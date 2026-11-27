"""S4.3 (#26): docs/HARNESS.md has a filled metrics row per milestone, each with a stated source, and a
written "What I'd change in the harness" section.

Values the orchestrator can't see (architect minutes, agent token spend) must say who supplies them rather
than carry an invented number.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HARNESS = REPO / "docs" / "HARNESS.md"
MILESTONES = ("M1", "M2", "M3", "M4")
COLUMNS = (
    "Milestone",
    "Issues closed",
    "Median fix rounds",
    "Escalations",
    "Reviewer catches",
    "Hard-gate fails on main",
    "Architect min",
    "Wall-clock",
    "Spend",
)


def _text() -> str:
    return HARNESS.read_text(encoding="utf-8")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table() -> dict[str, dict[str, str]]:
    lines = [line for line in _text().splitlines() if line.startswith("|")]
    header = _cells(lines[0])
    assert tuple(header) == COLUMNS
    rows = {}
    for line in lines[2:]:
        cells = _cells(line)
        if cells[0] in MILESTONES:
            assert len(cells) == len(COLUMNS), line
            rows[cells[0]] = dict(zip(COLUMNS, cells, strict=True))
    return rows


def _section(heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", _text(), re.DOTALL | re.MULTILINE)
    assert match, f"missing section: {heading}"
    return match.group(1).strip()


def test_every_milestone_row_is_filled() -> None:
    rows = _table()
    assert set(rows) == set(MILESTONES)
    for name, row in rows.items():
        for column, value in row.items():
            assert value, f"{name}: empty cell '{column}'"


def _source_line(label: str) -> str | None:
    match = re.search(rf"^- \*\*{re.escape(label)}\*\*.*$", _section("Sources"), re.MULTILINE)
    return match.group(0) if match else None


def test_architect_minutes_are_a_sourced_figure_or_a_named_pointer() -> None:
    """Before a gate the cell points at the architect; once logged, a figure needs a gate-log source line."""
    for name, row in _table().items():
        cell = row["Architect min"]
        if re.search(r"\d", re.sub(r"Gate \d", "", cell)):
            line = _source_line(f"{name} architect min")
            assert line and "gate" in line.lower(), f"{name}: architect minutes {cell!r} have no gate-log source"
        else:
            assert "architect" in cell.lower(), f"{name}: no figure and no named supplier: {cell!r}"


def test_agent_spend_is_a_sourced_figure_or_unknown_with_a_named_supplier() -> None:
    supplier = _source_line("Spend, agent tokens") or ""
    for name, row in _table().items():
        if "UNKNOWN" in row["Spend"]:
            assert "architect" in supplier.lower(), f"{name}: UNKNOWN spend but no named supplier in Sources"
        else:
            assert _source_line(f"{name} spend"), f"{name}: spend figure has no source line"


def test_only_the_last_milestone_may_be_in_progress_and_names_its_gate() -> None:
    rows = _table()
    open_rows = [name for name, row in rows.items() if "in progress" in " ".join(row.values())]
    assert open_rows in ([], [MILESTONES[-1]]), f"in-progress rows: {open_rows}"
    for name in open_rows:
        assert re.search(r"to Gate \d", rows[name]["Issues closed"]), f"{name}: in progress but no target gate"


def test_protected_proposals_match_the_intro() -> None:
    body = _section("What I'd change in the harness")
    span = re.search(r"those items \((\d+)–(\d+)\)", body)
    assert span, "intro must say which items touch protected paths"
    expected = set(range(int(span.group(1)), int(span.group(2)) + 1))
    items = re.findall(r"^(\d+)\. (.*)$", body, re.MULTILINE)
    marked = {int(n) for n, text in items if "(Protected: " in text}
    assert marked == expected, f"intro says {sorted(expected)}, marked {sorted(marked)}"


def test_every_row_has_a_source() -> None:
    sources = _section("Sources")
    for name in MILESTONES:
        assert re.search(rf"^- \*\*{name}\b", sources, re.MULTILINE), f"no source line for {name}"
    for column in COLUMNS[1:]:
        assert column in sources, f"no source for column '{column}'"


def test_what_id_change_section_is_written() -> None:
    body = _section("What I'd change in the harness")
    assert "filled in at M4" not in body
    assert len(re.findall(r"^\d+\. ", body, re.MULTILINE)) >= 3
