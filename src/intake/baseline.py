"""No-LLM baseline matcher (SPEC §6).

Score per formula = rapidfuzz token-set ratio (0-1) between the raw prescription text and the formula's
name plus its ingredient string ("<name> <strength><unit>" per ingredient). Top 3 are returned; the
result is NO_MATCH when the top score is below `NO_MATCH_CUTOFF`, read from `baseline_no_match_cutoff` in
eval/thresholds.yaml (protected). It was tuned on the dev split only with `tune_cutoff` (DECISIONS-LOG #14). The baseline adds no flags and never calls a model.
"""

from collections.abc import Sequence
from pathlib import Path

import yaml
from rapidfuzz import fuzz, utils

from intake.match import DEFAULT_THRESHOLDS, TOP_K, MatchResult
from intake.models import Formula, MatchCandidate, ProposalStatus

BASELINE_VERSION = "0.1.0"
NO_MATCH = "NO_MATCH"
_PRECISION = 6
_CUTOFF_GRID = [i / 100 for i in range(102)]  # 0.00 … 1.01 (1.01 rejects everything)


def load_no_match_cutoff(path: Path = DEFAULT_THRESHOLDS) -> float:
    """`baseline_no_match_cutoff` from eval/thresholds.yaml. Missing file: FileNotFoundError; malformed: ValueError."""
    data = yaml.safe_load(path.read_text())
    value = data.get("baseline_no_match_cutoff") if isinstance(data, dict) else None
    valid = isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value <= 1
    if not valid:
        raise ValueError(f"{path}: 'baseline_no_match_cutoff' must be a number from 0 to 1, got {value!r}.")
    return float(value)  # type: ignore[arg-type]


# Tuned on dev with tune_cutoff (S2.4); frozen at Gate 2. tests/test_baseline.py checks it is still dev-optimal.
NO_MATCH_CUTOFF: float = load_no_match_cutoff()


def formula_string(formula: Formula) -> str:
    """Formula name followed by each ingredient's name, strength and unit."""
    ingredients = " ".join(f"{i.name} {i.strength:g}{i.unit.value}" for i in formula.ingredients)
    return f"{formula.name} {ingredients}".strip()


def raw_text(text: str, notes: str | None = None) -> str:
    """The raw prescription text the baseline sees: text, then notes on a new line if present."""
    return f"{text}\n{notes}" if notes else text


def score(text: str, formula: Formula) -> float:
    ratio = fuzz.token_set_ratio(text, formula_string(formula), processor=utils.default_process)
    return round(ratio / 100, _PRECISION)


def _candidate(text: str, formula: Formula) -> MatchCandidate:
    s = score(text, formula)
    return MatchCandidate(
        formula_id=formula.formula_id, formula_version=formula.version, score=s, component_scores={"token_set": s}
    )


def baseline_match(text: str, formulas: Sequence[Formula], cutoff: float = NO_MATCH_CUTOFF) -> MatchResult:
    """Top 3 formulas by token-set ratio; NO_MATCH when the top score is below `cutoff`."""
    ranked = sorted((_candidate(text, f) for f in formulas), key=lambda c: (-c.score, c.formula_id))
    top = ranked[:TOP_K]
    confidence = top[0].score if top else 0.0
    second = top[1].score if len(top) > 1 else 0.0
    status = ProposalStatus.NO_MATCH if confidence < cutoff else ProposalStatus.PROPOSED
    margin = round(confidence - second, _PRECISION)
    return MatchResult(candidates=top, confidence=confidence, margin=margin, status=status)


def decision_correct(result: MatchResult, gold: str) -> bool:
    """Gold NO_MATCH needs status NO_MATCH; a gold formula needs PROPOSED with that formula ranked first."""
    if gold == NO_MATCH:
        return result.status == ProposalStatus.NO_MATCH
    return result.status == ProposalStatus.PROPOSED and bool(result.candidates) and result.candidates[0].formula_id == gold


def _correct_at(cut: float, top_score: float, top_id: str, gold: str) -> bool:
    if gold == NO_MATCH:
        return top_score < cut
    return top_score >= cut and top_id == gold


def tune_cutoff(cases: Sequence[tuple[float, str, str]]) -> float:
    """Cut-off maximising decision accuracy over (top score, top formula_id, gold) triples.

    Tried on a 0.01 grid from 0.00 to 1.01; among equally good cut-offs, the middle one (lower middle
    for an even count) is returned, so the choice sits away from the edges of the best plateau.
    Callers pass dev-split cases only.
    """
    if not cases:
        raise ValueError("tune_cutoff needs at least one case")
    accuracy = {cut: sum(_correct_at(cut, *case) for case in cases) for cut in _CUTOFF_GRID}
    best = max(accuracy.values())
    optimal = [cut for cut in _CUTOFF_GRID if accuracy[cut] == best]
    return optimal[(len(optimal) - 1) // 2]
