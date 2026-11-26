"""S3.5b (#62): `intake demo` walks the three demo fixtures in REPLAY, with no API key and no audit write.

1. Every demo input (samples/demo_*.txt, data/demo/demo_cases.jsonl) has a committed REPLAY recording.
2. `intake demo` in REPLAY gives each case the formula, status, flags and CONFIRM state in the fixture.
3. A missing recording fails loudly (non-zero exit, error on stderr), never a live call.
4. The demo writes nothing to the audit log (invariant 1): only a pharmacist action commits a record.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from intake import audit, cli, pipeline
from intake.adapters import anthropic_client
from intake.adapters.anthropic_client import ModelClient, load_model_config
from intake.adapters.cassette import Cassette, recording_key
from intake.cli import main
from intake.extract import load_prompt, wrap_input
from intake.models import Severity

REPO = Path(__file__).resolve().parents[1]
DEMO_CASES = REPO / "data" / "demo" / "demo_cases.jsonl"
SAMPLES = sorted((REPO / "samples").glob("demo_*.txt"))


def _cases() -> list[dict[str, Any]]:
    lines = DEMO_CASES.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


CASES = _cases()


@pytest.fixture(autouse=True)
def _replay_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs in REPLAY with no API key, and constructing a live client is a failure."""
    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(**_: Any) -> Any:
        raise AssertionError("a live client was constructed in REPLAY")

    monkeypatch.setattr(anthropic_client, "_make_live_client", _boom)


@pytest.fixture
def no_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to open the audit log fails the test."""

    def _refuse(*_: Any, **__: Any) -> Any:
        raise AssertionError("the demo opened the audit log")

    monkeypatch.setattr(audit, "connect", _refuse)
    monkeypatch.setattr(pipeline, "log_pending", _refuse)


def _key(text: str) -> str:
    model_id = load_model_config().model_id
    return recording_key(model_id, load_prompt().sha256, wrap_input(text))


# --- 1. recording coverage (invariant 4 for the demo inputs) -----------------------------------


def test_three_demo_samples_and_cases() -> None:
    assert [p.stem for p in SAMPLES] == ["demo_1_clean", "demo_2_unsafe", "demo_3_injection"]
    assert sorted(REPO / c["sample_file"] for c in CASES) == SAMPLES


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda p: p.stem)
def test_every_demo_sample_has_a_recording(sample: Path) -> None:
    cassette = Cassette(anthropic_client.default_cassette_dir())
    text = sample.read_bytes().decode("utf-8")
    assert cassette.path_for(_key(text)).is_file(), f"no REPLAY recording for {sample.name}"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_every_demo_case_has_a_recording(case: dict[str, Any]) -> None:
    """The demo sends the case's sample file; it must be the jsonl text and have a recording."""
    cassette = Cassette(anthropic_client.default_cassette_dir())
    text = cli.demo_case_text(case)
    assert text.rstrip("\n") == case["raw"]["text"]
    assert cassette.path_for(_key(text)).is_file(), f"no REPLAY recording for {case['case_id']}"


def test_demo_recordings_are_for_the_current_unsafe_text() -> None:
    """demo_2_unsafe is minoxidil 12% (SHF-014); the recording holds that text."""
    case = next(c for c in CASES if c["case_id"] == "demo_2_unsafe")
    assert "Minoxidil 12%" in case["raw"]["text"]
    path = Cassette(anthropic_client.default_cassette_dir()).path_for(_key(cli.demo_case_text(case)))
    assert "Minoxidil 12%" in json.loads(path.read_text(encoding="utf-8"))["input"]


# --- 2. outcomes in REPLAY --------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["case_id"])
def test_demo_case_outcome_matches_fixture(case: dict[str, Any], no_audit: None) -> None:
    proposal = cli.demo_proposal(case, client=ModelClient())
    top = proposal.candidates[0].formula_id if proposal.candidates else None
    assert top == case["expected_formula_id"]
    assert proposal.status.value == case["expected_status"]
    assert sorted(f.rule_id for f in proposal.flags) == sorted(case["expected_flags"])
    has_block = any(f.severity is Severity.BLOCK for f in proposal.flags)
    assert has_block is case["expect_confirm_disabled"]


def test_intake_demo_prints_every_case_and_exits_ok(no_audit: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    for case in CASES:
        assert case["case_id"] in out
        assert case["expected_formula_id"] in out
        for rule_id in case["expected_flags"]:
            assert rule_id in out
    blocks = [line for line in out.splitlines() if line.startswith("CONFIRM:")]
    expected = ["disabled" if c["expect_confirm_disabled"] else "enabled" for c in CASES]
    assert [line.split()[1] for line in blocks] == expected
    assert out.count("matches the fixture") == len(CASES)
    assert "3/3 demo cases match" in out


def test_intake_demo_fails_when_an_outcome_differs(
    tmp_path: Path, no_audit: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A wrong expectation makes the demo exit non-zero, so `make demo` cannot hide a drift."""
    case = dict(CASES[0], sample_file=str(REPO / CASES[0]["sample_file"]), expected_formula_id="SHF-999")
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(case) + "\n", encoding="utf-8")
    assert main(["demo", "--cases", str(cases)]) == cli.EXIT_DEMO_MISMATCH
    out = capsys.readouterr().out
    assert "DIFFERS from the fixture" in out
    assert "0/1 demo cases match" in out


# --- 3. missing recording fails loudly --------------------------------------------------------


def test_missing_recording_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_audit: None, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(anthropic_client, "default_cassette_dir", lambda *_: tmp_path / "empty")
    assert main(["demo"]) == cli.EXIT_MISSING_RECORDING
    err = capsys.readouterr().err
    assert "no recording" in err
    assert "demo_1_clean" in err


def test_missing_cases_file_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["demo", "--cases", str(tmp_path / "nope.jsonl")]) == cli.EXIT_ERROR
    assert "cannot read" in capsys.readouterr().err


# --- 4. no audit write (invariant 1) ----------------------------------------------------------


def test_demo_writes_no_audit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the audit path pointed at a temp file, the demo leaves no file behind."""
    db = tmp_path / "audit.sqlite"
    monkeypatch.setattr(audit, "db_path", lambda *_: db)
    assert main(["demo"]) == cli.EXIT_OK
    assert not db.exists()


def test_demo_says_nothing_was_logged(no_audit: None, capsys: pytest.CaptureFixture[str]) -> None:
    main(["demo"])
    assert "nothing written to the audit log" in capsys.readouterr().out


# --- end to end: the `make demo` command line -------------------------------------------------


def test_intake_demo_subprocess_without_api_key() -> None:
    """`INTAKE_MODE=replay intake demo` with ANTHROPIC_API_KEY unset, as `make demo` runs it."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env[anthropic_client.MODE_ENV] = "replay"
    script = Path(sys.executable).parent / "intake"
    result = subprocess.run([str(script), "demo"], check=False, capture_output=True, text=True, cwd=REPO, env=env)
    assert result.returncode == 0, result.stderr
    assert "3/3 demo cases match" in result.stdout
