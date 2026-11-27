"""Replay traces for the static viewer (intake.trace, viewer/).

The drift test regenerates every trace in REPLAY and compares it byte for byte with the
committed copy in viewer/traces, so the viewer can't show a pipeline that no longer exists.
Fix a failure by running `make traces` and committing the result, never by editing the JSON.
"""

import ast
import json
import os
from pathlib import Path

import pytest

from intake import trace
from intake.adapters.anthropic_client import REPO_ROOT, ModelClient
from intake.cli import main

VIEWER = REPO_ROOT / "viewer"
CREDIT = "Prototyped by Sabbir Hossain with AI coding assistants (Claude) under an architect-defined harness."


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    os.environ["INTAKE_MODE"] = "replay"
    return trace.render_all(client=ModelClient())


@pytest.fixture(scope="module")
def traces(rendered: dict[str, str]) -> dict[str, dict]:
    return {name: json.loads(text) for name, text in rendered.items() if name != "index.json"}


def test_committed_traces_match_the_pipeline(rendered: dict[str, str]) -> None:
    committed = {p.name for p in (VIEWER / "traces").glob("*.json")}
    assert committed == set(rendered), "viewer/traces is out of date: run `make traces`"
    for name, text in rendered.items():
        assert (VIEWER / "traces" / name).read_text(encoding="utf-8") == text, f"{name} drifted: run `make traces`"


def test_render_is_deterministic(rendered: dict[str, str]) -> None:
    assert trace.render_all(client=ModelClient()) == rendered


def test_index_lists_scenarios_in_order(rendered: dict[str, str]) -> None:
    index = json.loads(rendered["index.json"])
    assert [s["id"] for s in index["scenarios"]] == ["clean", "ambiguous", "unsafe", "adversarial"]
    assert index["mode"] == "REPLAY"


def test_every_trace_is_marked_illustrative_replay(traces: dict[str, dict]) -> None:
    for data in traces.values():
        assert data["illustrative"] is True
        assert data["mode"] == "REPLAY"
        assert data["trace_version"] == trace.TRACE_VERSION


def test_stage_flags_add_up_to_the_proposal_flags_in_order(traces: dict[str, dict]) -> None:
    for name, data in traces.items():
        stages = data["stages"]
        union = stages["pass1"]["flags"] + stages["pass2"]["flags"] + stages["match"]["flags"]
        assert union == data["proposal"]["flags"], name


@pytest.mark.parametrize(
    ("name", "status", "top", "flags", "confirm_open"),
    [
        ("clean.json", "PROPOSED", "SHF-009", [], True),
        ("ambiguous.json", "PROPOSED", "SHF-005", ["M-01"], False),
        ("unsafe.json", "PROPOSED", "SHF-014", ["R2-02"], False),
        ("adversarial.json", "PROPOSED", "SHF-003", ["R1-05"], False),
    ],
)
def test_scenarios_tell_the_intended_story(
    traces: dict[str, dict], name: str, status: str, top: str, flags: list[str], confirm_open: bool
) -> None:
    data = traces[name]
    assert data["proposal"]["status"] == status
    assert data["stages"]["match"]["candidates"][0]["formula_id"] == top
    assert sorted(f["rule_id"] for f in data["proposal"]["flags"]) == flags
    assert (data["review"]["confirm_blockers"] == []) is confirm_open


def test_block_keeps_confirm_closed_even_after_acknowledging(traces: dict[str, dict]) -> None:
    for data in traces.values():
        if any(f["severity"] == "BLOCK" for f in data["proposal"]["flags"]):
            assert data["review"]["blockers_after_ack"], data["scenario"]["id"]


def test_review_flag_opens_confirm_only_after_acknowledging(traces: dict[str, dict]) -> None:
    review = traces["ambiguous.json"]["review"]
    assert review["review_flag_ids"] == ["M-01"]
    assert review["confirm_blockers"] and review["blockers_after_ack"] == []


def test_trace_module_has_no_write_path() -> None:
    source = Path(trace.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names
    }
    assert not names & {"log_pending", "run_file", "submit", "build_action", "append", "audit"}
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "intake.audit" not in imported


def test_trace_command_writes_only_the_out_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_MODE", "replay")
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out"
    assert main(["trace", "--out", str(out)]) == 0
    assert sorted(p.name for p in tmp_path.rglob("*") if p.is_file()) == sorted(
        ["adversarial.json", "ambiguous.json", "clean.json", "index.json", "unsafe.json"]
    )
    assert not list(tmp_path.rglob("*.sqlite*"))


def test_viewer_carries_the_honesty_lines() -> None:
    html = (VIEWER / "index.html").read_text(encoding="utf-8")
    for line in (
        CREDIT,
        "Synthetic data",
        "Not for clinical use",
        "not for compounding",
        "simulated and saved nowhere",
    ):
        assert line in html, line


def test_viewer_makes_no_network_calls_except_fonts_and_traces() -> None:
    js = (VIEWER / "app.js").read_text(encoding="utf-8")
    fetches = [part.split(")")[0] for part in js.split("fetch(")[1:]]
    assert fetches == ['"traces/index.json"', "`traces/${s.file}`"]
    for marker in ("XMLHttpRequest", "sendBeacon", "WebSocket", "localStorage", "api.anthropic"):
        assert marker not in js, marker
