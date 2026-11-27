"""S4.4 (#27): docs/DEMO.md is a walkthrough of the clean, unsafe and injection showcase cases, and every
command it shows is exact.

DEMO.md pairs each command it shows output for as a ```sh block holding one command, followed directly by a
```text block holding that command's output. These tests run those commands in order, in REPLAY with no API
key, against a fresh audit DB in a temporary directory, and require the shown output to match exactly.
No model is called: a missing recording fails the test.
"""

import re
import shlex
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from intake import cli
from intake.adapters import anthropic_client

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "docs" / "DEMO.md"
CASES = {
    "clean": "samples/demo_1_clean.txt",
    "unsafe": "samples/demo_2_unsafe.txt",
    "injection": "samples/demo_3_injection.txt",
}
BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


@pytest.fixture(autouse=True)
def _replay_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def _boom(**_: Any) -> Any:
        raise AssertionError("a live client was constructed in REPLAY")

    monkeypatch.setattr(anthropic_client, "_make_live_client", _boom)


@pytest.fixture(scope="module")
def demo() -> str:
    assert DEMO.is_file(), "docs/DEMO.md is missing"
    return DEMO.read_text(encoding="utf-8")


def _blocks(text: str) -> list[tuple[str, str]]:
    return [(lang, body) for lang, body in BLOCK.findall(text)]


def _commands(text: str) -> list[str]:
    """Every command line in the ```sh blocks (comments and blank lines dropped)."""
    lines = []
    for lang, body in _blocks(text):
        if lang == "sh":
            for line in body.splitlines():
                line = line.split("  #", 1)[0].strip()
                if line and not line.startswith("#"):
                    lines.append(line)
    return lines


def _pairs(text: str) -> list[tuple[str, str]]:
    """(command, shown output) for each one-command ```sh block followed directly by a ```text block."""
    blocks = list(BLOCK.finditer(text))
    pairs = []
    for first, second in pairwise(blocks):
        between = text[first.end() : second.start()]
        if first.group(1) == "sh" and second.group(1) == "text" and not between.strip():
            commands = _commands(first.group(0))
            assert len(commands) == 1, f"a ```sh block followed by output must hold one command: {commands}"
            pairs.append((commands[0], second.group(2)))
    return pairs


def _make_targets() -> set[str]:
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    return {line.split(":", 1)[0].strip() for line in makefile.splitlines() if re.match(r"^[a-z][\w-]*\s*:", line)}


def _run_intake(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    args = [str(REPO / a) if a.startswith("samples/") else a for a in argv]
    code = cli.main(args)
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK, f"`intake {' '.join(argv)}` exited {code}"
    return out


# --- coverage of the AC ----------------------------------------------------------------------------


@pytest.mark.parametrize("name,sample", CASES.items())
def test_each_showcase_case_is_run_with_an_exact_command(demo: str, name: str, sample: str) -> None:
    assert name in demo.lower(), f"DEMO.md never mentions the {name} case"
    commands = [c for c, _ in _pairs(demo)]
    assert any(c.startswith("uv run intake run ") and sample in c for c in commands), (
        f"DEMO.md has no `uv run intake run {sample}` command with its output"
    )


def test_walkthrough_is_timed_for_three_to_five_minutes(demo: str) -> None:
    assert re.search(r"3[–-]5 min", demo), "DEMO.md should say it is a 3–5 minute walkthrough"
    cues = re.findall(r"\b(\d):(\d\d)\b", demo)
    assert cues, "DEMO.md has no time cues (m:ss)"
    assert max(int(m) * 60 + int(s) for m, s in cues) <= 5 * 60


def test_needs_no_api_key(demo: str) -> None:
    assert "no API key" in demo
    for command in _commands(demo):
        assert "record" not in command.lower() and "live" not in command.lower(), command
        assert "ANTHROPIC_API_KEY" not in command


# --- every command is real -------------------------------------------------------------------------


def test_every_command_is_a_known_command(demo: str) -> None:
    targets = _make_targets()
    for command in _commands(demo):
        argv = shlex.split(command)
        env = [a for a in argv if re.match(r"^[A-Z_]+=", a)]
        argv = argv[len(env) :]
        if argv[:3] == ["uv", "run", "intake"]:
            cli._parser().parse_args(argv[3:])  # SystemExit on an unknown command or flag
            for arg in argv[3:]:
                if arg.startswith("samples/"):
                    assert (REPO / arg).is_file(), f"no such sample: {arg}"
        elif argv[0] == "make":
            assert argv[1] in targets, f"no Makefile target '{argv[1]}'"
        elif argv[0] == "cat":
            assert (REPO / argv[1]).is_file(), f"no such file: {argv[1]}"
        elif argv[:3] == ["uv", "run", "streamlit"]:
            assert (REPO / argv[4]).is_file()
        elif argv[0] in ("uv", "rm"):
            assert argv[:2] in (["uv", "sync"], ["rm", "-f"]), command
        else:
            pytest.fail(f"unexpected command in DEMO.md: {command}")


def test_shown_output_matches_a_real_replay_run(
    demo: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run the shown commands in order from a fresh directory; each shown output is exactly what it prints."""
    monkeypatch.chdir(tmp_path)
    pairs = _pairs(demo)
    assert len(pairs) >= 4, "expected output for the three cases and the audit check"
    for command, shown in pairs:
        argv = shlex.split(command)
        if argv[0] == "cat":
            actual = (REPO / argv[1]).read_text(encoding="utf-8")
        elif argv[:3] == ["uv", "run", "intake"]:
            actual = _run_intake(argv[3:], capsys)
        else:
            pytest.fail(f"no way to check the output of: {command}")
        assert shown == actual, f"output shown for `{command}` differs from a real REPLAY run"


def test_make_demo_closing_line_is_quoted_exactly(demo: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert "make demo" in _commands(demo)
    last = _run_intake(["demo"], capsys).strip().splitlines()[-1]
    assert last in demo, f"DEMO.md should quote make demo's last line: {last}"
