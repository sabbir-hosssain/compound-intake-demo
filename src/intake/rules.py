"""Deterministic flag rules (SPEC §5). Versioned by RULES_VERSION.

Pass 1 runs on the raw prescription text; pass 2 runs on the extracted fields against the library.
Each pass takes the flags raised so far and returns a NEW list: the existing flags first, unchanged
and in order, followed by any new ones. No function here removes, edits or downgrades a flag
(invariant 2); `Flag` is frozen, so a flag cannot be changed after it is created.

Implemented so far (S1.4): R1-01, R1-05, R2-01. The rest arrive in S2.3.
"""

import re
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path

import yaml

from intake.models import Extraction, Flag, Severity

RULES_VERSION = "0.1.0"

DEFAULT_INGREDIENT_MASTER = Path(__file__).resolve().parents[2] / "data" / "formulas" / "ingredient_master.yaml"

# R1-01: the description is a pointer elsewhere rather than a compound.
_PLACEHOLDER_DESCRIPTION = re.compile(
    r"\bsee\s+(?:the\s+)?(?:notes?|attached|attachment|comments?|below)\b"
    r"|\b(?:as\s+)?per\s+(?:the\s+)?notes?\b"
    r"|\brefer\s+to\s+(?:the\s+)?(?:notes?|attached|attachment)\b",
    re.IGNORECASE,
)

# R1-05: instruction-like text aimed at the system.
_INSTRUCTION_LIKE = re.compile(
    r"\bignore\b"
    r"|\bdisregard\b"
    r"|\bapprove\b"
    r"|\bmark(?:ed)?\s+(?:as\s+)?verified\b"
    r"|\b(?:system|assistant)\s*:",
    re.IGNORECASE,
)


def _normalise_text(text: str) -> str:
    """NFKC (folds full-width and compatibility characters) and collapse whitespace."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def normalise_name(name: str) -> str:
    return _normalise_text(name).casefold()


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


# --- Pass 1 (raw text) -------------------------------------------------------------------------


def r1_01_placeholder_description(text: str) -> list[Flag]:
    clean = _normalise_text(text)
    if not clean:
        return [_flag("R1-01", Severity.REVIEW, "Prescription text is empty.", 1)]
    match = _PLACEHOLDER_DESCRIPTION.search(clean)
    if match:
        return [_flag("R1-01", Severity.REVIEW, f"Description points elsewhere: '{match.group(0)}'.", 1)]
    return []


def r1_05_instruction_like_text(text: str) -> list[Flag]:
    match = _INSTRUCTION_LIKE.search(_normalise_text(text))
    if match:
        return [_flag("R1-05", Severity.BLOCK, f"Instruction-like text aimed at the system: '{match.group(0)}'.", 1)]
    return []


PASS1_RULES = (r1_01_placeholder_description, r1_05_instruction_like_text)


def run_pass1(text: str, existing: Sequence[Flag] = ()) -> list[Flag]:
    new = [flag for rule in PASS1_RULES for flag in rule(text)]
    return _append(existing, new)


# --- Pass 2 (extracted fields vs library) ------------------------------------------------------


def load_ingredient_names(path: Path = DEFAULT_INGREDIENT_MASTER) -> frozenset[str]:
    """Normalised canonical names and aliases from the ingredient master."""
    data = yaml.safe_load(path.read_text())
    names: set[str] = set()
    for entry in data["ingredients"]:
        names.add(normalise_name(entry["name"]))
        names.update(normalise_name(alias) for alias in entry.get("aliases") or [])
    return frozenset(names)


def r2_01_unknown_ingredient(extraction: Extraction, known: frozenset[str]) -> list[Flag]:
    return [
        _flag("R2-01", Severity.BLOCK, f"Ingredient not in the ingredient master: '{ing.name}'.", 2)
        for ing in extraction.ingredients
        if normalise_name(ing.name) not in known
    ]


def run_pass2(extraction: Extraction, known: frozenset[str], existing: Sequence[Flag] = ()) -> list[Flag]:
    new = r2_01_unknown_ingredient(extraction, known)
    return _append(existing, new)
