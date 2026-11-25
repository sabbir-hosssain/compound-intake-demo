"""Code-scored formula matching (SPEC §6).

Every weight and threshold comes from `eval/thresholds.yaml` (protected); none is hard-coded here.
Score per formula = Σ weight[c] · component[c] over: ingredients (Jaccard on canonical names),
strength (per formula ingredient: full credit within ±full_credit_pct, linear to 0 at ±zero_credit_pct),
dosage_form, base, route (normalised exact match). Flags are only appended (invariant 2).
"""

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from intake.models import (
    Extraction,
    Flag,
    Formula,
    FormulaIngredient,
    Ingredient,
    MatchCandidate,
    ProposalStatus,
    Score,
    Severity,
)
from intake.rules import normalise_name

MATCH_VERSION = "0.1.0"
TOP_K = 3
COMPONENTS = ("ingredients", "strength", "dosage_form", "base", "route")
DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"
_PRECISION = 6  # decimal places kept in scores, so results are stable across float noise


class StrengthTolerance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_credit_pct: float = Field(ge=0)
    zero_credit_pct: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> "StrengthTolerance":
        if self.zero_credit_pct <= self.full_credit_pct:
            raise ValueError("zero_credit_pct must be greater than full_credit_pct")
        return self


class Thresholds(BaseModel):
    """The matcher's view of eval/thresholds.yaml. Unrelated keys (e.g. soft_gates) are ignored."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    weights: dict[str, float]
    strength_tolerance: StrengthTolerance
    T_match: float
    T_margin: float

    @model_validator(mode="after")
    def _weights_valid(self) -> "Thresholds":
        if set(self.weights) != set(COMPONENTS):
            raise ValueError(f"weights must have exactly the keys {COMPONENTS}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("weights must be non-negative")
        if not math.isclose(sum(self.weights.values()), 1, abs_tol=1e-6):
            raise ValueError("weights must sum to 1")
        return self


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[MatchCandidate] = Field(default_factory=list, max_length=TOP_K)
    confidence: Score
    margin: Score
    status: ProposalStatus
    flags: list[Flag] = Field(default_factory=list)


def load_thresholds(path: Path = DEFAULT_THRESHOLDS) -> Thresholds:
    return Thresholds.model_validate(yaml.safe_load(path.read_text()))


# --- components --------------------------------------------------------------------------------


def _canonical(name: str, aliases: Mapping[str, str]) -> str:
    key = normalise_name(name)
    return aliases.get(key, key)


def _norm_text(value: str | None) -> str | None:
    if value is None:
        return None
    return normalise_name(value) or None


def ingredient_similarity(extracted: set[str], formula: set[str]) -> float:
    """Jaccard similarity on canonical names; 0 when both sets are empty."""
    union = extracted | formula
    return len(extracted & formula) / len(union) if union else 0.0


def strength_credit(given: float, reference: float, thresholds: Thresholds) -> float:
    """1 within ±full_credit_pct of the reference, linear decay to 0 at ±zero_credit_pct."""
    tol = thresholds.strength_tolerance
    if reference == 0:
        return 1.0 if given == 0 else 0.0
    deviation_pct = abs(given - reference) / abs(reference) * 100
    if deviation_pct <= tol.full_credit_pct:
        return 1.0
    if deviation_pct >= tol.zero_credit_pct:
        return 0.0
    return (tol.zero_credit_pct - deviation_pct) / (tol.zero_credit_pct - tol.full_credit_pct)


def _ingredient_credit(target: FormulaIngredient, candidates: Sequence[Ingredient], thresholds: Thresholds) -> float:
    credits = [
        strength_credit(ing.strength, target.strength, thresholds)
        for ing in candidates
        if ing.strength is not None and ing.unit == target.unit
    ]
    return max(credits, default=0.0)


def strength_agreement(
    extraction: Extraction, formula: Formula, thresholds: Thresholds, aliases: Mapping[str, str]
) -> float:
    """Mean per-formula-ingredient strength credit; a missing ingredient, strength or unit mismatch scores 0."""
    if not formula.ingredients:
        return 0.0
    by_name: dict[str, list[Ingredient]] = {}
    for ing in extraction.ingredients:
        by_name.setdefault(_canonical(ing.name, aliases), []).append(ing)
    credits = [
        _ingredient_credit(target, by_name.get(_canonical(target.name, aliases), []), thresholds)
        for target in formula.ingredients
    ]
    return sum(credits) / len(credits)


def _field_match(extracted: str | None, reference: str | None) -> float:
    a, b = _norm_text(extracted), _norm_text(reference)
    return 1.0 if a is not None and a == b else 0.0


def component_scores(
    extraction: Extraction, formula: Formula, thresholds: Thresholds, aliases: Mapping[str, str]
) -> dict[str, float]:
    extracted_names = {_canonical(i.name, aliases) for i in extraction.ingredients}
    formula_names = {_canonical(i.name, aliases) for i in formula.ingredients}
    return {
        "ingredients": ingredient_similarity(extracted_names, formula_names),
        "strength": strength_agreement(extraction, formula, thresholds, aliases),
        "dosage_form": _field_match(extraction.dosage_form, formula.dosage_form),
        "base": _field_match(extraction.base, formula.base),
        "route": _field_match(extraction.route, formula.route),
    }


def score_formula(
    extraction: Extraction, formula: Formula, thresholds: Thresholds, aliases: Mapping[str, str]
) -> MatchCandidate:
    components = {
        k: round(v, _PRECISION) for k, v in component_scores(extraction, formula, thresholds, aliases).items()
    }
    total = sum(thresholds.weights[k] * components[k] for k in COMPONENTS)
    return MatchCandidate(
        formula_id=formula.formula_id,
        formula_version=formula.version,
        score=min(1.0, max(0.0, round(total, _PRECISION))),
        component_scores=components,
    )


# --- ranking -----------------------------------------------------------------------------------


def _m01(margin: float, thresholds: Thresholds) -> Flag:
    return Flag(
        rule_id="M-01",
        rule_version=MATCH_VERSION,
        severity=Severity.REVIEW,
        message=f"Ambiguous match: margin {margin:.2f} below T_margin {thresholds.T_margin:.2f}.",
        source_pass=2,
    )


def match(
    extraction: Extraction,
    formulas: Sequence[Formula],
    thresholds: Thresholds,
    aliases: Mapping[str, str],
    existing: Sequence[Flag] = (),
) -> MatchResult:
    """Score every formula; return the top 3, confidence, margin, status, and flags `[*existing, *new]`."""
    scored = [score_formula(extraction, f, thresholds, aliases) for f in formulas]
    ranked = sorted(scored, key=lambda c: (-c.score, c.formula_id))
    top = ranked[:TOP_K]
    confidence = top[0].score if top else 0.0
    second = top[1].score if len(top) > 1 else 0.0
    margin = round(confidence - second, _PRECISION)
    status = ProposalStatus.NO_MATCH if confidence < thresholds.T_match else ProposalStatus.PROPOSED
    new = [_m01(margin, thresholds)] if margin < thresholds.T_margin else []
    return MatchResult(candidates=top, confidence=confidence, margin=margin, status=status, flags=[*existing, *new])
