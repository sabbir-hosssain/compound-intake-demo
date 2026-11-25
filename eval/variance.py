"""Run-to-run variance (S2.7): how often repeated runs of the system disagree with each other on a case.

Runs are compared to each other, never to the labels. Over N >= 2 runs of the same cases, a case
*disagrees* on a measure when the runs do not all give the same value (also in DECISIONS-LOG, #17):

- decision: (status, top-1 formula if PROPOSED). A status change or a different first candidate counts;
  lower-ranked candidates do not. A run that produced nothing (error) has decision (none, none).
- flags: the set of flag rule IDs (order ignored). Severity and message are fixed by the rule ID.
- fields: per scored extraction field (`metrics.EXTRACTION_FIELDS`), compared with the same normalisation
  as field accuracy (`metrics.field_correct`). If some runs have an extraction and others don't, every
  field disagrees; if no run has one, every field agrees. Rate = disagreeing (case, field) pairs.
- any: the case disagrees on at least one of the above.

Each rate is a `metrics.Rate` (count with a 95% Wilson interval). This module also wraps the model client
to count calls and to retry transient API errors within a fixed, shared budget, so a LIVE run reports the
exact number of calls it made. Nothing here writes recordings or touches the audit log.
"""

import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from eval.metrics import EXTRACTION_FIELDS, Outcome, Rate, decision, field_correct
from intake.adapters.anthropic_client import Mode, ModelClient
from intake.extract import CompletionClient
from intake.models import Extraction, ProposalStatus

KINDS = ("decision", "flags", "fields")
TRANSIENT_STATUS = frozenset({408, 409, 429})  # plus every 5xx; mirrors the SDK's own retry rule


# --- disagreement --------------------------------------------------------------------------------


class Disagreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    category: str
    kinds: tuple[str, ...]
    decisions: tuple[str, ...]
    flag_sets: tuple[str, ...]
    fields: tuple[str, ...] = ()


class Variance(BaseModel):
    model_config = ConfigDict(frozen=True)

    runs: int
    cases: int
    decision: Rate
    decision_by_category: dict[str, Rate]
    flags: Rate
    fields: Rate
    by_field: dict[str, Rate]
    any: Rate
    disagreements: list[Disagreement]


def decision_text(outcome: Outcome) -> str:
    if outcome.status is None:
        return "none"
    if outcome.status is ProposalStatus.PROPOSED and outcome.candidates:
        return f"{outcome.status.value} {outcome.candidates[0]}"
    return outcome.status.value


def _decision_key(outcome: Outcome) -> tuple[str | None, str | None]:
    return (outcome.status.value if outcome.status else None, decision(outcome))


def _flag_text(outcome: Outcome) -> str:
    return ", ".join(sorted(set(outcome.flags))) or "-"


def _field_agrees(field: str, extractions: Sequence[Extraction | None], aliases: Mapping[str, str]) -> bool:
    present = [e for e in extractions if e is not None]
    if not present:
        return True
    if len(present) != len(extractions):
        return False
    first = present[0]
    return all(field_correct(field, first, other, aliases) for other in present[1:])


def _differs(values: Sequence[Any]) -> bool:
    return len(set(values)) > 1


def _rate(hits: Sequence[bool]) -> Rate:
    return Rate(k=sum(hits), n=len(hits))  # same as metrics._rate, kept local to avoid a private import


def compute(
    case_ids: Sequence[str],
    categories: Sequence[str],
    runs: Sequence[Sequence[Outcome]],
    aliases: Mapping[str, str],
) -> Variance:
    """Disagreement across runs. `runs[i][j]` is run i's outcome for case j."""
    if len(runs) < 2:
        raise ValueError("variance needs at least two runs")
    if any(len(run) != len(case_ids) for run in runs) or len(categories) != len(case_ids):
        raise ValueError("every run needs one outcome per case")
    per_case = [[run[j] for run in runs] for j in range(len(case_ids))]
    decision_hits = [_differs([_decision_key(o) for o in outs]) for outs in per_case]
    flag_hits = [_differs([frozenset(o.flags) for o in outs]) for outs in per_case]
    field_hits = {
        field: [not _field_agrees(field, [o.extraction for o in outs], aliases) for outs in per_case]
        for field in EXTRACTION_FIELDS
    }
    disagreements = []
    for j, outs in enumerate(per_case):
        fields = tuple(f for f in EXTRACTION_FIELDS if field_hits[f][j])
        kinds = tuple(k for k, hit in zip(KINDS, (decision_hits[j], flag_hits[j], bool(fields)), strict=True) if hit)
        if kinds:
            disagreements.append(
                Disagreement(
                    case_id=case_ids[j],
                    category=categories[j],
                    kinds=kinds,
                    decisions=tuple(decision_text(o) for o in outs),
                    flag_sets=tuple(_flag_text(o) for o in outs),
                    fields=fields,
                )
            )
    by_category = {
        cat: _rate([hit for hit, c in zip(decision_hits, categories, strict=True) if c == cat])
        for cat in dict.fromkeys(categories)
    }
    return Variance(
        runs=len(runs),
        cases=len(case_ids),
        decision=_rate(decision_hits),
        decision_by_category=by_category,
        flags=_rate(flag_hits),
        fields=_rate([hit for hits in field_hits.values() for hit in hits]),
        by_field={field: _rate(hits) for field, hits in field_hits.items()},
        any=Rate(k=len(disagreements), n=len(case_ids)),
        disagreements=disagreements,
    )


# --- call counting and bounded retries -----------------------------------------------------------


class CallCount(BaseModel):
    calls: int = 0
    retries: int = 0


class CallBudgetExceeded(RuntimeError):
    """The run hit its call limit; no further model call is made."""


def is_transient(error: BaseException) -> bool:
    """Connection errors, timeouts, 408/409/429 and 5xx (incl. 529 overloaded). Never a missing recording."""
    import anthropic

    if isinstance(error, anthropic.APIConnectionError):
        return True
    if isinstance(error, anthropic.APIStatusError):
        return error.status_code in TRANSIENT_STATUS or error.status_code >= 500
    return False


class CountingClient:
    """Wraps a CompletionClient: counts every call (retries included) and retries transient errors.

    `retry_budget` is shared by every call through this wrapper (all runs), so the total is bounded.
    """

    def __init__(
        self,
        inner: CompletionClient,
        *,
        retry_budget: int = 0,
        max_calls: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.inner = inner
        self.config = inner.config
        self.mode: Mode = getattr(inner, "mode", Mode.REPLAY)
        self.retry_budget = retry_budget
        self.max_calls = max_calls
        self.count = CallCount()
        self._sleep = sleep

    def complete(self, **kwargs: Any) -> dict[str, Any]:
        while True:
            if self.max_calls is not None and self.count.calls >= self.max_calls:
                raise CallBudgetExceeded(f"call limit {self.max_calls} reached")
            self.count.calls += 1
            try:
                return self.inner.complete(**kwargs)
            except Exception as error:
                if not is_transient(error) or self.count.retries >= self.retry_budget:
                    raise
                self.count.retries += 1
                self._sleep(min(30.0, 2.0**self.count.retries))


def live_model_client(cassette_dir: Path | None = None) -> ModelClient:
    """A LIVE ModelClient whose SDK client has `max_retries=0`, so every HTTP attempt is a counted call.

    LIVE never writes recordings (ModelClient only saves in RECORD). Pre-building `_live` is the one
    reach into the adapter; the request it sends is unchanged.
    """
    import anthropic

    client = ModelClient(mode=Mode.LIVE, cassette_dir=cassette_dir)
    client._live = anthropic.Anthropic(max_retries=0)
    return client


# --- results section -----------------------------------------------------------------------------


class RunSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    run: int
    top1: Rate
    failed_gates: tuple[str, ...]
    gates_total: int
    errors: int


def not_measured(mode: Mode) -> list[str]:
    return [
        "## Run-to-run variance",
        "",
        f"Not measured in this run (one {mode.value} run). Re-run with `--runs 3` (S2.7; LIVE: the manual",
        "`live-eval` workflow) to fill this section. REPLAY is deterministic, so it always shows 0%.",
        "",
    ]


def _definitions() -> list[str]:
    return [
        "Runs are compared with each other, not with the labels. A case disagrees when the runs do not all",
        "give the same value. Decision = (status, top-1 formula if PROPOSED); an error counts as its own value.",
        "Flag set = rule IDs, order ignored. Fields = each scored extraction field, normalised as in field",
        "accuracy; extraction present in some runs only = every field disagrees. Any = at least one of these.",
        "",
    ]


def _rate_rows(v: Variance) -> list[str]:
    rows = [
        "| Measure | Disagreeing / total | Unit |",
        "|---|---|---|",
        f"| Decision disagreement | {v.decision.fmt()} | cases |",
        f"| Flag-set disagreement | {v.flags.fmt()} | cases |",
        f"| Field disagreement | {v.fields.fmt()} | case × field |",
        f"| Any disagreement | {v.any.fmt()} | cases |",
    ]
    rows += [f"| Decision, category {c} | {r.fmt()} | cases |" for c, r in v.decision_by_category.items()]
    rows += [f"| Field `{f}` | {r.fmt()} | cases |" for f, r in v.by_field.items()]
    return [*rows, ""]


def _run_rows(summaries: Sequence[RunSummary]) -> list[str]:
    rows = ["| Run | Top-1 accuracy | Hard gates | Errors |", "|---|---|---|---|"]
    for s in summaries:
        gates = f"FAIL: {', '.join(s.failed_gates)}" if s.failed_gates else f"{s.gates_total}/{s.gates_total} pass"
        rows.append(f"| {s.run} | {s.top1.fmt()} | {gates} | {s.errors} |")
    return [*rows, ""]


def _disagreement_rows(v: Variance) -> list[str]:
    if not v.disagreements:
        return ["No case disagreed across runs.", ""]
    rows = [
        "| Case | Category | Differs in | Decision per run | Flags per run | Fields |",
        "|---|---|---|---|---|---|",
    ]
    for d in v.disagreements:
        rows.append(
            f"| {d.case_id} | {d.category} | {', '.join(d.kinds)} | {' / '.join(d.decisions)} "
            f"| {' / '.join(d.flag_sets)} | {', '.join(d.fields) or '-'} |"
        )
    return [*rows, ""]


def render(v: Variance, summaries: Sequence[RunSummary], *, calls: CallCount, mode: Mode) -> list[str]:
    return [
        f"## Run-to-run variance ({v.runs} {mode.value} runs)",
        "",
        f"- {v.cases} cases × {v.runs} runs; {calls.calls} model calls ({calls.retries} transient retries).",
        "- Metrics, hard gates and the case table above are from run 1; `--enforce-gates` needs every run to pass.",
        "",
        *_definitions(),
        *_rate_rows(v),
        "### Per run",
        "",
        *_run_rows(summaries),
        "### Cases that disagreed",
        "",
        *_disagreement_rows(v),
    ]
