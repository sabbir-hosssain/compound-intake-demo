"""Threshold tuning (S2.8): grid search over T_match and T_margin on the **dev split only**, in REPLAY.

    uv run python -m eval.tune [--out eval/thresholds.proposed.yaml]

Each dev case is run once through `intake.pipeline.build_proposal` from its REPLAY recording, with the
matching thresholds neutralised (T_match 0, T_margin 0: nothing is NO_MATCH and no M-01 is added), which
gives the recorded extraction plus the pass-1 and pass-2 flags. Every grid point then re-runs the real
`intake.match.match` on that extraction with `existing=` those flags, so flags are only appended
(invariant 2) and only T_match and T_margin vary: weights, strength tolerance, rules, prompts and labels
are untouched. tests/test_tune.py checks this equals `build_proposal` at sample points.

Objective, in order (see DECISIONS-LOG, issue #18):
  constraint  the three eval hard gates (adversarial pass, unsafe-flag recall, schema) all 100% on dev;
  1. most dev decisions that are correct and robust: a PROPOSED top-1 that ties the runner-up's score is
     decided by formula_id order, so it does not count;
  2. fewest wrong proposals (PROPOSED with a formula other than gold; NO_MATCH routes to manual handling);
  3. highest M-01 Youden J on dev (ambiguity-flag recall minus false-alarm rate).
Among the grid points with the best objective, pick the one deepest inside that set (the most grid steps
to a non-optimal point along each axis), then the one closest to the current values.

The proposal goes to `eval/thresholds.proposed.yaml`. This module never writes `eval/thresholds.yaml`
(protected; the architect applies the proposal at Gate 2), and never scores the test split.
"""

import argparse
import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from eval import metrics
from eval.metrics import AMBIGUITY_RULE, NO_MATCH, Rate
from eval.run_eval import GOLDEN_CASES, REPO_ROOT, CaseResult, EvalCase, hard_gates, load_cases, run_baseline, run_case
from intake.adapters.anthropic_client import Mode, ModelClient
from intake.extract import CompletionClient
from intake.match import DEFAULT_THRESHOLDS, match
from intake.models import ProposalStatus
from intake.pipeline import Library, load_library

DEV = "dev"
DEFAULT_OUT = REPO_ROOT / "eval" / "thresholds.proposed.yaml"
GRID_STEP = 0.01


def _grid(low: float, high: float) -> list[float]:
    steps = round((high - low) / GRID_STEP)
    return [round(low + k * GRID_STEP, 2) for k in range(steps + 1)]


T_MATCH_GRID = _grid(0.30, 0.90)
T_MARGIN_GRID = _grid(0.00, 0.30)

OBJECTIVE = [
    "constraint: adversarial_pass_rate, unsafe_flag_recall and schema_valid_or_manual all 100% on dev",
    (
        "1. maximise robust correct decisions on dev (decision == gold; a PROPOSED top-1 tied with the runner-up "
        "score does not count, since formula_id order decides it)"
    ),
    "2. minimise wrong proposals on dev (PROPOSED with a formula other than gold)",
    "3. maximise M-01 Youden J on dev (ambiguity-flag recall minus false-alarm rate)",
]
SELECTION = [
    "optimal set = feasible grid points with the best objective",
    (
        "pick the point deepest inside the optimal set: largest (min, sum) of grid steps to the nearest non-optimal "
        "point along each axis (the grid edge counts as non-optimal)"
    ),
    "then closest to the current values, then the lower values",
]


# --- preparing the dev cases (one REPLAY extraction each) --------------------------------------


class Prepared(BaseModel):
    """A dev case run once through the pipeline with neutral matching thresholds."""

    model_config = ConfigDict(frozen=True)

    case: EvalCase
    base: CaseResult


def dev_only(cases: Sequence[EvalCase]) -> list[EvalCase]:
    return [c for c in cases if c.split == DEV]


def library_at(library: Library, t_match: float, t_margin: float) -> Library:
    """The library with only T_match and T_margin replaced."""
    thresholds = library.thresholds.model_copy(update={"T_match": t_match, "T_margin": t_margin})
    return library.model_copy(update={"thresholds": thresholds})


def prepare(cases: Sequence[EvalCase], *, client: CompletionClient, library: Library) -> list[Prepared]:
    """Run each dev case once. A non-dev case or a missing REPLAY recording is an error (invariant 4)."""
    not_dev = [c.case_id for c in cases if c.split != DEV]
    if not_dev:
        raise ValueError(f"tuning uses the dev split only; got non-dev cases: {', '.join(not_dev)}")
    neutral = library_at(library, 0.0, 0.0)
    prepared = [Prepared(case=c, base=run_case(c, client=client, library=neutral)) for c in cases]
    missing = [p.case.case_id for p in prepared if p.base.missing_recording]
    if missing:
        raise ValueError(f"missing REPLAY recordings: {', '.join(missing)}")
    return prepared


def result_at(prep: Prepared, library: Library) -> CaseResult:
    """The case's result at the library's thresholds: the real matcher on the recorded extraction."""
    proposal = prep.base.proposal
    if proposal is None or proposal.status is ProposalStatus.MANUAL or proposal.extraction is None:
        return prep.base
    matched = match(proposal.extraction, library.formulas, library.thresholds, library.aliases, existing=proposal.flags)
    update = {
        "candidates": matched.candidates,
        "confidence": matched.confidence,
        "margin": matched.margin,
        "status": matched.status,
        "flags": matched.flags,
    }
    return CaseResult(case=prep.case, proposal=proposal.model_copy(update=update))


# --- scoring one grid point --------------------------------------------------------------------


def top_tied(result: CaseResult) -> bool:
    """PROPOSED, and the top two candidates have the same score."""
    p = result.proposal
    if p is None or p.status is not ProposalStatus.PROPOSED or len(p.candidates) < 2:
        return False
    return p.candidates[0].score == p.candidates[1].score


def _decision_ok(result: CaseResult) -> bool:
    return metrics.decision(result.outcome()) == result.case.gold_formula


def _wrong_proposal(result: CaseResult) -> bool:
    p = result.proposal
    return p is not None and p.status is ProposalStatus.PROPOSED and not _decision_ok(result)


class PointScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    i: int  # index into T_MATCH_GRID
    j: int  # index into T_MARGIN_GRID
    T_match: float
    T_margin: float
    gates_passed: bool
    robust_correct: int
    correct: int
    wrong_proposals: int
    m01_tp: int
    m01_pos: int
    m01_fp: int
    m01_neg: int
    j_stat: float

    @property
    def key(self) -> tuple[int, int, float]:
        return (self.robust_correct, -self.wrong_proposals, self.j_stat)


def _youden(tp: int, pos: int, fp: int, neg: int) -> float:
    recall = tp / pos if pos else 0.0
    false_alarm = fp / neg if neg else 0.0
    return round(recall - false_alarm, 9)


def score_point(prepared: Sequence[Prepared], library: Library, i: int, j: int) -> PointScore:
    results = [result_at(p, library) for p in prepared]
    labelled = [AMBIGUITY_RULE in r.case.expected_flags for r in results]
    fired = [AMBIGUITY_RULE in r.flag_ids for r in results]
    tp = sum(f for f, lab in zip(fired, labelled, strict=True) if lab)
    fp = sum(f for f, lab in zip(fired, labelled, strict=True) if not lab)
    pos, neg = sum(labelled), len(labelled) - sum(labelled)
    return PointScore(
        i=i,
        j=j,
        T_match=library.thresholds.T_match,
        T_margin=library.thresholds.T_margin,
        gates_passed=all(g.passed for g in hard_gates(results)),
        robust_correct=sum(_decision_ok(r) and not top_tied(r) for r in results),
        correct=sum(_decision_ok(r) for r in results),
        wrong_proposals=sum(_wrong_proposal(r) for r in results),
        m01_tp=tp,
        m01_pos=pos,
        m01_fp=fp,
        m01_neg=neg,
        j_stat=_youden(tp, pos, fp, neg),
    )


def grid_search(prepared: Sequence[Prepared], library: Library) -> list[PointScore]:
    return [
        score_point(prepared, library_at(library, tm, tg), i, j)
        for i, tm in enumerate(T_MATCH_GRID)
        for j, tg in enumerate(T_MARGIN_GRID)
    ]


# --- selection ---------------------------------------------------------------------------------


def _clearance(point: tuple[int, int], optimal: set[tuple[int, int]], axis: int, size: int) -> int:
    """Grid steps from `point` to the nearest non-optimal point (or off the grid) along one axis."""
    step = 1
    while True:
        for sign in (-1, 1):
            moved = list(point)
            moved[axis] += sign * step
            if not 0 <= moved[axis] < size or tuple(moved) not in optimal:
                return step
        step += 1


def optimal_set(scores: Sequence[PointScore]) -> list[PointScore]:
    feasible = [s for s in scores if s.gates_passed]
    if not feasible:
        raise ValueError("no grid point passes every hard gate on dev")
    best = max(s.key for s in feasible)
    return [s for s in feasible if s.key == best]


def select(scores: Sequence[PointScore], current: tuple[float, float]) -> PointScore:
    optimal = optimal_set(scores)
    cells = {(s.i, s.j) for s in optimal}

    def rank(s: PointScore) -> tuple[int, int, float, float, float]:
        a = _clearance((s.i, s.j), cells, 0, len(T_MATCH_GRID))
        b = _clearance((s.i, s.j), cells, 1, len(T_MARGIN_GRID))
        distance = math.hypot(s.T_match - current[0], s.T_margin - current[1])
        return (-min(a, b), -(a + b), round(distance, 9), s.T_match, s.T_margin)

    return min(optimal, key=rank)


def _plateau(chosen: PointScore, scores: Sequence[PointScore]) -> dict[str, list[float]]:
    """The contiguous run of optimal grid values through the chosen point, along each axis."""
    cells = {(s.i, s.j) for s in optimal_set(scores)}

    def run(axis: int, grid: list[float]) -> list[float]:
        idx = [chosen.i, chosen.j]
        lo = hi = idx[axis]
        while lo - 1 >= 0 and tuple(idx[:axis] + [lo - 1] + idx[axis + 1 :]) in cells:
            lo -= 1
        while hi + 1 < len(grid) and tuple(idx[:axis] + [hi + 1] + idx[axis + 1 :]) in cells:
            hi += 1
        return [grid[lo], grid[hi]]

    return {"T_match": run(0, T_MATCH_GRID), "T_margin": run(1, T_MARGIN_GRID)}


# --- report ------------------------------------------------------------------------------------


def _ratio(rate: Rate) -> str:
    return f"{rate.k}/{rate.n}"


REPORTED_CATEGORY_METRICS = ("top1_accuracy", "no_match_recall", "ambiguity_flag_recall", "ambiguity_false_alarm_rate")


def dev_metrics(prepared: Sequence[Prepared], library: Library) -> dict[str, Any]:
    """Every SPEC §8 metric on dev for system and baseline, a few per category, and the hard gates."""
    results = [result_at(p, library) for p in prepared]
    golds = [r.case.gold() for r in results]
    table = metrics.metric_table(
        {
            "system": list(zip(golds, [r.outcome() for r in results], strict=True)),
            "baseline": list(zip(golds, [run_baseline(p.case, library) for p in prepared], strict=True)),
        },
        library.aliases,
    )
    out: dict[str, Any] = {
        "hard_gates": {
            g.name: {"result": f"{g.passed_cases}/{g.total}", "passed": g.passed} for g in hard_gates(results)
        }
    }
    for matcher, slices in table.items():
        out[matcher] = {name: _ratio(rate) for name, rate in slices["split:dev"].items()}
        out[f"{matcher}_by_category"] = {
            s.split(":", 1)[1]: {m: _ratio(slices[s][m]) for m in REPORTED_CATEGORY_METRICS}
            for s in slices
            if s.startswith("category:")
        }
    return out


def _runs(
    scores: Sequence[PointScore], value: Callable[[PointScore], float], fields: Callable[[PointScore], dict]
) -> list:
    """Collapse consecutive grid values with identical fields into ranges."""
    rows: list[dict[str, Any]] = []
    for s in scores:
        f = fields(s)
        if rows and rows[-1]["_f"] == f:
            rows[-1]["range"][1] = value(s)
        else:
            rows.append({"range": [value(s), value(s)], "_f": f})
    return [{"range": r["range"], **r["_f"]} for r in rows]


def landscape(scores: Sequence[PointScore], chosen: PointScore) -> dict[str, Any]:
    """1-D slices through the chosen point: how each threshold trades off on dev."""
    along_match = [s for s in scores if s.j == chosen.j]
    along_margin = [s for s in scores if s.i == chosen.i]
    return {
        f"T_match (T_margin fixed at {chosen.T_margin:.2f})": _runs(
            along_match,
            lambda s: s.T_match,
            lambda s: {
                "robust_correct": s.robust_correct,
                "correct": s.correct,
                "wrong_proposals": s.wrong_proposals,
                "gates_passed": s.gates_passed,
            },
        ),
        f"T_margin (T_match fixed at {chosen.T_match:.2f})": _runs(
            along_margin,
            lambda s: s.T_margin,
            lambda s: {
                "m01_recall": f"{s.m01_tp}/{s.m01_pos}",
                "m01_false_alarms": f"{s.m01_fp}/{s.m01_neg}",
                "youden_j": s.j_stat,
                "gates_passed": s.gates_passed,
            },
        ),
    }


def _why_wrong(result: CaseResult) -> str:
    p = result.proposal
    if p is None:
        return "no proposal (error)"
    if p.status is ProposalStatus.MANUAL:
        return "MANUAL (extraction failed)"
    gold = result.case.gold_formula
    top = p.candidates[0] if p.candidates else None
    if p.status is ProposalStatus.NO_MATCH:
        return f"NO_MATCH: top score {p.confidence:.3f} < T_match"
    if gold == NO_MATCH:
        return f"PROPOSED {top.formula_id if top else '-'}: top score {p.confidence:.3f} >= T_match, gold NO_MATCH"
    ranked = [c.formula_id for c in p.candidates]
    where = f"gold ranked {ranked.index(gold) + 1}" if gold in ranked else "gold not in top 3"
    return f"PROPOSED {top.formula_id if top else '-'} (score {p.confidence:.3f}, margin {p.margin:.3f}); {where}"


def diagnostics(prepared: Sequence[Prepared], library: Library) -> dict[str, Any]:
    """The dev cases still wrong at the proposed point, and its M-01 false alarms: what thresholds can't fix."""
    results = [result_at(p, library) for p in prepared]
    return {
        "decisions_wrong_or_tie_decided": [
            {
                "case": r.case.case_id,
                "category": r.case.category,
                "gold": r.case.gold_formula,
                "why": "correct only by formula_id order (top-1 score tie)" if _decision_ok(r) else _why_wrong(r),
            }
            for r in results
            if not _decision_ok(r) or top_tied(r)
        ],
        "m01_false_alarms": [
            {
                "case": r.case.case_id,
                "category": r.case.category,
                "status": r.proposal.status.value,
                "margin": round(r.proposal.margin, 3),
            }
            for r in results
            if r.proposal is not None and AMBIGUITY_RULE in r.flag_ids and AMBIGUITY_RULE not in r.case.expected_flags
        ],
    }


def build_document(prepared: Sequence[Prepared], library: Library) -> dict[str, Any]:
    current = (library.thresholds.T_match, library.thresholds.T_margin)
    scores = grid_search(prepared, library)
    chosen = select(scores, current)
    return {
        "current": {"T_match": current[0], "T_margin": current[1]},
        "proposed": {"T_match": chosen.T_match, "T_margin": chosen.T_margin},
        "cases": {"split": DEV, "count": len(prepared), "ids": [p.case.case_id for p in prepared]},
        "grid": {
            "T_match": [T_MATCH_GRID[0], T_MATCH_GRID[-1]],
            "T_margin": [T_MARGIN_GRID[0], T_MARGIN_GRID[-1]],
            "step": GRID_STEP,
            "points": len(scores),
            "feasible_points": sum(s.gates_passed for s in scores),
        },
        "objective": OBJECTIVE,
        "selection": SELECTION,
        "optimum": {
            "robust_correct": f"{chosen.robust_correct}/{len(prepared)}",
            "wrong_proposals": chosen.wrong_proposals,
            "m01_youden_j": chosen.j_stat,
            "optimal_points": len(optimal_set(scores)),
            "plateau_through_proposed": _plateau(chosen, scores),
        },
        "dev_metrics": {
            "current": dev_metrics(prepared, library_at(library, *current)),
            "proposed": dev_metrics(prepared, library_at(library, chosen.T_match, chosen.T_margin)),
        },
        "landscape": landscape(scores, chosen),
        "diagnostics_at_proposed": diagnostics(prepared, library_at(library, chosen.T_match, chosen.T_margin)),
    }


HEADER = (
    "# Generated by `python -m eval.tune` (S2.8, issue #18). Do not edit by hand; re-run the tuner instead.\n"
    "# PROPOSAL ONLY: eval/thresholds.yaml is unchanged. The architect applies these values at Gate 2.\n"
    "# Dev split only, REPLAY recordings, only T_match and T_margin varied. No test-split metric is computed.\n"
    "# Ratios are hits/cases. Synthetic, illustrative data.\n"
)


def write_proposal(document: dict[str, Any], path: Path = DEFAULT_OUT) -> Path:
    """Write the proposal YAML. Refuses to touch the protected thresholds file."""
    if Path(path).resolve() == DEFAULT_THRESHOLDS.resolve() or Path(path).name == DEFAULT_THRESHOLDS.name:
        raise ValueError("refusing to write eval/thresholds.yaml: it is protected; the architect applies at Gate 2")
    body = yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=120)
    Path(path).write_text(HEADER + body, encoding="utf-8")
    return Path(path)


# --- command line ------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m eval.tune", description="Tune T_match/T_margin on dev (REPLAY).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Proposal file (never eval/thresholds.yaml).")
    return parser


def main(argv: Sequence[str] | None = None, *, client: CompletionClient | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.out.resolve() == DEFAULT_THRESHOLDS.resolve() or args.out.name == DEFAULT_THRESHOLDS.name:
        print("error: refusing to write eval/thresholds.yaml (protected; applied by the architect)", file=sys.stderr)
        return 1
    library = load_library()
    try:
        cases = dev_only(load_cases(GOLDEN_CASES))
        prepared = prepare(cases, client=client or ModelClient(mode=Mode.REPLAY), library=library)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    document = build_document(prepared, library)
    path = write_proposal(document, args.out)
    print(f"current  T_match {document['current']['T_match']:.2f}  T_margin {document['current']['T_margin']:.2f}")
    print(f"proposed T_match {document['proposed']['T_match']:.2f}  T_margin {document['proposed']['T_margin']:.2f}")
    print(f"proposal: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
