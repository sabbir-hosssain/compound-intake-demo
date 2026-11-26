"""S2.4 baseline matcher (SPEC §6): rapidfuzz token-set ratio, no LLM."""

import ast
import io
import json
import time
import tokenize
from pathlib import Path

import pytest

from intake import baseline
from intake.baseline import (
    NO_MATCH_CUTOFF,
    baseline_match,
    decision_correct,
    formula_string,
    raw_text,
    tune_cutoff,
)
from intake.library import load_formulas
from intake.match import TOP_K, MatchResult
from intake.models import Formula, ProposalStatus

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "golden" / "golden_cases.jsonl"
FORMULAS = load_formulas()


def _formula(fid: str, name: str, ingredients: list[tuple[str, float, str]]) -> Formula:
    return Formula(
        formula_id=fid,
        version="1.0",
        name=name,
        ingredients=[{"name": n, "strength": s, "unit": u, "illustrative_max": s * 2} for n, s, u in ingredients],
        dosage_form="cream",
        route="topical",
        illustrative=True,
    )


TOY = [
    _formula("SHF-901", "Alpha Cream", [("alphaol", 1.0, "%")]),
    _formula("SHF-902", "Beta Gel", [("betaine", 2.0, "%"), ("gammane", 5.0, "%")]),
    _formula("SHF-903", "Delta Ointment", [("deltazole", 0.5, "%")]),
    _formula("SHF-904", "Epsilon Lotion", [("epsilonine", 3.0, "%")]),
]


def _golden(split: str) -> list[dict]:
    rows = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r["split"] == split]


def _run(case: dict, cutoff: float = NO_MATCH_CUTOFF) -> MatchResult:
    return baseline_match(raw_text(case["raw"]["text"], case["raw"].get("notes")), FORMULAS, cutoff=cutoff)


# --- AC 1: token-set ratio on raw text vs formula name + ingredient string ---------------------


def test_formula_string_has_name_and_ingredients() -> None:
    s = formula_string(TOY[1])
    assert s.startswith("Beta Gel")
    assert "betaine 2%" in s and "gammane 5%" in s


def test_raw_text_joins_notes() -> None:
    assert raw_text("a", None) == "a"
    assert raw_text("a", "") == "a"
    assert raw_text("a", "b") == "a\nb"


def test_exact_formula_text_scores_one_and_ranks_first() -> None:
    result = baseline_match(formula_string(TOY[1]), TOY, cutoff=0.5)
    assert result.candidates[0].formula_id == "SHF-902"
    assert result.candidates[0].score == 1.0
    assert result.candidates[0].component_scores == {"token_set": 1.0}
    assert result.status == ProposalStatus.PROPOSED


def test_token_set_ignores_order_and_extra_words() -> None:
    result = baseline_match("Rx: please compound gammane 5% betaine 2% beta gel, qty 30 g", TOY, cutoff=0.5)
    assert result.candidates[0].formula_id == "SHF-902"


def test_top_three_sorted_with_margin() -> None:
    result = baseline_match("delta ointment deltazole", TOY, cutoff=0.0)
    assert len(result.candidates) == TOP_K == 3
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert result.confidence == scores[0]
    assert result.margin == pytest.approx(scores[0] - scores[1])


def test_ties_break_by_formula_id() -> None:
    result = baseline_match("zzz unrelated", TOY, cutoff=0.0)
    tied = [c for c in result.candidates if c.score == result.confidence]
    assert [c.formula_id for c in tied] == sorted(c.formula_id for c in tied)


def test_below_cutoff_is_no_match() -> None:
    result = baseline_match("completely unrelated words", TOY, cutoff=0.99)
    assert result.status == ProposalStatus.NO_MATCH
    assert len(result.candidates) == 3  # candidates are still shown


def test_cutoff_is_inclusive() -> None:
    top = baseline_match(formula_string(TOY[0]), TOY, cutoff=0.0).confidence
    assert baseline_match(formula_string(TOY[0]), TOY, cutoff=top).status == ProposalStatus.PROPOSED


def test_empty_text_and_empty_library() -> None:
    assert baseline_match("", TOY).status == ProposalStatus.NO_MATCH
    empty = baseline_match("beta gel", [])
    assert empty.candidates == [] and empty.confidence == 0.0 and empty.status == ProposalStatus.NO_MATCH


def test_baseline_adds_no_flags() -> None:
    assert baseline_match("beta gel", TOY).flags == []


def test_deterministic() -> None:
    text = "salicylic acid 3% urea 10% cream"
    assert baseline_match(text, FORMULAS) == baseline_match(text, FORMULAS)


def test_no_llm_or_audit_imports() -> None:
    tree = ast.parse(Path(baseline.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    banned = ("anthropic", "intake.extract", "intake.explain", "intake.adapters", "intake.audit", "intake.pipeline")
    assert not [m for m in imported if m.startswith(banned)]


# --- cut-off tuning ----------------------------------------------------------------------------


def test_decision_correct() -> None:
    proposed = baseline_match(formula_string(TOY[0]), TOY, cutoff=0.5)
    assert decision_correct(proposed, "SHF-901")
    assert not decision_correct(proposed, "SHF-902")
    assert not decision_correct(proposed, "NO_MATCH")
    rejected = baseline_match(formula_string(TOY[0]), TOY, cutoff=1.01)
    assert decision_correct(rejected, "NO_MATCH")
    assert not decision_correct(rejected, "SHF-901")


def test_tune_cutoff_picks_middle_of_best_plateau() -> None:
    # Gold NO_MATCH scored 0.40; gold match scored 0.70 → any cut in (0.40, 0.70] is perfect.
    pairs = [(0.40, "SHF-901", "NO_MATCH"), (0.70, "SHF-902", "SHF-902")]
    assert tune_cutoff(pairs) == pytest.approx(0.55)


def test_tune_cutoff_ignores_cases_no_cutoff_can_fix() -> None:
    # A wrong top-1 on a matchable case is wrong at every cut-off, so it must not move the choice.
    pairs = [(0.40, "SHF-901", "NO_MATCH"), (0.70, "SHF-902", "SHF-902"), (0.90, "SHF-901", "SHF-903")]
    assert tune_cutoff(pairs) == pytest.approx(0.55)


def test_tune_cutoff_needs_cases() -> None:
    with pytest.raises(ValueError):
        tune_cutoff([])


def test_shipped_cutoff_is_reproduced_from_dev_split_only() -> None:
    dev = _golden("dev")
    assert dev and {c["split"] for c in dev} == {"dev"}
    pairs = [
        (r.confidence, r.candidates[0].formula_id, c["expected_formula_id"])
        for c in dev
        for r in [_run(c, cutoff=0.0)]
    ]
    # S2.9 added two dev cases, which moved the middle of the optimal plateau from 0.80 to 0.79.
    # The shipped cut-off stays frozen (Gate 2) and must remain optimal on dev.
    best = sum(baseline._correct_at(tune_cutoff(pairs), *p) for p in pairs)
    shipped = sum(baseline._correct_at(NO_MATCH_CUTOFF, *p) for p in pairs)
    assert shipped == best


def test_dev_quality_floor() -> None:
    """Pins the tuned result so an accidental change to scoring shows up (DECISIONS-LOG #14)."""
    dev = _golden("dev")
    results = [(_run(c), c["expected_formula_id"]) for c in dev]
    matchable = [(r, g) for r, g in results if g != "NO_MATCH"]
    top3 = sum(g in {c.formula_id for c in r.candidates} for r, g in matchable)
    assert top3 == len(matchable)
    assert sum(decision_correct(r, g) for r, g in results) >= 34


# --- S3.7: cut-off read from eval/thresholds.yaml ----------------------------------------------

THRESHOLDS_FILE = ROOT / "eval" / "thresholds.yaml"


def test_cutoff_comes_from_thresholds_yaml() -> None:
    assert baseline.load_no_match_cutoff(THRESHOLDS_FILE) == pytest.approx(0.80)
    assert NO_MATCH_CUTOFF == pytest.approx(0.80)


def test_cutoff_is_not_a_literal_in_baseline_source() -> None:
    source = Path(baseline.__file__).read_text(encoding="utf-8")
    numbers = [
        float(tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.NUMBER
    ]
    assert 0.8 not in numbers


def test_load_cutoff_reads_the_given_file(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    path.write_text("T_match: 0.5\nbaseline_no_match_cutoff: 0.42\n")
    assert baseline.load_no_match_cutoff(path) == pytest.approx(0.42)


def test_load_cutoff_fails_loudly_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        baseline.load_no_match_cutoff(tmp_path / "missing.yaml")


@pytest.mark.parametrize(
    "content",
    [
        "",
        "T_match: 0.5\n",
        "baseline_no_match_cutoff:\n",
        "baseline_no_match_cutoff: high\n",
        "baseline_no_match_cutoff: true\n",
        "baseline_no_match_cutoff: [0.8]\n",
        "baseline_no_match_cutoff: -0.1\n",
        "baseline_no_match_cutoff: 1.5\n",
        "baseline_no_match_cutoff: .nan\n",
        "- baseline_no_match_cutoff\n",
    ],
)
def test_load_cutoff_fails_loudly_when_key_missing_or_malformed(tmp_path: Path, content: str) -> None:
    path = tmp_path / "t.yaml"
    path.write_text(content)
    with pytest.raises(ValueError):
        baseline.load_no_match_cutoff(path)


def test_load_cutoff_accepts_integer_bounds(tmp_path: Path) -> None:
    path = tmp_path / "t.yaml"
    for value in ("0", "1"):
        path.write_text(f"baseline_no_match_cutoff: {value}\n")
        assert baseline.load_no_match_cutoff(path) == float(value)


# --- AC 2: runtime -----------------------------------------------------------------------------


def test_runs_on_golden_set_under_five_seconds() -> None:
    rows = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 64
    start = time.perf_counter()
    formulas = load_formulas()
    results = [baseline_match(raw_text(r["raw"]["text"], r["raw"].get("notes")), formulas) for r in rows]
    elapsed = time.perf_counter() - start
    assert len(results) == 64
    assert elapsed < 5.0, f"baseline took {elapsed:.2f}s on the golden set"
