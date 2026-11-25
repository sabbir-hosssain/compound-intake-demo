"""Print golden-set category counts (stdlib only). Usage: python data/golden/counts.py"""

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATEGORIES = ("clean", "ambiguous", "unsafe", "adversarial")
SPLITS = ("dev", "test")


def load() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(HERE.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))
    return cases


def main() -> int:
    cases = load()
    ids = [c["case_id"] for c in cases]
    if len(ids) != len(set(ids)):
        print("ERROR: duplicate case_id")
        return 1
    print(f"total cases: {len(cases)}")
    print(f"{'category':<12}{'total':>6}{'dev':>6}{'test':>6}{'no_match':>10}")
    for cat in CATEGORIES:
        rows = [c for c in cases if c["category"] == cat]
        by_split = Counter(c["split"] for c in rows)
        nm = sum(1 for c in rows if c["expected_formula_id"] == "NO_MATCH")
        print(f"{cat:<12}{len(rows):>6}{by_split['dev']:>6}{by_split['test']:>6}{nm:>10}")
    by_split = Counter(c["split"] for c in cases)
    nm_total = sum(1 for c in cases if c["expected_formula_id"] == "NO_MATCH")
    print(f"{'ALL':<12}{len(cases):>6}{by_split['dev']:>6}{by_split['test']:>6}{nm_total:>10}")
    other = {c["category"] for c in cases} - set(CATEGORIES)
    if other:
        print(f"ERROR: unknown categories {sorted(other)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
