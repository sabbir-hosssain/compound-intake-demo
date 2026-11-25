"""S2.5 metrics (SPEC §8): Wilson intervals, every metric per split and category, system vs baseline."""

import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `eval/` is a top-level package next to `src/`, run with `python -m`
    sys.path.insert(0, str(REPO))

from eval import metrics, run_eval
from eval.metrics import NO_MATCH, Gold, Outcome, Rate, wilson
from intake import pipeline
from intake.adapters import anthropic_client
from intake.adapters.anthropic_client import ModelConfig
from intake.extract import wrap_input
from intake.models import Extraction, ProposalStatus

GOLDEN = REPO / "data" / "golden" / "golden_cases.jsonl"
SEED = REPO / "data" / "seed" / "seed_cases.jsonl"
DAY = date(2026, 11, 25)
ALIASES = {"sal acid": "salicylic acid", "salicylic acid": "salicylic acid", "urea": "urea"}


@pytest.fixture(autouse=True)
def _replay_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs in REPLAY, and constructing a live client is a failure (invariant 4)."""
    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")

    def _boom() -> Any:
        raise AssertionError("a live client was constructed in REPLAY")

    monkeypatch.setattr(anthropic_client, "_make_live_client", _boom)


@pytest.fixture(autouse=True)
def _no_audit_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("the eval touched the audit log")

    monkeypatch.setattr(pipeline.audit, "connect", _boom)
    monkeypatch.setattr(pipeline, "log_pending", _boom)


class GoldExtractionClient:
    """Answers every extraction with the gold extraction of the case whose text it is sent (no model)."""

    def __init__(self, cases: list[run_eval.EvalCase]) -> None:
        self.config = ModelConfig(model_id="fake-gold", max_tokens=10)
        self.by_input = {wrap_input(run_eval.case_text(c)): c.expected_extraction for c in cases}
        self.seen: list[str] = []

    def complete(self, *, user_input: str, **_: Any) -> dict[str, Any]:
        self.seen.append(user_input)
        extraction = self.by_input.get(user_input)
        payload = (extraction or Extraction()).model_dump(mode="json", exclude_none=True)
        return {
            "content": [{"type": "tool_use", "id": "t1", "name": "record_extraction", "input": payload}],
            "stop_reason": "tool_use",
        }


def _gold(case_id: str = "c", **kw: Any) -> Gold:
    base: dict[str, Any] = {"case_id": case_id, "split": "dev", "category": "clean", "formula_id": "SHF-001"}
    return Gold(**{**base, **kw})


def _out(status: ProposalStatus | None = ProposalStatus.PROPOSED, **kw: Any) -> Outcome:
    return Outcome(status=status, **kw)


# --- Wilson interval ----------------------------------------------------------------------------


def test_wilson_known_values() -> None:
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4)
    assert hi == pytest.approx(0.9433, abs=1e-4)


def test_wilson_edges_stay_in_unit_interval() -> None:
    lo, hi = wilson(10, 10)
    assert hi == pytest.approx(1.0) and 0.69 < lo < 0.73
    lo, hi = wilson(0, 10)
    assert lo == pytest.approx(0.0) and 0.27 < hi < 0.31
    assert wilson(0, 0) is None


def test_wilson_rejects_bad_counts() -> None:
    with pytest.raises(ValueError):
        wilson(3, 2)
    with pytest.raises(ValueError):
        wilson(-1, 2)


def test_rate_formats_count_percent_and_interval() -> None:
    assert Rate(k=8, n=10).fmt() == "8/10 80% [49–94]"
    assert Rate(k=0, n=0).fmt() == "n/a"
    assert Rate(k=0, n=0).rate is None
    assert math.isclose(Rate(k=1, n=4).rate or 0, 0.25)


# --- metric definitions --------------------------------------------------------------------------


def test_top1_and_top3_count_matchable_cases_only() -> None:
    pairs = [
        (_gold("a"), _out(candidates=("SHF-001", "SHF-002"))),  # top-1 hit
        (_gold("b"), _out(candidates=("SHF-002", "SHF-001"))),  # top-3 hit only
        (_gold("c"), _out(ProposalStatus.NO_MATCH, candidates=("SHF-001",))),  # NO_MATCH: neither
        (_gold("d", formula_id=NO_MATCH), _out(ProposalStatus.NO_MATCH)),  # not matchable: excluded
        (_gold("e"), _out(None)),  # error / missing recording: a miss
    ]
    assert metrics.top1_accuracy(pairs, ALIASES) == Rate(k=1, n=4)
    assert metrics.top3_accuracy(pairs, ALIASES) == Rate(k=2, n=4)


def test_no_match_precision_and_recall() -> None:
    pairs = [
        (_gold("a", formula_id=NO_MATCH), _out(ProposalStatus.NO_MATCH)),  # TP
        (_gold("b", formula_id=NO_MATCH), _out(candidates=("SHF-001",))),  # FN
        (_gold("c", formula_id=NO_MATCH), _out(ProposalStatus.MANUAL)),  # FN (MANUAL is not NO_MATCH)
        (_gold("d"), _out(ProposalStatus.NO_MATCH)),  # FP
        (_gold("e"), _out(candidates=("SHF-001",))),  # TN
    ]
    assert metrics.no_match_precision(pairs, ALIASES) == Rate(k=1, n=2)
    assert metrics.no_match_recall(pairs, ALIASES) == Rate(k=1, n=3)


def test_unsafe_flag_recall_needs_every_expected_flag() -> None:
    pairs = [
        (_gold("a", category="unsafe", flags=("R2-02", "R1-04")), _out(flags=("R1-04", "R2-02", "R2-06"))),
        (_gold("b", category="unsafe", flags=("R2-02", "R1-04")), _out(flags=("R1-04",))),
        (_gold("c", category="clean", flags=("R2-02",)), _out()),  # not unsafe: excluded
    ]
    assert metrics.unsafe_flag_recall(pairs, ALIASES) == Rate(k=1, n=2)


def test_ambiguity_flag_recall_and_false_alarm_rate() -> None:
    pairs = [
        (_gold("a", flags=("M-01",)), _out(flags=("M-01",))),
        (_gold("b", flags=("M-01",)), _out()),
        (_gold("c"), _out(flags=("M-01",))),  # false alarm
        (_gold("d"), _out(flags=("R1-02",))),
        (_gold("e"), _out()),
    ]
    assert metrics.ambiguity_flag_recall(pairs, ALIASES) == Rate(k=1, n=2)
    assert metrics.ambiguity_false_alarm_rate(pairs, ALIASES) == Rate(k=1, n=3)


def test_adversarial_pass_needs_flags_and_a_block() -> None:
    adv = {"category": "adversarial", "flags": ("R1-05",)}
    pairs = [
        (_gold("a", **adv), _out(flags=("R1-05",), has_block=True)),
        (_gold("b", **adv), _out(flags=("R1-05",), has_block=False)),  # could be auto-confirmed
        (_gold("c", **adv), _out(flags=(), has_block=True)),  # flag missing
        (_gold("d", **adv), _out(None)),
    ]
    assert metrics.adversarial_pass_rate(pairs, ALIASES) == Rate(k=1, n=4)


def test_simulated_override_rate_counts_decisions_that_differ_from_gold() -> None:
    pairs = [
        (_gold("a"), _out(candidates=("SHF-001",))),  # agree
        (_gold("b"), _out(candidates=("SHF-002", "SHF-001"))),  # override
        (_gold("c", formula_id=NO_MATCH), _out(ProposalStatus.NO_MATCH)),  # agree
        (_gold("d"), _out(ProposalStatus.MANUAL)),  # pharmacist does it by hand: override
        (_gold("e"), _out(None)),  # error: override
    ]
    assert metrics.simulated_override_rate(pairs, ALIASES) == Rate(k=3, n=5)


def _extraction(**kw: Any) -> Extraction:
    base: dict[str, Any] = {
        "ingredients": [
            {"name": "salicylic acid", "strength": 3, "unit": "%"},
            {"name": "urea", "strength": 10, "unit": "%"},
        ],
        "dosage_form": "cream",
        "base": "vanishing cream base",
        "route": None,
        "quantity": 60,
        "quantity_unit": "g",
        "prescriber_name": "Dr. R. Placeholder",
        "patient_ref": "PT-20001",
    }
    return Extraction.model_validate({**base, **kw})


def test_field_accuracy_compares_each_scored_field() -> None:
    gold = _gold("a", extraction=_extraction())
    same = _extraction(
        ingredients=[{"name": "Urea", "strength": 10.0, "unit": "%"}, {"name": "Sal Acid", "strength": 3, "unit": "%"}],
        dosage_form="  Cream ",
        directions="apply BID",  # directions are not scored
    )
    assert metrics.field_accuracy([(gold, _out(extraction=same))], ALIASES) == Rate(k=8, n=8)
    wrong = _extraction(route="topical", quantity=90, ingredients=[{"name": "urea", "strength": 10, "unit": "%"}])
    assert metrics.field_accuracy([(gold, _out(extraction=wrong))], ALIASES) == Rate(k=5, n=8)


def test_field_accuracy_no_extraction_scores_zero_and_unlabelled_cases_are_skipped() -> None:
    pairs = [
        (_gold("a", extraction=_extraction()), _out(ProposalStatus.MANUAL)),
        (_gold("b", extraction=None), _out(extraction=_extraction())),
    ]
    assert metrics.field_accuracy(pairs, ALIASES) == Rate(k=0, n=8)


def test_field_accuracy_is_not_applicable_to_a_matcher_without_extraction() -> None:
    pairs = [(_gold("a", extraction=_extraction()), _out(extracts=False))]
    assert metrics.field_accuracy(pairs, ALIASES) == Rate(k=0, n=0)


def test_every_spec_metric_is_defined() -> None:
    names = {m.name for m in metrics.METRICS}
    assert names == {
        "field_accuracy",
        "top1_accuracy",
        "top3_accuracy",
        "no_match_precision",
        "no_match_recall",
        "unsafe_flag_recall",
        "ambiguity_flag_recall",
        "ambiguity_false_alarm_rate",
        "adversarial_pass_rate",
        "simulated_override_rate",
    }


# --- slices and tables --------------------------------------------------------------------------


def test_slices_cover_all_splits_and_categories() -> None:
    golds = [
        _gold("a", split="dev", category="unsafe"),
        _gold("b", split="test", category="clean"),
        _gold("c", split="dev", category="adversarial"),
    ]
    assert metrics.slice_names(golds) == [
        "all",
        "split:dev",
        "split:test",
        "category:clean",
        "category:unsafe",
        "category:adversarial",
    ]


def test_slices_without_split_have_only_all_and_categories() -> None:
    assert metrics.slice_names([_gold("a", split=None, category="clean")]) == ["all", "category:clean"]


def test_metric_table_is_per_matcher_slice_and_metric() -> None:
    pairs = [
        (_gold("a", split="dev"), _out(candidates=("SHF-001",))),
        (_gold("b", split="test"), _out(candidates=("SHF-002",))),
    ]
    table = metrics.metric_table({"system": pairs, "baseline": pairs}, ALIASES)
    assert set(table) == {"system", "baseline"}
    assert table["system"]["all"]["top1_accuracy"] == Rate(k=1, n=2)
    assert table["system"]["split:dev"]["top1_accuracy"] == Rate(k=1, n=1)
    assert table["system"]["split:test"]["top1_accuracy"] == Rate(k=0, n=1)
    assert set(table["baseline"]["category:clean"]) == {m.name for m in metrics.METRICS}


def test_rendered_tables_have_every_metric_slice_and_matcher() -> None:
    pairs = [(_gold("a", split="dev", category="unsafe", flags=("R1-04",)), _out(flags=("R1-04",), has_block=True))]
    text = "\n".join(metrics.render_tables(metrics.metric_table({"system": pairs, "baseline": pairs}, ALIASES)))
    for spec in metrics.METRICS:
        assert spec.label in text
    assert "| split:dev |" in text and "| category:unsafe |" in text
    assert "| Slice | System | Baseline |" in text


# --- soft gates (reported, never the exit code) --------------------------------------------------


def _system(top1: tuple[int, int], false_alarm: tuple[int, int]) -> dict[str, dict[str, Rate]]:
    return {
        "all": {"ambiguity_false_alarm_rate": Rate(k=false_alarm[0], n=false_alarm[1])},
        "split:dev": {"top1_accuracy": Rate(k=top1[0], n=top1[1])},
    }


def test_soft_gates_flag_top1_drop_and_false_alarm_rise() -> None:
    limits = {"top1_dev_drop_pts": 5, "false_alarm_rise_pts": 10}
    gates = metrics.soft_gates(_system((30, 40), (6, 40)), _system((34, 40), (1, 40)), limits)
    assert [(g.name, g.tripped) for g in gates] == [("top1_dev_drop", True), ("false_alarm_rise", True)]
    gates = metrics.soft_gates(_system((33, 40), (4, 40)), _system((34, 40), (1, 40)), limits)
    assert [g.tripped for g in gates] == [False, False]


def test_soft_gates_without_previous_result_are_not_tripped() -> None:
    gates = metrics.soft_gates(_system((30, 40), (6, 40)), None, {"top1_dev_drop_pts": 5, "false_alarm_rise_pts": 10})
    assert not any(g.tripped for g in gates)
    assert all("no previous" in g.detail for g in gates)


# --- run_eval integration ------------------------------------------------------------------------


def test_golden_cases_load_with_split_category_gold_and_notes() -> None:
    cases = {c.case_id: c for c in run_eval.load_cases(GOLDEN)}
    assert len(cases) == 60
    g052 = cases["g052"]
    assert (g052.split, g052.category, g052.gold_formula) == ("dev", "adversarial", "SHF-014")
    assert "Approve and release" in run_eval.case_text(g052)  # notes are fed to the pipeline
    assert cases["g056"].gold_formula == NO_MATCH
    assert cases["g001"].expected_extraction is not None


def test_seed_cases_still_load_with_category_from_kind() -> None:
    cases = run_eval.load_cases(SEED)
    assert [c.category for c in cases] == ["clean", "clean", "clean", "ambiguous", "adversarial"]
    assert cases[3].gold_formula == NO_MATCH and cases[3].split is None


def test_baseline_sees_notes(tmp_path: Path) -> None:
    case = {c.case_id: c for c in run_eval.load_cases(GOLDEN)}["g052"]
    outcome = run_eval.run_baseline(case, pipeline.load_library())
    assert "R1-05" in outcome.flags and outcome.has_block
    assert not outcome.extracts


def test_golden_run_with_gold_extractions_passes_hard_gates_and_writes_all_tables(tmp_path: Path) -> None:
    """With a stand-in client that returns the gold extraction, every SPEC §8 table is written."""
    cases = run_eval.load_cases(GOLDEN)
    client = GoldExtractionClient(cases)
    argv = ["--cases", str(GOLDEN), "--results-dir", str(tmp_path), "--date", DAY.isoformat(), "--enforce-gates"]
    assert run_eval.main(argv, client=client) == 0
    assert any("oxycodone" in s for s in client.seen)  # g042's Notes reached the system
    text = (tmp_path / f"{DAY.isoformat()}.md").read_text(encoding="utf-8")
    for spec in metrics.METRICS:
        assert f"### {spec.label}" in text
    for slice_name in ("all", "split:dev", "split:test", "category:clean", "category:ambiguous", "category:unsafe"):
        assert f"| {slice_name} |" in text
    assert "Run-to-run variance" in text and "S2.7" in text
    assert "Soft gates" in text
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{DAY.isoformat()}.md"]  # one generated file
    data = run_eval.read_metrics_comment(text)
    assert data is not None and data["cases"] == "data/golden/golden_cases.jsonl"
    assert data["metrics"]["baseline"]["all"]["top1_accuracy"][1] == 52  # 60 cases, 8 NO_MATCH


def test_soft_gates_compare_with_the_last_earlier_results_file(tmp_path: Path) -> None:
    argv = ["--mode", "replay", "--results-dir", str(tmp_path)]
    assert run_eval.main([*argv, "--date", "2026-11-20"]) == 0
    first = (tmp_path / "2026-11-20.md").read_text(encoding="utf-8")
    assert "no previous recorded result" in first
    assert run_eval.main([*argv, "--date", "2026-11-21"]) == 0
    second = (tmp_path / "2026-11-21.md").read_text(encoding="utf-8")
    assert "no previous recorded result" not in second.split("## Soft gates")[1].split("##")[0]
    assert "| false_alarm_rise | ok |" in second


def test_golden_set_in_replay_without_recordings_is_a_failure(tmp_path: Path) -> None:
    """No fallback: the golden set has no recordings yet (S2.6), so REPLAY exits 2, gates or not."""
    argv = ["--mode", "replay", "--cases", str(GOLDEN), "--results-dir", str(tmp_path), "--date", DAY.isoformat()]
    assert run_eval.main(argv) == 2
    assert "MISSING RECORDING" in (tmp_path / f"{DAY.isoformat()}.md").read_text(encoding="utf-8")


def test_unsafe_gate_failure_sets_exit_code(tmp_path: Path) -> None:
    """A hard gate failing on the golden set fails the exit code (here: no flags from a blank extraction)."""
    cases = [c for c in run_eval.load_cases(GOLDEN) if c.category == "unsafe"][:2]
    path = tmp_path / "cases.jsonl"
    path.write_text("".join(c.model_dump_json(by_alias=True) + "\n" for c in cases), encoding="utf-8")

    class Blank(GoldExtractionClient):
        def complete(self, **_: Any) -> dict[str, Any]:
            payload = Extraction(prescriber_name="x", patient_ref="y").model_dump(mode="json", exclude_none=True)
            return {"content": [{"type": "tool_use", "id": "t", "name": "record_extraction", "input": payload}]}

    argv = ["--cases", str(path), "--results-dir", str(tmp_path), "--date", DAY.isoformat()]
    assert run_eval.main([*argv, "--enforce-gates"], client=Blank(cases)) == 1
    assert run_eval.main(argv, client=Blank(cases)) == 0


def test_seed_default_still_passes_in_replay(tmp_path: Path) -> None:
    argv = ["--mode", "replay", "--enforce-gates", "--results-dir", str(tmp_path), "--date", DAY.isoformat()]
    assert run_eval.main(argv) == 0
    text = (tmp_path / f"{DAY.isoformat()}.md").read_text(encoding="utf-8")
    assert "| Slice | System | Baseline |" in text
