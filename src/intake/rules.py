"""Deterministic flag rules (SPEC §5). Versioned by RULES_VERSION.

Pass 1 runs on the raw prescription text; pass 2 runs on the extracted fields against the library.
Each pass takes the flags raised so far and returns a NEW list: the existing flags first, unchanged
and in order, followed by any new ones. No function here removes, edits or downgrades a flag
(invariant 2); `Flag` is frozen, so a flag cannot be changed after it is created. Each rule function
(`r1_xx_…`, `r2_xx_…`) sees only its input and returns only new flags.

S1.4: R1-01, R1-05, R2-01. S2.3: R1-02, R1-03, R1-04, R2-02 … R2-07. The ambiguity flag M-01 is
raised by the matcher (`match.py`), because it needs the scores.

Every table used here (controlled terms, form/route pairs, quantity ceilings) is illustrative demo data,
not clinical or legal reference material. Controlled terms and form/route pairs live in data/rules/;
quantity ceilings are `quantity_max` in eval/thresholds.yaml. All are loaded at import and fail loudly.
"""

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from intake.models import Extraction, Flag, Formula, Ingredient, Severity, Unit

RULES_VERSION = "0.2.0"

DEFAULT_INGREDIENT_MASTER = Path(__file__).resolve().parents[2] / "data" / "formulas" / "ingredient_master.yaml"

_FLOAT_TOL = 1e-9

# --- text normalisation ------------------------------------------------------------------------

# Latin look-alikes from Cyrillic and Greek, folded so "kеtamine" (Cyrillic е) reads as "ketamine".
_CONFUSABLE_PAIRS = (
    "аa еe оo рp сc уy хx іi јj ѕs ԁd ӏl кk мm нh тt вb "
    "АA ВB ЕE КK МM НH ОO РP СC ТT ХX УY ІI ЈJ ЅS "
    "αa οo ιi κk νv ρp υu ΑA ΒB ΕE ΖZ ΗH ΙI ΚK ΜM ΝN ΟO ΡP ΤT ΥY ΧX"
)
_CONFUSABLES = str.maketrans({pair[0]: pair[1] for pair in _CONFUSABLE_PAIRS.split()})


def _normalise_text(text: str) -> str:
    """NFKC (folds full-width and compatibility characters) and collapse whitespace."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalise_name(name: str) -> str:
    return _normalise_text(name).casefold()


def _harden(text: str) -> str:
    """Pass-1 view of text: NFKC, invisible format characters (zero-width etc.) dropped, look-alikes folded."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.translate(_CONFUSABLES).casefold()


def _pass1_text(text: str) -> str:
    return " ".join(_harden(text).split())


def _pass1_lines(text: str) -> list[str]:
    return [" ".join(line.split()) for line in _harden(text).splitlines()]


def _flag(rule_id: str, severity: Severity, message: str, source_pass: int) -> Flag:
    return Flag(
        rule_id=rule_id,
        rule_version=RULES_VERSION,
        severity=severity,
        message=message,
        source_pass=source_pass,
    )


def _append(existing: Sequence[Flag], new: Iterable[Flag]) -> list[Flag]:
    """Union of flags: every existing flag is kept as-is; new flags are only appended."""
    return [*existing, *new]


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


# --- ingredient master -------------------------------------------------------------------------


class IngredientLimit(BaseModel):
    """An illustrative (not clinical) strength ceiling for one ingredient, in one unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Unit
    illustrative_max: float


def _master_entries(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text())["ingredients"]


def load_ingredient_names(path: Path = DEFAULT_INGREDIENT_MASTER) -> frozenset[str]:
    """Normalised canonical names and aliases from the ingredient master."""
    names: set[str] = set()
    for entry in _master_entries(path):
        names.add(normalise_name(entry["name"]))
        names.update(normalise_name(alias) for alias in entry.get("aliases") or [])
    return frozenset(names)


def load_ingredient_limits(path: Path = DEFAULT_INGREDIENT_MASTER) -> dict[str, IngredientLimit]:
    """Normalised canonical name -> illustrative max from the ingredient master (entries without one are skipped)."""
    return {
        normalise_name(entry["name"]): IngredientLimit(unit=entry["unit"], illustrative_max=entry["illustrative_max"])
        for entry in _master_entries(path)
        if entry.get("unit") is not None and entry.get("illustrative_max") is not None
    }


@lru_cache(maxsize=1)
def _default_known() -> frozenset[str]:
    return load_ingredient_names()


# --- Pass 1 (raw text) -------------------------------------------------------------------------

# R1-01: the description is a pointer elsewhere rather than a compound.
_PLACEHOLDER_DESCRIPTION = re.compile(
    r"\bsee\s+(?:the\s+)?(?:notes?|attached|attachment|comments?|below)\b"
    r"|\b(?:as\s+)?per\s+(?:the\s+)?notes?\b"
    r"|\brefer\s+to\s+(?:the\s+)?(?:notes?|attached|attachment)\b",
    re.IGNORECASE,
)

# R1-02: a bare number (no unit after it) and the words around it.
_UNIT_AFTER = r"(?:%|percent|pct|mg/ml|mg/g|mcg/ml|mg|mcg|µg|μg|ug|g|gm|gms|grams?|kg|ml|mls|l|iu|units?|mmol|meq)"
_BARE_NUMBER = re.compile(rf"(?<![\w.\-/:#])\d+(?:\.\d+)?(?![\w%/:])(?!\.\d)(?!\s*{_UNIT_AFTER}(?![a-z]))")
_WORDS_BEFORE = re.compile(r"(?<![a-z'\-])([a-z][a-z'\-]*(?:\s+[a-z][a-z'\-]*){0,2})[\s:=\-]*$")
_WORDS_AFTER = re.compile(r"[\s:=\-]*([a-z][a-z'\-]*(?:\s+[a-z][a-z'\-]*){0,2})")
# Name endings and salt words typical of drug substances, so unknown ingredients still look ingredient-like.
_DRUG_SUFFIX = re.compile(
    r"(?:caine|idine|amine|azole|mycin|cillin|olone|sone|profen|statin|pril|sartan|oxacin|cycline|dipine"
    r"|zepam|zolam|codone|morphone|fenac|thromycin|acid|hcl|hydrochloride)$"
)

# R1-03: refers to a prior order the system cannot see.
_PRIOR_ORDER = re.compile(
    r"\bas\s+(?:before|previously|last\s+time)\b"
    r"|\bsame\s+(?:as\s+)?(?:before|last|previous|prior|usual|again)\b"
    r"|\b(?:like|per)\s+(?:the\s+)?(?:last|previous|prior)\b"
    r"|\brepeat\s+(?:the\s+)?(?:last|previous|prior)\b"
    r"|\b(?:previous|prior|last)\s+(?:order|rx|script|prescription|fill|batch)\b"
    r"|\busual\b",
    re.IGNORECASE,
)

# R1-04: SYNTHETIC controlled-substance list, kept in data/rules/controlled_terms.yaml (illustrative, not a
# legal schedule). Any hit routes the order to the controlled workflow (BLOCK).
DEFAULT_CONTROLLED_TERMS = Path(__file__).resolve().parents[2] / "data" / "rules" / "controlled_terms.yaml"


def load_controlled_terms(path: Path = DEFAULT_CONTROLLED_TERMS) -> tuple[str, ...]:
    """Terms from the R1-04 data file. Missing file raises FileNotFoundError; empty or malformed raises ValueError."""
    data = yaml.safe_load(path.read_text())
    terms = data.get("terms") if isinstance(data, dict) else None
    if not isinstance(terms, list) or not terms:
        raise ValueError(f"{path}: no 'terms' list; R1-04 cannot run without its controlled-substance list.")
    if not all(isinstance(t, str) and t.strip() for t in terms):
        raise ValueError(f"{path}: every controlled term must be a non-blank string.")
    return tuple(normalise_name(t) for t in terms)


CONTROLLED_TERMS: tuple[str, ...] = load_controlled_terms()
_SCHEDULE = re.compile(r"\bschedule\s+(?:ii|iii|iv|v|[2-5])\b|\bc-?(?:ii|iii|iv)\b")
# Terms this long are also looked for with spaces/punctuation removed ("k e t a m i n e").
_SQUASH_MIN_LEN = 7

# R1-05: instruction-like text aimed at the system.
_INSTRUCTION_LIKE = re.compile(
    r"\bignore\b"
    r"|\bdisregard\b"
    r"|\bapprove\b"
    r"|\bmark(?:ed)?\s+(?:as\s+)?verified\b"
    r"|\b(?:system|assistant)\s*:",
    re.IGNORECASE,
)


def r1_01_placeholder_description(text: str) -> list[Flag]:
    clean = _pass1_text(text)
    if not clean:
        return [_flag("R1-01", Severity.REVIEW, "Prescription text is empty.", 1)]
    match = _PLACEHOLDER_DESCRIPTION.search(clean)
    if match:
        return [_flag("R1-01", Severity.REVIEW, f"Description points elsewhere: '{match.group(0)}'.", 1)]
    return []


def _ingredient_like(words: Sequence[str], known: frozenset[str], *, from_end: bool) -> bool:
    phrases = [" ".join(words[-k:] if from_end else words[:k]) for k in range(1, len(words) + 1)]
    edge = words[-1] if from_end else words[0]
    return any(p in known for p in phrases) or bool(_DRUG_SUFFIX.search(edge))


def _bare_number_hits(line: str, known: frozenset[str]) -> list[str]:
    """'word number' / 'number word' for each bare number next to an ingredient-like word on this line."""
    hits = []
    for number in _BARE_NUMBER.finditer(line):
        before = _WORDS_BEFORE.search(line[: number.start()])
        after = _WORDS_AFTER.match(line[number.end() :])
        words_before = before.group(1).split() if before else []
        words_after = after.group(1).split() if after else []
        if words_before and _ingredient_like(words_before, known, from_end=True):
            hits.append(f"{words_before[-1]} {number.group(0)}")
        elif words_after and _ingredient_like(words_after, known, from_end=False):
            hits.append(f"{number.group(0)} {words_after[0]}")
    return hits


def r1_02_number_without_unit(text: str, known: frozenset[str]) -> list[Flag]:
    return [
        _flag("R1-02", Severity.REVIEW, f"Number with no unit next to an ingredient: '{hit}'.", 1)
        for line in _pass1_lines(text)
        for hit in _bare_number_hits(line, known)
    ]


def r1_03_prior_order_reference(text: str) -> list[Flag]:
    match = _PRIOR_ORDER.search(_pass1_text(text))
    if match:
        return [
            _flag("R1-03", Severity.REVIEW, f"Refers to a prior order the system cannot see: '{match.group(0)}'.", 1)
        ]
    return []


def _controlled_hits(text: str) -> list[str]:
    squashed = re.sub(r"[^a-z]", "", text)
    hits = []
    for term in CONTROLLED_TERMS:
        letters = re.sub(r"[^a-z]", "", term)
        worded = re.search(rf"\b{re.escape(term)}\b", text)
        if worded or (len(letters) >= _SQUASH_MIN_LEN and letters in squashed):
            hits.append(term)
    schedule = _SCHEDULE.search(text)
    if schedule:
        hits.append(schedule.group(0))
    return hits


def r1_04_controlled_substance(text: str) -> list[Flag]:
    hits = _controlled_hits(_pass1_text(text))
    if hits:
        terms = ", ".join(f"'{h}'" for h in hits)
        return [_flag("R1-04", Severity.BLOCK, f"Controlled-substance term(s) {terms}: controlled workflow.", 1)]
    return []


def r1_05_instruction_like_text(text: str) -> list[Flag]:
    match = _INSTRUCTION_LIKE.search(_pass1_text(text))
    if match:
        return [_flag("R1-05", Severity.BLOCK, f"Instruction-like text aimed at the system: '{match.group(0)}'.", 1)]
    return []


def run_pass1(text: str, existing: Sequence[Flag] = (), *, known: frozenset[str] | None = None) -> list[Flag]:
    """Every pass-1 rule on the raw text. `known` (ingredient names for R1-02) defaults to the ingredient master."""
    names = _default_known() if known is None else known
    new = [
        *r1_01_placeholder_description(text),
        *r1_02_number_without_unit(text, names),
        *r1_03_prior_order_reference(text),
        *r1_04_controlled_substance(text),
        *r1_05_instruction_like_text(text),
    ]
    return _append(existing, new)


# --- Pass 2 (extracted fields vs library) ------------------------------------------------------

# Strength units that can be compared: (dimension, factor to the dimension's base unit).
# % is taken as w/v, so 1% = 10 mg/mL (illustrative approximation).
_STRENGTH_SCALE: dict[Unit, tuple[str, float]] = {
    Unit.MCG: ("mass", 0.001),
    Unit.MG: ("mass", 1.0),
    Unit.G: ("mass", 1000.0),
    Unit.PERCENT: ("concentration", 10.0),
    Unit.MG_PER_ML: ("concentration", 1.0),
    Unit.UNITS: ("units", 1.0),
}

# R2-04: route words/phrases -> canonical route.
_ROUTE_WORDS: dict[str, str] = {
    "oral": "oral", "orally": "oral", "po": "oral", "by mouth": "oral", "per os": "oral",
    "topical": "topical", "topically": "topical", "cutaneous": "topical", "dermal": "topical",
    "external": "topical", "externally": "topical", "skin": "topical",
    "transdermal": "transdermal", "td": "transdermal",
    "rectal": "rectal", "rectally": "rectal", "pr": "rectal", "per rectum": "rectal",
    "vaginal": "vaginal", "vaginally": "vaginal", "intravaginal": "vaginal", "pv": "vaginal",
    "buccal": "buccal", "oromucosal": "buccal",
    "sublingual": "sublingual", "sl": "sublingual",
    "nasal": "nasal", "intranasal": "nasal",
    "ophthalmic": "ophthalmic", "otic": "otic",
    "intravenous": "parenteral", "iv": "parenteral", "intramuscular": "parenteral", "im": "parenteral",
    "subcutaneous": "parenteral", "subcut": "parenteral", "injection": "parenteral", "injectable": "parenteral",
}  # fmt: skip

# R2-04: dosage-form words (incl. common abbreviations) -> form.
_FORM_WORDS: dict[str, str] = {
    "cream": "cream", "creams": "cream",
    "ointment": "ointment", "oint": "ointment",
    "gel": "gel", "gels": "gel",
    "lotion": "lotion",
    "foam": "foam",
    "paste": "paste",
    "solution": "solution", "soln": "solution",
    "suspension": "suspension", "susp": "suspension",
    "syrup": "syrup", "elixir": "elixir",
    "capsule": "capsule", "capsules": "capsule", "caps": "capsule",
    "tablet": "tablet", "tablets": "tablet", "tabs": "tablet",
    "troche": "troche", "troches": "troche", "lozenge": "lozenge", "lozenges": "lozenge",
    "suppository": "suppository", "suppositories": "suppository", "supp": "suppository", "supps": "suppository",
    "spray": "spray", "powder": "powder", "shampoo": "shampoo",
}  # fmt: skip

# R2-04: routes each form can plausibly be given by (illustrative, non-sterile only), kept in
# data/rules/form_routes.yaml. Its keys must be exactly the forms above; its routes must be known routes.
DEFAULT_FORM_ROUTES = Path(__file__).resolve().parents[2] / "data" / "rules" / "form_routes.yaml"


def load_form_routes(path: Path = DEFAULT_FORM_ROUTES) -> dict[str, frozenset[str]]:
    """Form -> allowed routes from the R2-04 data file. Missing file: FileNotFoundError; malformed: ValueError."""
    data = yaml.safe_load(path.read_text())
    forms = data.get("forms") if isinstance(data, dict) else None
    if not isinstance(forms, dict) or not forms:
        raise ValueError(f"{path}: no 'forms' mapping; R2-04 cannot run without its form/route table.")
    expected, known_routes = set(_FORM_WORDS.values()), set(_ROUTE_WORDS.values())
    if set(forms) != expected:
        missing, unknown = sorted(expected - set(forms)), sorted(set(forms) - expected)
        raise ValueError(f"{path}: forms must match R2-04's form words (missing {missing}, unknown {unknown}).")
    table: dict[str, frozenset[str]] = {}
    for form, routes in forms.items():
        if not isinstance(routes, list) or not routes or not all(isinstance(r, str) for r in routes):
            raise ValueError(f"{path}: '{form}' must have a non-empty list of route names.")
        if not set(routes) <= known_routes:
            raise ValueError(f"{path}: '{form}' has unknown route(s) {sorted(set(routes) - known_routes)}.")
        table[form] = frozenset(routes)
    return table


FORM_ROUTES: dict[str, frozenset[str]] = load_form_routes()

# R2-05: quantity units -> (kind, factor to the kind's base unit). The illustrative ceiling per kind is
# `quantity_max` in eval/thresholds.yaml (protected).
_QUANTITY_UNITS: dict[str, tuple[str, float]] = {
    **{u: ("g", 1.0) for u in ("g", "gm", "gms", "gram", "grams")},
    "kg": ("g", 1000.0),
    **{u: ("ml", 1.0) for u in ("ml", "mls", "millilitre", "millilitres", "milliliter", "milliliters")},
    **{u: ("ml", 1000.0) for u in ("l", "litre", "litres", "liter", "liters")},
    **{
        u: ("count", 1.0)
        for u in (
            "capsule", "capsules", "caps", "tablet", "tablets", "tabs", "troche", "troches", "lozenge",
            "lozenges", "suppository", "suppositories", "supps", "each", "ea", "count", "ct",
        )
    },
}  # fmt: skip
DEFAULT_THRESHOLDS = Path(__file__).resolve().parents[2] / "eval" / "thresholds.yaml"


def load_quantity_max(path: Path = DEFAULT_THRESHOLDS) -> dict[str, float]:
    """R2-05 ceiling per quantity kind from `quantity_max`. Missing file: FileNotFoundError; malformed: ValueError."""
    data = yaml.safe_load(path.read_text())
    ceilings = data.get("quantity_max") if isinstance(data, dict) else None
    kinds = {kind for kind, _ in _QUANTITY_UNITS.values()}
    if not isinstance(ceilings, dict) or set(ceilings) != kinds:
        raise ValueError(f"{path}: 'quantity_max' must map exactly the kinds {sorted(kinds)} to a ceiling.")
    for kind, value in ceilings.items():
        valid = isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) and value > 0
        if not valid:
            raise ValueError(f"{path}: quantity_max.{kind} must be a positive finite number, got {value!r}.")
    return {kind: float(value) for kind, value in ceilings.items()}


QUANTITY_MAX: dict[str, float] = load_quantity_max()


def _canonical(name: str, aliases: Mapping[str, str]) -> str:
    key = normalise_name(name)
    return aliases.get(key, key)


def _in_base_unit(value: float, unit: Unit | None) -> tuple[str, float] | None:
    if unit is None:
        return None
    dimension, factor = _STRENGTH_SCALE[unit]
    return dimension, value * factor


def _strengths_with(ingredients: Iterable[Ingredient]) -> list[Ingredient]:
    return [ing for ing in ingredients if ing.strength is not None]


def r2_01_unknown_ingredient(extraction: Extraction, known: frozenset[str]) -> list[Flag]:
    return [
        _flag("R2-01", Severity.BLOCK, f"Ingredient not in the ingredient master: '{ing.name}'.", 2)
        for ing in extraction.ingredients
        if normalise_name(ing.name) not in known
    ]


def _all_limits(
    formulas: Sequence[Formula], aliases: Mapping[str, str], limits: Mapping[str, IngredientLimit]
) -> dict[str, list[IngredientLimit]]:
    """Master limits plus every formula's per-ingredient illustrative_max, by canonical name."""
    out: dict[str, list[IngredientLimit]] = {}
    for name, limit in limits.items():
        out.setdefault(_canonical(name, aliases), []).append(limit)
    for formula in formulas:
        for ing in formula.ingredients:
            limit = IngredientLimit(unit=ing.unit, illustrative_max=ing.illustrative_max)
            out.setdefault(_canonical(ing.name, aliases), []).append(limit)
    return out


def _strictest(given: tuple[str, float], limits: Sequence[IngredientLimit]) -> IngredientLimit | None:
    comparable = [lim for lim in limits if _STRENGTH_SCALE[lim.unit][0] == given[0]]
    return min(comparable, key=lambda lim: lim.illustrative_max * _STRENGTH_SCALE[lim.unit][1], default=None)


def r2_02_above_illustrative_max(
    extraction: Extraction,
    formulas: Sequence[Formula],
    aliases: Mapping[str, str],
    limits: Mapping[str, IngredientLimit],
) -> list[Flag]:
    by_name = _all_limits(formulas, aliases, limits)
    flags = []
    for ing in _strengths_with(extraction.ingredients):
        given = _in_base_unit(ing.strength, ing.unit)  # type: ignore[arg-type]
        cap = _strictest(given, by_name.get(_canonical(ing.name, aliases), [])) if given else None
        if given and cap and given[1] > cap.illustrative_max * _STRENGTH_SCALE[cap.unit][1] * (1 + _FLOAT_TOL):
            message = (
                f"Strength {ing.strength:g} {ing.unit.value} for '{ing.name}' is above its illustrative max "  # type: ignore[union-attr]
                f"{cap.illustrative_max:g} {cap.unit.value}."
            )
            flags.append(_flag("R2-02", Severity.BLOCK, message, 2))
    return flags


def _library_strengths(formulas: Sequence[Formula], aliases: Mapping[str, str]) -> dict[str, list[tuple[float, Unit]]]:
    out: dict[str, list[tuple[float, Unit]]] = {}
    for formula in formulas:
        for ing in formula.ingredients:
            out.setdefault(_canonical(ing.name, aliases), []).append((ing.strength, ing.unit))
    return out


def _unit_error(ing: Ingredient, refs: Sequence[tuple[float, Unit]]) -> str | None:
    """Why this strength looks like a unit error against the library strengths, or None."""
    given = _in_base_unit(ing.strength, ing.unit)  # type: ignore[arg-type]
    if given is None:
        return "has no unit"
    comparable = [v * _STRENGTH_SCALE[u][1] for v, u in refs if _STRENGTH_SCALE[u][0] == given[0] and v > 0]
    if not comparable:
        units = ", ".join(sorted({u.value for _, u in refs}))
        return f"is in {ing.unit.value}, not comparable with the library's {units}"  # type: ignore[union-attr]
    if given[1] <= 0:
        return "is zero or negative"
    nearest = min(comparable, key=lambda ref: abs(math.log(given[1] / ref)))
    ratio = given[1] / nearest
    if ratio >= 10 * (1 - _FLOAT_TOL) or ratio <= 0.1 * (1 + _FLOAT_TOL):
        return f"is {ratio:.3g}x the nearest library strength"
    return None


def r2_03_unit_error_suspicion(
    extraction: Extraction, formulas: Sequence[Formula], aliases: Mapping[str, str]
) -> list[Flag]:
    library = _library_strengths(formulas, aliases)
    flags = []
    for ing in _strengths_with(extraction.ingredients):
        refs = library.get(_canonical(ing.name, aliases))
        reason = _unit_error(ing, refs) if refs else None
        if reason:
            unit = ing.unit.value if ing.unit else ""
            message = f"Possible unit error: '{ing.name}' {ing.strength:g} {unit}".rstrip() + f" {reason}."
            flags.append(_flag("R2-03", Severity.BLOCK, message, 2))
    return flags


def _phrases_in(text: str, table: Mapping[str, str]) -> set[str]:
    padded = f" {re.sub(r'[^a-z]+', ' ', normalise_name(text))} "
    return {value for key, value in table.items() if f" {key} " in padded}


def r2_04_dosage_form_and_route(extraction: Extraction) -> list[Flag]:
    form = extraction.dosage_form
    if _blank(form):
        return [_flag("R2-04", Severity.REVIEW, "Dosage form is missing.", 2)]
    routes = _phrases_in(extraction.route or "", _ROUTE_WORDS)
    forms = _phrases_in(form, _FORM_WORDS)  # type: ignore[arg-type]
    implied = _phrases_in(form, _ROUTE_WORDS)  # type: ignore[arg-type]
    allowed = set().union(*(FORM_ROUTES[f] for f in forms)) if forms else set()
    conflict = bool(routes) and ((forms and not routes & allowed) or (implied and not routes & implied))
    if conflict:
        message = f"Dosage form '{form}' conflicts with route '{extraction.route}'."
        return [_flag("R2-04", Severity.REVIEW, message, 2)]
    return []


def _quantity_problem(quantity: float | None, unit: str | None) -> str | None:
    if quantity is None:
        return "Quantity is missing."
    if not math.isfinite(quantity) or quantity <= 0:
        return f"Quantity {quantity} is not a positive number."
    if _blank(unit):
        return f"Quantity {quantity:g} has no unit."
    known = _QUANTITY_UNITS.get(normalise_name(unit).rstrip("."))  # type: ignore[arg-type]
    if known is None:
        return f"Quantity unit '{unit}' is not recognised."
    kind, factor = known
    if quantity * factor > QUANTITY_MAX[kind] * (1 + _FLOAT_TOL):
        return f"Quantity {quantity:g} {unit} is implausibly large."
    return None


def r2_05_quantity(extraction: Extraction) -> list[Flag]:
    problem = _quantity_problem(extraction.quantity, extraction.quantity_unit)
    return [_flag("R2-05", Severity.REVIEW, problem, 2)] if problem else []


def r2_06_prescriber_or_patient_missing(extraction: Extraction) -> list[Flag]:
    flags = []
    if _blank(extraction.prescriber_name):
        flags.append(_flag("R2-06", Severity.REVIEW, "Prescriber name is missing.", 2))
    if _blank(extraction.patient_ref):
        flags.append(_flag("R2-06", Severity.REVIEW, "Patient reference is missing.", 2))
    return flags


def r2_07_duplicate_ingredient(extraction: Extraction, aliases: Mapping[str, str]) -> list[Flag]:
    seen: dict[str, list[str]] = {}
    for ing in extraction.ingredients:
        seen.setdefault(_canonical(ing.name, aliases), []).append(ing.name.strip())
    return [
        _flag("R2-07", Severity.REVIEW, f"Duplicate ingredient '{name}': {', '.join(repr(n) for n in given)}.", 2)
        for name, given in seen.items()
        if len(given) > 1
    ]


def run_pass2(
    extraction: Extraction,
    known: frozenset[str],
    existing: Sequence[Flag] = (),
    *,
    formulas: Sequence[Formula] = (),
    aliases: Mapping[str, str] | None = None,
    limits: Mapping[str, IngredientLimit] | None = None,
) -> list[Flag]:
    """Every pass-2 rule. `formulas`, `aliases` and `limits` (from the library) feed R2-02, R2-03 and R2-07."""
    aliases = aliases or {}
    limits = limits or {}
    new = [
        *r2_01_unknown_ingredient(extraction, known),
        *r2_02_above_illustrative_max(extraction, formulas, aliases, limits),
        *r2_03_unit_error_suspicion(extraction, formulas, aliases),
        *r2_04_dosage_form_and_route(extraction),
        *r2_05_quantity(extraction),
        *r2_06_prescriber_or_patient_missing(extraction),
        *r2_07_duplicate_ingredient(extraction, aliases),
    ]
    return _append(existing, new)
