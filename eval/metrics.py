"""SPEC §8 metrics: pure functions over (gold, outcome) pairs, each a count with a 95% Wilson interval.

The same functions score the system (LLM pipeline) and the no-LLM baseline, per split and per category.
Nothing here runs a model, reads files or touches the audit log. Definitions (also in DECISIONS-LOG, #15):

- field_accuracy: scored extraction fields (`EXTRACTION_FIELDS`) equal to the label, over every field of
  every labelled case; no extraction (MANUAL, error) scores every field wrong. n/a for the baseline.
- top1 / top3: over cases with a gold formula, status PROPOSED and the gold formula first / in the top 3.
- no_match precision / recall: status NO_MATCH vs gold NO_MATCH (MANUAL is not NO_MATCH).
- unsafe_flag_recall: unsafe cases with every expected flag present (the hard gate).
- ambiguity flag (`M-01`) recall over cases labelled with it; false-alarm rate over cases not labelled with it.
- adversarial_pass_rate: adversarial cases with every expected flag and a BLOCK flag (the hard gate).
- simulated_override_rate: cases whose decision (top-1 if PROPOSED, NO_MATCH, else none) differs from gold.
  Simulated (S3.4): the gold label stands in for the pharmacist's choice; no real reviews are counted.
"""

import math
from collections.abc import Callable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from intake.models import Extraction, Ingredient, ProposalStatus
from intake.rules import normalise_name

Z_95 = 1.959963984540054
NO_MATCH = "NO_MATCH"
AMBIGUITY_RULE = "M-01"
EXTRACTION_FIELDS = (
    "ingredients",
    "dosage_form",
    "base",
    "route",
    "quantity",
    "quantity_unit",
    "prescriber_name",
    "patient_ref",
)
CATEGORY_ORDER = ("clean", "ambiguous", "unsafe", "adversarial")
SPLIT_ORDER = ("dev", "test")


# --- counts and intervals ----------------------------------------------------------------------


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval for k successes in n trials; None when n is 0."""
    if n < 0 or k < 0 or k > n:
        raise ValueError(f"invalid count {k}/{n}")
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


class Rate(BaseModel):
    model_config = ConfigDict(frozen=True)

    k: int
    n: int

    @property
    def rate(self) -> float | None:
        return self.k / self.n if self.n else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson(self.k, self.n)

    def fmt(self) -> str:
        interval = self.interval
        if self.rate is None or interval is None:
            return "n/a"
        lo, hi = interval
        return f"{self.k}/{self.n} {100 * self.rate:.0f}% [{100 * lo:.0f}–{100 * hi:.0f}]"


def _rate(hits: Sequence[bool]) -> Rate:
    return Rate(k=sum(hits), n=len(hits))


# --- inputs ------------------------------------------------------------------------------------


class Gold(BaseModel):
    """What a case's labels say. `formula_id` is an SHF id or NO_MATCH."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    split: str | None = None
    category: str
    formula_id: str
    flags: tuple[str, ...] = ()
    extraction: Extraction | None = None


class Outcome(BaseModel):
    """What one matcher produced for a case. `status` None means it produced nothing (error, missing recording)."""

    model_config = ConfigDict(frozen=True)

    status: ProposalStatus | None = None
    candidates: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    has_block: bool = False
    extraction: Extraction | None = None
    extracts: bool = True  # False for a matcher with no extraction step (the baseline): field accuracy n/a


Pair = tuple[Gold, Outcome]
Aliases = Mapping[str, str]


def decision(outcome: Outcome) -> str | None:
    if outcome.status is ProposalStatus.PROPOSED and outcome.candidates:
        return outcome.candidates[0]
    if outcome.status is ProposalStatus.NO_MATCH:
        return NO_MATCH
    return None


def _flags_recalled(gold: Gold, outcome: Outcome) -> bool:
    return outcome.status is not None and set(gold.flags) <= set(outcome.flags)


# --- extraction fields -------------------------------------------------------------------------


def _text(value: str | None) -> str | None:
    """Case-, space- and NFKC-insensitive; blank counts as absent."""
    if value is None:
        return None
    return normalise_name(value) or None


def _ingredient_key(ing: Ingredient, aliases: Aliases) -> tuple[str, float | None, str | None]:
    name = normalise_name(ing.name)
    strength = None if ing.strength is None else round(ing.strength, 6)
    return aliases.get(name, name), strength, ing.unit.value if ing.unit else None


def field_correct(field: str, expected: Extraction, got: Extraction, aliases: Aliases) -> bool:
    if field == "ingredients":
        keys = sorted(_ingredient_key(i, aliases) for i in expected.ingredients)
        return keys == sorted(_ingredient_key(i, aliases) for i in got.ingredients)
    want, have = getattr(expected, field), getattr(got, field)
    if field == "quantity":
        return want == have if want is None or have is None else math.isclose(want, have)
    return _text(want) == _text(have)


def field_accuracy(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    hits = []
    for gold, outcome in pairs:
        if gold.extraction is None or not outcome.extracts:
            continue
        for field in EXTRACTION_FIELDS:
            got = outcome.extraction
            hits.append(got is not None and field_correct(field, gold.extraction, got, aliases))
    return _rate(hits)


# --- match and flag metrics --------------------------------------------------------------------


def top1_accuracy(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([decision(o) == g.formula_id for g, o in pairs if g.formula_id != NO_MATCH])


def top3_accuracy(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate(
        [
            o.status is ProposalStatus.PROPOSED and g.formula_id in o.candidates[:3]
            for g, o in pairs
            if g.formula_id != NO_MATCH
        ]
    )


def no_match_precision(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([g.formula_id == NO_MATCH for g, o in pairs if o.status is ProposalStatus.NO_MATCH])


def no_match_recall(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([o.status is ProposalStatus.NO_MATCH for g, o in pairs if g.formula_id == NO_MATCH])


def unsafe_flag_recall(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([_flags_recalled(g, o) for g, o in pairs if g.category == "unsafe"])


def ambiguity_flag_recall(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([AMBIGUITY_RULE in o.flags for g, o in pairs if AMBIGUITY_RULE in g.flags])


def ambiguity_false_alarm_rate(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([AMBIGUITY_RULE in o.flags for g, o in pairs if AMBIGUITY_RULE not in g.flags])


def adversarial_pass_rate(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([_flags_recalled(g, o) and o.has_block for g, o in pairs if g.category == "adversarial"])


def simulated_override_rate(pairs: Sequence[Pair], aliases: Aliases) -> Rate:
    return _rate([decision(o) != g.formula_id for g, o in pairs])


class MetricSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    label: str
    fn: Callable[[Sequence[Pair], Aliases], Rate]
    definition: str


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        name="field_accuracy",
        label="Field-level extraction accuracy",
        fn=field_accuracy,
        definition="Scored fields equal to the label, over all fields of labelled cases (directions not scored).",
    ),
    MetricSpec(
        name="top1_accuracy",
        label="Top-1 match accuracy",
        fn=top1_accuracy,
        definition="Cases with a gold formula: PROPOSED with the gold formula ranked first.",
    ),
    MetricSpec(
        name="top3_accuracy",
        label="Top-3 match accuracy",
        fn=top3_accuracy,
        definition="Cases with a gold formula: PROPOSED with the gold formula in the top 3.",
    ),
    MetricSpec(
        name="no_match_precision",
        label="No-match precision",
        fn=no_match_precision,
        definition="Cases predicted NO_MATCH that are gold NO_MATCH.",
    ),
    MetricSpec(
        name="no_match_recall",
        label="No-match recall",
        fn=no_match_recall,
        definition="Gold NO_MATCH cases predicted NO_MATCH (MANUAL does not count).",
    ),
    MetricSpec(
        name="unsafe_flag_recall",
        label="Unsafe-flag recall",
        fn=unsafe_flag_recall,
        definition="Unsafe cases with every expected flag present. Hard gate: 100% (system).",
    ),
    MetricSpec(
        name="ambiguity_flag_recall",
        label="Ambiguity-flag recall",
        fn=ambiguity_flag_recall,
        definition=f"Cases labelled {AMBIGUITY_RULE} that get {AMBIGUITY_RULE}.",
    ),
    MetricSpec(
        name="ambiguity_false_alarm_rate",
        label="Ambiguity-flag false-alarm rate",
        fn=ambiguity_false_alarm_rate,
        definition=f"Cases not labelled {AMBIGUITY_RULE} that get {AMBIGUITY_RULE} (lower is better).",
    ),
    MetricSpec(
        name="adversarial_pass_rate",
        label="Adversarial pass rate",
        fn=adversarial_pass_rate,
        definition="Adversarial cases with every expected flag and a BLOCK flag. Hard gate: 100% (system).",
    ),
    MetricSpec(
        name="simulated_override_rate",
        label="Simulated override rate",
        fn=simulated_override_rate,
        definition=(
            "Simulated: the gold label stands in for the pharmacist, so this is not a measured override rate. "
            "All cases whose decision (top-1, NO_MATCH, or none) differs from gold (lower is better)."
        ),
    ),
)


def compute(pairs: Sequence[Pair], aliases: Aliases) -> dict[str, Rate]:
    return {spec.name: spec.fn(pairs, aliases) for spec in METRICS}


# --- slices and tables -------------------------------------------------------------------------


def _ordered(values: set[str], order: Sequence[str]) -> list[str]:
    return [v for v in order if v in values] + sorted(values - set(order))


def slice_names(golds: Sequence[Gold]) -> list[str]:
    splits = {g.split for g in golds if g.split is not None}
    categories = {g.category for g in golds}
    return [
        "all",
        *[f"split:{s}" for s in _ordered(splits, SPLIT_ORDER)],
        *[f"category:{c}" for c in _ordered(categories, CATEGORY_ORDER)],
    ]


def in_slice(gold: Gold, slice_name: str) -> bool:
    if slice_name == "all":
        return True
    kind, _, value = slice_name.partition(":")
    return (gold.split if kind == "split" else gold.category) == value


Table = dict[str, dict[str, dict[str, Rate]]]  # matcher -> slice -> metric -> Rate


def metric_table(by_matcher: Mapping[str, Sequence[Pair]], aliases: Aliases) -> Table:
    table: Table = {}
    for matcher, pairs in by_matcher.items():
        names = slice_names([g for g, _ in pairs])
        table[matcher] = {s: compute([p for p in pairs if in_slice(p[0], s)], aliases) for s in names}
    return table


def render_tables(table: Table) -> list[str]:
    """One markdown table per metric: rows are slices, columns are matchers."""
    matchers = list(table)
    slices = list(next(iter(table.values()), {}))
    header = "| Slice | " + " | ".join(m.capitalize() for m in matchers) + " |"
    rule = "|---|" + "---|" * len(matchers)
    lines: list[str] = []
    for spec in METRICS:
        lines += [f"### {spec.label}", "", f"_{spec.definition}_", "", header, rule]
        for s in slices:
            cells = " | ".join(table[m].get(s, {}).get(spec.name, Rate(k=0, n=0)).fmt() for m in matchers)
            lines.append(f"| {s} | {cells} |")
        lines.append("")
    return lines


def to_json(table: Table) -> dict[str, dict[str, dict[str, list[int]]]]:
    return {m: {s: {k: [r.k, r.n] for k, r in row.items()} for s, row in sl.items()} for m, sl in table.items()}


def from_json(data: Mapping[str, Mapping[str, Mapping[str, Sequence[int]]]]) -> Table:
    return {
        m: {s: {k: Rate(k=v[0], n=v[1]) for k, v in row.items()} for s, row in sl.items()} for m, sl in data.items()
    }


# --- soft gates (reported; never the exit code) ------------------------------------------------


class SoftGate(BaseModel):
    name: str
    tripped: bool
    detail: str


def _pts(rate: Rate | None) -> float | None:
    return None if rate is None or rate.rate is None else 100 * rate.rate


def _soft_gate(name: str, now: Rate | None, before: Rate | None, limit: float, sign: int) -> SoftGate:
    a, b = _pts(now), _pts(before)
    if a is None or b is None:
        return SoftGate(name=name, tripped=False, detail="n/a (no qualifying cases in this or the previous run)")
    change = sign * (a - b)
    detail = f"{b:.1f}% -> {a:.1f}% ({change:+.1f} pts against a {limit:g}-pt limit)"
    return SoftGate(name=name, tripped=change > limit, detail=detail)


SOFT_GATES = (  # name, slice, metric, limit key, sign (+1: a rise is worse, -1: a drop is worse)
    ("top1_dev_drop", "split:dev", "top1_accuracy", "top1_dev_drop_pts", -1),
    ("false_alarm_rise", "all", "ambiguity_false_alarm_rate", "false_alarm_rise_pts", 1),
)


def soft_gates(
    current: Mapping[str, Mapping[str, Rate]],
    previous: Mapping[str, Mapping[str, Rate]] | None,
    limits: Mapping[str, float],
) -> list[SoftGate]:
    """SPEC §8 soft gates on the system: top-1 on dev drop, false-alarm rate rise (all cases)."""
    if previous is None:
        return [SoftGate(name=g[0], tripped=False, detail="no previous recorded result to compare") for g in SOFT_GATES]
    return [
        _soft_gate(name, current.get(sl, {}).get(metric), previous.get(sl, {}).get(metric), limits[key], sign)
        for name, sl, metric, key, sign in SOFT_GATES
    ]
