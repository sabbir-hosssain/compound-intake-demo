"""Checks on the demo fixtures (data/demo/demo_cases.jsonl). No model is called.

1. Each record has the golden-case shape, matches its sample file and references a real formula.
2. Rules + match on the fixture's expected_extraction give exactly the fixture's formula, status and flags.
"""

import json
import re
from pathlib import Path

import pytest

from intake.match import match
from intake.models import Extraction, RawPrescription, Severity
from intake.pipeline import load_library
from intake.rules import run_pass1, run_pass2

ROOT = Path(__file__).resolve().parents[1]
DEMO_CASES = ROOT / "data" / "demo" / "demo_cases.jsonl"
FORMULA_IDS = {p.stem for p in (ROOT / "data" / "formulas").glob("SHF-*.yaml")}
REQUIRED_KEYS = {
    "illustrative",
    "case_id",
    "category",
    "sample_file",
    "raw",
    "expected_extraction",
    "expected_formula_id",
    "expected_status",
    "expected_flags",
    "expect_confirm_disabled",
    "rationale",
}


def _cases() -> list[dict]:
    lines = DEMO_CASES.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


CASES = _cases()
LIBRARY = load_library()


def _spec_block_rules() -> set[str]:
    """Rule IDs whose SPEC §5 severity is BLOCK."""
    sec5 = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8").split("## 5. Rules")[1].split("## 6.")[0]
    return set(re.findall(r"^\| (R[12]-\d\d) \|.*\| BLOCK[^|]*\|$", sec5, re.MULTILINE))


BLOCK_RULES = _spec_block_rules()


def test_spec_block_rules_parsed() -> None:
    assert BLOCK_RULES == {"R1-04", "R1-05", "R2-01", "R2-02", "R2-03"}


def test_three_fixtures_with_unique_ids() -> None:
    ids = [c["case_id"] for c in CASES]
    assert ids == ["demo_1_clean", "demo_2_unsafe", "demo_3_injection"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_fixture_shape(case: dict) -> None:
    assert REQUIRED_KEYS <= case.keys()
    assert case["illustrative"] is True
    raw = RawPrescription(**case["raw"])
    Extraction(**case["expected_extraction"])
    assert raw.id == case["case_id"]
    sample = (ROOT / case["sample_file"]).read_text(encoding="utf-8")
    assert raw.text == sample.rstrip("\n")
    assert case["expected_formula_id"] in FORMULA_IDS


def _run_rules_and_match(case: dict) -> tuple[str | None, str, list[str], bool]:
    """Pipeline steps after extraction (SPEC §3), with the fixture's extraction standing in for the model."""
    text = case["raw"]["text"]
    extraction = Extraction(**case["expected_extraction"])
    flags = run_pass1(text, known=LIBRARY.known_ingredients)
    flags = run_pass2(
        extraction,
        LIBRARY.known_ingredients,
        flags,
        formulas=LIBRARY.formulas,
        aliases=LIBRARY.aliases,
        limits=LIBRARY.ingredient_limits,
    )
    result = match(extraction, LIBRARY.formulas, LIBRARY.thresholds, LIBRARY.aliases, existing=flags)
    top = result.candidates[0].formula_id if result.candidates else None
    has_block = any(f.severity is Severity.BLOCK for f in result.flags)
    return top, result.status.value, sorted(f.rule_id for f in result.flags), has_block


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_expected_outcome_without_model(case: dict) -> None:
    top, status, flags, has_block = _run_rules_and_match(case)
    assert top == case["expected_formula_id"]
    assert status == case["expected_status"]
    assert flags == sorted(case["expected_flags"])
    assert has_block is case["expect_confirm_disabled"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_confirm_disabled_agrees_with_block_flags(case: dict) -> None:
    expects_block = bool(set(case["expected_flags"]) & BLOCK_RULES)
    assert case["expect_confirm_disabled"] is expects_block
