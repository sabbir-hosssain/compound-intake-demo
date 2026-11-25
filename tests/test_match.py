"""S1.6: formula library loader and matcher (SPEC §6)."""

import ast
from pathlib import Path

import pytest
import yaml

from intake.library import library_version, load_alias_map, load_formulas
from intake.match import (
    MATCH_VERSION,
    Thresholds,
    load_thresholds,
    match,
    score_formula,
    strength_credit,
)
from intake.models import Extraction, Flag, Ingredient, ProposalStatus, Severity, Unit

ROOT = Path(__file__).resolve().parents[1]
FORMULAS = ROOT / "data" / "formulas"
THRESHOLDS = ROOT / "eval" / "thresholds.yaml"


@pytest.fixture(scope="module")
def formulas():
    return load_formulas(FORMULAS)


@pytest.fixture(scope="module")
def aliases():
    return load_alias_map(FORMULAS / "ingredient_master.yaml")


@pytest.fixture(scope="module")
def thresholds() -> Thresholds:
    return load_thresholds(THRESHOLDS)


def _by_id(formulas, formula_id):
    return next(f for f in formulas if f.formula_id == formula_id)


def _exact(formula) -> Extraction:
    """An extraction that mirrors a formula exactly."""
    return Extraction(
        ingredients=[Ingredient(name=i.name, strength=i.strength, unit=i.unit) for i in formula.ingredients],
        dosage_form=formula.dosage_form,
        base=formula.base,
        route=formula.route,
    )


def _write_thresholds(tmp_path: Path, **overrides) -> Path:
    data = yaml.safe_load(THRESHOLDS.read_text())
    data.update(overrides)
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


# --- library -----------------------------------------------------------------------------------


def test_load_formulas_reads_seed_library(formulas):
    assert [f.formula_id for f in formulas] == ["SHF-001", "SHF-002", "SHF-003"]
    assert all(f.illustrative for f in formulas)


def test_alias_map_maps_alias_and_name_to_canonical(aliases):
    assert aliases["carbamide"] == "urea"
    assert aliases["lignocaine"] == "lidocaine"
    assert aliases["urea"] == "urea"


def test_library_version_is_stable_and_content_based(tmp_path):
    assert library_version(FORMULAS) == library_version(FORMULAS)
    for src in FORMULAS.glob("SHF-*.yaml"):
        (tmp_path / src.name).write_text(src.read_text())
    assert library_version(tmp_path) == library_version(FORMULAS)
    (tmp_path / "SHF-001.yaml").write_text((FORMULAS / "SHF-001.yaml").read_text().replace("3.0", "4.0"))
    assert library_version(tmp_path) != library_version(FORMULAS)


# --- thresholds come from eval/thresholds.yaml -------------------------------------------------


def test_thresholds_loaded_from_yaml(thresholds):
    raw = yaml.safe_load(THRESHOLDS.read_text())
    assert thresholds.weights == raw["weights"]
    assert thresholds.T_match == raw["T_match"]
    assert thresholds.T_margin == raw["T_margin"]
    assert thresholds.strength_tolerance.full_credit_pct == raw["strength_tolerance"]["full_credit_pct"]
    assert thresholds.strength_tolerance.zero_credit_pct == raw["strength_tolerance"]["zero_credit_pct"]


def test_weights_change_scores(tmp_path, formulas, aliases):
    """Changing only the YAML weights changes the score: nothing is hard-coded."""
    weights = {"ingredients": 0.0, "strength": 0.0, "dosage_form": 1.0, "base": 0.0, "route": 0.0}
    custom = load_thresholds(_write_thresholds(tmp_path, weights=weights))
    shf1 = _by_id(formulas, "SHF-001")
    extraction = Extraction(dosage_form="cream")
    assert score_formula(extraction, shf1, custom, aliases).score == pytest.approx(1.0)


def test_t_match_read_from_yaml(tmp_path, formulas, aliases):
    shf1 = _by_id(formulas, "SHF-001")
    strict = load_thresholds(_write_thresholds(tmp_path, T_match=1.01))
    result = match(_exact(shf1), formulas, strict, aliases)
    assert result.status == ProposalStatus.NO_MATCH


def test_strength_tolerance_read_from_yaml(tmp_path):
    custom = load_thresholds(
        _write_thresholds(tmp_path, strength_tolerance={"full_credit_pct": 20, "zero_credit_pct": 40})
    )
    assert strength_credit(12.0, 10.0, custom) == pytest.approx(1.0)
    assert strength_credit(13.0, 10.0, custom) == pytest.approx(0.5)
    assert strength_credit(14.0, 10.0, custom) == pytest.approx(0.0)


def test_thresholds_reject_weights_not_summing_to_one(tmp_path):
    bad = {"ingredients": 0.5, "strength": 0.5, "dosage_form": 0.5, "base": 0.0, "route": 0.0}
    with pytest.raises(ValueError):
        load_thresholds(_write_thresholds(tmp_path, weights=bad))


def test_match_module_has_no_numeric_weight_literals():
    """Guard against hard-coding: SPEC weights/thresholds must not appear as literals in match.py."""
    tree = ast.parse((ROOT / "src" / "intake" / "match.py").read_text())
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, float)}
    assert not literals & {0.40, 0.25, 0.15, 0.10, 0.60}


# --- strength decay ±10% → ±50% ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (10.0, 1.0),  # exact
        (11.0, 1.0),  # +10%
        (9.0, 1.0),  # -10%
        (13.0, 0.5),  # +30%: halfway between 10% and 50%
        (7.0, 0.5),  # -30%
        (12.0, 0.75),  # +20%
        (15.0, 0.0),  # +50%
        (5.0, 0.0),  # -50%
        (20.0, 0.0),  # beyond +50%
    ],
)
def test_strength_decay(given, expected, thresholds):
    assert strength_credit(given, 10.0, thresholds) == pytest.approx(expected)


def test_strength_component_on_seed_formula(formulas, thresholds, aliases):
    shf1 = _by_id(formulas, "SHF-001")
    extraction = _exact(shf1).model_copy(
        update={
            "ingredients": [
                Ingredient(name="salicylic acid", strength=3.9, unit=Unit.PERCENT),  # +30% -> 0.5
                Ingredient(name="urea", strength=10.0, unit=Unit.PERCENT),  # exact -> 1.0
            ]
        }
    )
    candidate = score_formula(extraction, shf1, thresholds, aliases)
    assert candidate.component_scores["strength"] == pytest.approx(0.75)


def test_strength_needs_matching_unit_and_value(formulas, thresholds, aliases):
    shf2 = _by_id(formulas, "SHF-002")
    extraction = Extraction(
        ingredients=[
            Ingredient(name="lidocaine", strength=4.0, unit=Unit.MG),  # wrong unit -> 0
            Ingredient(name="menthol", strength=None, unit=None),  # no strength -> 0
        ]
    )
    candidate = score_formula(extraction, shf2, thresholds, aliases)
    assert candidate.component_scores["strength"] == 0.0
    assert candidate.component_scores["ingredients"] == pytest.approx(1.0)


# --- scoring on seed formulas ------------------------------------------------------------------


@pytest.mark.parametrize("formula_id", ["SHF-001", "SHF-002", "SHF-003"])
def test_exact_extraction_scores_one_and_wins(formula_id, formulas, thresholds, aliases):
    target = _by_id(formulas, formula_id)
    result = match(_exact(target), formulas, thresholds, aliases)
    top = result.candidates[0]
    assert top.formula_id == formula_id
    assert top.formula_version == target.version
    assert top.score == pytest.approx(1.0)
    assert result.confidence == pytest.approx(1.0)
    assert result.status == ProposalStatus.PROPOSED
    assert set(top.component_scores) == {"ingredients", "strength", "dosage_form", "base", "route"}


def test_jaccard_and_aliases(formulas, thresholds, aliases):
    shf1 = _by_id(formulas, "SHF-001")
    extraction = Extraction(
        ingredients=[
            Ingredient(name="Carbamide", strength=10.0, unit=Unit.PERCENT),  # alias of urea
            Ingredient(name="menthol", strength=1.0, unit=Unit.PERCENT),
        ]
    )
    candidate = score_formula(extraction, shf1, thresholds, aliases)
    # {urea, menthol} vs {salicylic acid, urea}: 1 / 3
    assert candidate.component_scores["ingredients"] == pytest.approx(1 / 3)


def test_text_fields_compared_case_insensitively(formulas, thresholds, aliases):
    shf3 = _by_id(formulas, "SHF-003")
    extraction = Extraction(dosage_form="Oral  Suspension", route="ORAL", base=None)
    candidate = score_formula(extraction, shf3, thresholds, aliases)
    assert candidate.component_scores["dosage_form"] == 1.0
    assert candidate.component_scores["route"] == 1.0
    assert candidate.component_scores["base"] == 0.0


def test_weighted_total(formulas, thresholds, aliases):
    shf2 = _by_id(formulas, "SHF-002")
    extraction = Extraction(
        ingredients=[Ingredient(name="lidocaine", strength=4.0, unit=Unit.PERCENT)],
        dosage_form="gel",
        route="topical",
    )
    candidate = score_formula(extraction, shf2, thresholds, aliases)
    w = thresholds.weights
    expected = w["ingredients"] * 0.5 + w["strength"] * 0.5 + w["dosage_form"] + w["route"]
    assert candidate.score == pytest.approx(expected)


def test_returns_top_three_sorted_with_margin(formulas, thresholds, aliases):
    shf2 = _by_id(formulas, "SHF-002")
    result = match(_exact(shf2), formulas, thresholds, aliases)
    assert len(result.candidates) == 3
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores, reverse=True)
    assert result.confidence == pytest.approx(scores[0])
    assert result.margin == pytest.approx(scores[0] - scores[1])


def test_at_most_three_candidates(tmp_path, formulas, thresholds, aliases):
    extra = [f.model_copy(update={"formula_id": f"SHF-{900 + i}"}) for i, f in enumerate(formulas)]
    result = match(_exact(formulas[0]), [*formulas, *extra], thresholds, aliases)
    assert len(result.candidates) == 3


def test_deterministic(formulas, thresholds, aliases):
    extraction = Extraction(dosage_form="cream", route="topical")
    first = match(extraction, formulas, thresholds, aliases)
    second = match(extraction, list(reversed(formulas)), thresholds, aliases)
    assert first == second
    # ties broken by formula_id
    tied = [c for c in first.candidates if c.score == first.candidates[1].score]
    assert [c.formula_id for c in tied] == sorted(c.formula_id for c in tied)


# --- NO_MATCH and M-01 -------------------------------------------------------------------------


def test_no_match_below_t_match(formulas, thresholds, aliases):
    extraction = Extraction(ingredients=[Ingredient(name="zinc oxide", strength=20.0, unit=Unit.PERCENT)])
    result = match(extraction, formulas, thresholds, aliases)
    assert result.confidence < thresholds.T_match
    assert result.status == ProposalStatus.NO_MATCH


def test_empty_extraction_is_no_match(formulas, thresholds, aliases):
    result = match(Extraction(), formulas, thresholds, aliases)
    assert result.status == ProposalStatus.NO_MATCH
    assert result.confidence == 0.0


def test_empty_library_is_no_match(thresholds, aliases):
    result = match(Extraction(dosage_form="cream"), [], thresholds, aliases)
    assert result.status == ProposalStatus.NO_MATCH
    assert result.candidates == []
    assert result.confidence == 0.0
    assert result.margin == 0.0


def test_m01_when_margin_below_t_margin(formulas, thresholds, aliases):
    shf1 = _by_id(formulas, "SHF-001")
    clone = shf1.model_copy(update={"formula_id": "SHF-901"})
    result = match(_exact(shf1), [shf1, clone], thresholds, aliases)
    assert result.margin < thresholds.T_margin
    m01 = [f for f in result.flags if f.rule_id == "M-01"]
    assert len(m01) == 1
    assert m01[0].severity == Severity.REVIEW
    assert m01[0].rule_version == MATCH_VERSION
    assert m01[0].source_pass == 2


def test_no_m01_when_margin_clear(formulas, thresholds, aliases):
    result = match(_exact(_by_id(formulas, "SHF-003")), formulas, thresholds, aliases)
    assert result.margin >= thresholds.T_margin
    assert [f.rule_id for f in result.flags] == []


def test_existing_flags_kept_first_and_unchanged(formulas, thresholds, aliases):
    existing = [
        Flag(rule_id="R1-05", rule_version="0.1.0", severity=Severity.BLOCK, message="x", source_pass=1),
        Flag(rule_id="R2-01", rule_version="0.1.0", severity=Severity.BLOCK, message="y", source_pass=2),
    ]
    shf1 = _by_id(formulas, "SHF-001")
    clone = shf1.model_copy(update={"formula_id": "SHF-901"})
    result = match(_exact(shf1), [shf1, clone], thresholds, aliases, existing=existing)
    assert result.flags[: len(existing)] == existing
    assert [f.rule_id for f in result.flags] == ["R1-05", "R2-01", "M-01"]

    clear = match(_exact(shf1), formulas, thresholds, aliases, existing=existing)
    assert clear.flags == existing
