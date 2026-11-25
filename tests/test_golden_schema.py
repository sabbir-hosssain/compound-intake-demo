"""Structural checks on the golden set (data/golden/*.jsonl). Does not run the pipeline."""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from intake.models import Extraction, RawPrescription

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data" / "golden"


def _cases() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(GOLDEN.glob("*.jsonl")):
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows


def _spec_rule_ids() -> set[str]:
    text = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    sec5 = text.split("## 5. Rules")[1].split("## 6.")[0]
    ids = set(re.findall(r"\| (R[12]-\d\d) \|", sec5))
    sec6 = text.split("## 6.")[1].split("## 7.")[0]
    return ids | set(re.findall(r"`(M-\d\d)", sec6))


CASES = _cases()


def test_counts() -> None:
    assert len(CASES) == 60
    assert Counter(c["split"] for c in CASES) == {"dev": 40, "test": 20}
    assert Counter(c["category"] for c in CASES) == {
        "clean": 25, "ambiguous": 15, "unsafe": 10, "adversarial": 10,
    }
    assert sum(c["expected_formula_id"] == "NO_MATCH" for c in CASES) == 8


def test_counts_script_agrees() -> None:
    out = subprocess.run(
        [sys.executable, str(GOLDEN / "counts.py")], capture_output=True, text=True, check=True
    ).stdout
    assert "total cases: 60" in out
    assert re.search(r"^ALL\s+60\s+40\s+20\s+8$", out, re.M)


def test_unique_ids() -> None:
    ids = [c["case_id"] for c in CASES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_case_valid(case: dict) -> None:
    assert case["illustrative"] is True
    RawPrescription(**case["raw"])
    Extraction(**case["expected_extraction"])
    formulas = {p.stem for p in (ROOT / "data" / "formulas").glob("SHF-*.yaml")}
    assert case["expected_formula_id"] in formulas | {"NO_MATCH"}
    assert set(case["expected_flags"]) <= _spec_rule_ids()
