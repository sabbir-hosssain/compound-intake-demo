"""S4.1 (#24): the README has the planned structure, cites the committed results exactly, and passes the
honesty checklist (credit line, synthetic data, non-pharmacist labels, simulated override, no clinical or
production claims).

These tests read README.md, docs/SPEC.md and the committed results file only; they make no model call.
"""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `eval/` is a top-level package next to `src/`
    sys.path.insert(0, str(REPO))

from eval import run_eval

README = REPO / "README.md"
SPEC = REPO / "docs" / "SPEC.md"

SECTIONS = (
    "The problem",
    "The principle",
    "How it works",
    "What the AI does, and what it never does",
    "Results",
    "Design decisions",
    "Limitations",
    "Run it",
    "How it was built",
)
CREDIT = "Prototyped by Sabbir Hossain with AI coding assistants (Claude) under an architect-defined harness."
ADRS = (
    "docs/adr/0001-ai-proposes-pharmacist-confirms.md",
    "docs/adr/0002-deterministic-rules-own-safety-flags.md",
    "docs/adr/0003-matching-in-code-not-llm.md",
)
# Every metric table in the results file, by its "### " heading.
METRICS = (
    "Field-level extraction accuracy",
    "Top-1 match accuracy",
    "Top-3 match accuracy",
    "No-match precision",
    "No-match recall",
    "Unsafe-flag recall",
    "Ambiguity-flag recall",
    "Ambiguity-flag false-alarm rate",
    "Adversarial pass rate",
    "Simulated override rate",
)
FORBIDDEN_CLAIMS = (
    "production-ready",
    "production ready",
    "production-grade",
    "clinically validated",
    "clinically proven",
    "fda",
    "hipaa",
    "safe for patients",
    "ready for clinical",
    "in production",
    "deployed at",
    "real prescriptions",
    "real patients",
)


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def _section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, f"section '{title}' not found"
    return match.group(1)


def _spec_limitations() -> str:
    lines = SPEC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## 11. Limitations"))
    body = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.strip():
            body.append(line.strip())
    assert body, "SPEC §11 is empty"
    return " ".join(body)


def _results_file(readme_text: str) -> Path:
    links = set(re.findall(r"\]\((results/\d{4}-\d{2}-\d{2}\.md)\)", readme_text))
    assert len(links) == 1, f"README must link exactly one results file, found {sorted(links)}"
    return REPO / links.pop()


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _results_row(results: str, heading: str, slice_name: str) -> list[str]:
    section = re.search(rf"^### {re.escape(heading)}\n(.*?)(?=^#|\Z)", results, re.DOTALL | re.MULTILINE)
    assert section, f"results file has no '### {heading}' table"
    rows = [line for line in section.group(1).splitlines() if line.startswith(f"| {slice_name} |")]
    assert len(rows) == 1, f"expected one '{slice_name}' row under '{heading}'"
    return _cells(rows[0])[1:]


def _readme_row(readme_text: str, metric: str) -> list[str]:
    results = _section(readme_text, "Results")
    rows = [line for line in results.splitlines() if line.startswith(f"| {metric} |")]
    assert len(rows) == 1, f"README results table needs exactly one '{metric}' row"
    return _cells(rows[0])[1:]


# --- structure -------------------------------------------------------------------------------------


def test_sections_appear_in_the_planned_order(readme: str) -> None:
    headings = _headings(readme)
    positions = []
    for title in SECTIONS:
        found = [i for i, heading in enumerate(headings) if heading.startswith(title)]
        assert len(found) == 1, f"expected exactly one '## {title}' section"
        positions.append(found[0])
    assert positions == sorted(positions), f"sections out of order: {headings}"


def test_every_section_has_content(readme: str) -> None:
    for title in SECTIONS:
        assert len(_section(readme, title).strip()) > 80, f"section '{title}' is empty or a stub"


def test_flow_is_a_mermaid_diagram(readme: str) -> None:
    flow = _section(readme, "How it works")
    assert "```mermaid" in flow
    for stage in ("Rules pass 1", "extract", "Rules pass 2", "Matcher", "explain", "Pharmacist", "Audit"):
        assert stage.lower() in flow.lower(), f"flow diagram is missing '{stage}'"


def test_ai_section_says_what_the_model_never_does(readme: str) -> None:
    section = _section(readme, "What the AI does, and what it never does").lower()
    for phrase in ("never", "flag", "confirm", "audit", "match"):
        assert phrase in section


def test_design_decisions_link_every_adr(readme: str) -> None:
    section = _section(readme, "Design decisions")
    for adr in ADRS:
        assert f"]({adr})" in section, f"README does not link {adr}"


def test_relative_links_resolve(readme: str) -> None:
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", readme):
        if re.match(r"[a-z]+:", target):
            continue
        assert (REPO / target).exists(), f"broken link in README: {target}"


# --- results ---------------------------------------------------------------------------------------


def test_results_link_the_newest_live_results_file(readme: str) -> None:
    """The README cites the final golden-set LIVE/RECORD results (the file tests/test_final_results.py checks),
    not a local REPLAY run someone left in results/."""
    linked = _results_file(readme)
    assert linked.exists()
    live = []
    for path in (REPO / "results").glob("*.md"):
        data = run_eval.read_metrics_comment(path.read_text(encoding="utf-8"))
        if data and data.get("cases") == "data/golden/golden_cases.jsonl" and data.get("mode") in ("LIVE", "RECORD"):
            live.append((str(data["date"]), path))
    assert live, "no LIVE/RECORD golden-set results file under results/"
    newest = max(live)[1]
    assert linked == newest, f"README cites {linked.name}; the newest LIVE results file is {newest.name}"
    assert f"Mode: {run_eval.read_metrics_comment(linked.read_text(encoding='utf-8'))['mode']}" in readme


@pytest.mark.parametrize("metric", METRICS)
def test_results_table_matches_the_test_split_in_the_results_file(readme: str, metric: str) -> None:
    results = _results_file(readme).read_text(encoding="utf-8")
    assert _readme_row(readme, metric) == _results_row(results, metric, "split:test")


def test_results_table_is_labelled_test_split_with_intervals_and_baseline(readme: str) -> None:
    section = _section(readme, "Results")
    assert "| Metric (test split) | System | No-LLM baseline |" in section
    assert "95%" in section and "Wilson" in section


def test_hard_gates_quoted_from_the_results_file(readme: str) -> None:
    results = _results_file(readme).read_text(encoding="utf-8")
    section = _section(readme, "Results")
    for gate in ("adversarial_pass_rate", "unsafe_flag_recall", "schema_valid_or_manual"):
        row = [line for line in results.splitlines() if line.startswith(f"| {gate} |")]
        assert len(row) == 1
        hits = _cells(row[0])[1].split(" ")[0]  # e.g. "10/10"
        assert _cells(row[0])[3] == "PASS"
        assert hits in section, f"README does not quote {gate} {hits}"


# --- honesty checklist (START_HERE §6) -------------------------------------------------------------


def test_credit_line_near_the_top(readme: str) -> None:
    assert CREDIT in readme
    assert readme.index(CREDIT) < readme.index("## The problem")


def test_synthetic_data_banner_near_the_top(readme: str) -> None:
    banner = "Synthetic data. Fictional, illustrative formulas and limits. Not for clinical use."
    assert banner in readme
    assert readme.index(banner) < readme.index("## The problem")


def test_limitations_quote_spec_section_11_verbatim(readme: str) -> None:
    assert _spec_limitations() in _section(readme, "Limitations")


def test_labels_are_described_as_written_by_a_non_pharmacist(readme: str) -> None:
    assert "non-pharmacist" in _section(readme, "Results")
    assert "non-pharmacist" in _section(readme, "Limitations")


def test_override_rate_is_always_called_simulated(readme: str) -> None:
    for line in readme.splitlines():
        if "override" in line.lower():
            assert "simulated" in line.lower(), f"override mentioned without 'simulated': {line}"


def test_no_clinical_or_production_claims(readme: str) -> None:
    lowered = readme.lower()
    for phrase in FORBIDDEN_CLAIMS:
        assert phrase not in lowered, f"README makes a claim it must not: '{phrase}'"
    assert "not clinical software" in lowered


def test_only_placeholder_organisation_names(readme: str) -> None:
    assert "SH Compounding Network" in readme
    for name in re.findall(r'"([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+)*)"', readme):
        assert name in {"SH Compounding Network", "TeleHealthSH"}, f"unexpected quoted name: {name}"


def test_run_instructions_need_no_api_key(readme: str) -> None:
    section = _section(readme, "Run it")
    for command in ("make demo", "uv run pytest -q", "--mode replay", "intake run samples/", "intake audit verify"):
        assert command in section, f"run instructions are missing '{command}'"
    assert "--results-dir" in section, "the replay eval example must not overwrite the committed results file"
