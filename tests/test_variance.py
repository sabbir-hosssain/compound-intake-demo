"""S2.7 run-to-run variance: disagreement definitions, the results section, `--runs`, and call counting.

Every test uses stub clients or REPLAY recordings; constructing a live network client is a failure.
"""

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:  # `eval/` is a top-level package next to `src/`, run with `python -m`
    sys.path.insert(0, str(REPO))

from eval import run_eval, variance
from eval.metrics import Outcome
from intake.adapters import anthropic_client
from intake.adapters.anthropic_client import Mode, ModelConfig
from intake.adapters.cassette import MissingRecordingError
from intake.models import Extraction, Ingredient, ProposalStatus

SEED = REPO / "data" / "seed" / "seed_cases.jsonl"
DAY = date(2026, 11, 25)
P, NM, MAN = ProposalStatus.PROPOSED, ProposalStatus.NO_MATCH, ProposalStatus.MANUAL


@pytest.fixture(autouse=True)
def _replay_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")

    def _boom() -> Any:
        raise AssertionError("a live client was constructed in a unit test")

    monkeypatch.setattr(anthropic_client, "_make_live_client", _boom)


def _ext(name: str = "urea", strength: float = 10, base: str | None = "cream base", **kw: Any) -> Extraction:
    return Extraction(ingredients=[Ingredient(name=name, strength=strength, unit="%")], base=base, **kw)


def _out(status: ProposalStatus | None = P, top: str = "SHF-001", flags: tuple[str, ...] = (), **kw: Any) -> Outcome:
    candidates = (top, "SHF-002") if status is P else ()
    return Outcome(status=status, candidates=candidates, flags=flags, **kw)


CASES = ("a", "b", "c")
CATS = ("clean", "unsafe", "clean")


def _compute(runs: list[list[Outcome]]) -> variance.Variance:
    return variance.compute(CASES, CATS, runs, aliases={})


# --- definitions ---------------------------------------------------------------------------------


def test_identical_runs_have_zero_disagreement() -> None:
    run = [_out(extraction=_ext()), _out(NM, flags=("R1-01",), extraction=_ext()), _out(MAN)]
    v = _compute([run, run, run])
    assert v.runs == 3 and v.cases == 3
    assert (v.decision.k, v.decision.n) == (0, 3)
    assert (v.flags.k, v.flags.n) == (0, 3)
    assert (v.fields.k, v.fields.n) == (0, 3 * len(variance.EXTRACTION_FIELDS))
    assert (v.any.k, v.any.n) == (0, 3)
    assert v.disagreements == []


def test_top1_change_is_a_decision_disagreement() -> None:
    base = [_out(), _out(), _out()]
    other = [_out(top="SHF-003"), _out(), _out()]
    v = _compute([base, base, other])
    assert (v.decision.k, v.decision.n) == (1, 3)
    assert v.decision_by_category["clean"].k == 1 and v.decision_by_category["clean"].n == 2
    assert v.decision_by_category["unsafe"].k == 0
    assert [d.case_id for d in v.disagreements] == ["a"]
    assert "decision" in v.disagreements[0].kinds


def test_status_change_with_same_top_candidate_is_a_decision_disagreement() -> None:
    v = _compute([[_out(), _out(), _out()], [_out(NM), _out(), _out()]])
    assert v.decision.k == 1


def test_lower_ranked_candidates_do_not_count() -> None:
    a = Outcome(status=P, candidates=("SHF-001", "SHF-002"))
    b = Outcome(status=P, candidates=("SHF-001", "SHF-009"))
    v = _compute([[a, a, a], [b, a, a]])
    assert v.decision.k == 0


def test_flag_set_disagreement_ignores_order_and_counts_sets() -> None:
    a = _out(flags=("R1-01", "M-01"))
    b = _out(flags=("M-01", "R1-01"))
    c = _out(flags=("R1-01",))
    v = _compute([[a, a, a], [b, a, c]])
    assert (v.flags.k, v.flags.n) == (1, 3)
    assert [d.case_id for d in v.disagreements] == ["c"]
    assert v.disagreements[0].kinds == ("flags",)


def test_field_disagreement_is_per_field_and_uses_metric_normalisation() -> None:
    a = _out(extraction=_ext(base="Cream Base"))
    same = _out(extraction=_ext(base="cream  base"))  # case/space-insensitive, as field accuracy scores it
    diff = _out(extraction=_ext(strength=5))
    v = _compute([[a, a, a], [same, diff, a]])
    assert v.fields.k == 1
    assert v.by_field["ingredients"].k == 1 and v.by_field["ingredients"].n == 3
    assert v.by_field["base"].k == 0
    assert [d.case_id for d in v.disagreements] == ["b"]
    assert v.disagreements[0].fields == ("ingredients",)


def test_extraction_in_some_runs_only_disagrees_on_every_field() -> None:
    a = _out(extraction=_ext())
    manual = _out(MAN)
    v = _compute([[a, manual, manual], [manual, manual, manual]])
    assert v.fields.k == len(variance.EXTRACTION_FIELDS)
    assert v.decision.k == 1  # PROPOSED vs MANUAL


def test_error_in_one_run_is_a_disagreement() -> None:
    a = _out()
    v = _compute([[a, a, a], [Outcome(), a, a]])
    assert v.decision.k == 1
    assert v.disagreements[0].case_id == "a"


def test_any_counts_each_case_once() -> None:
    a = _out(flags=("M-01",), extraction=_ext())
    b = _out(top="SHF-004", flags=(), extraction=_ext(strength=1))
    v = _compute([[a, a, a], [b, a, a]])
    assert (v.any.k, v.any.n) == (1, 3)
    assert set(v.disagreements[0].kinds) == {"decision", "flags", "fields"}


def test_needs_two_runs_of_equal_length() -> None:
    run = [_out(), _out(), _out()]
    with pytest.raises(ValueError):
        _compute([run])
    with pytest.raises(ValueError):
        _compute([run, run[:2]])


# --- rendering -----------------------------------------------------------------------------------


def test_section_states_definitions_rates_and_calls() -> None:
    v = _compute([[_out(), _out(), _out()], [_out(top="SHF-003"), _out(), _out()]])
    summaries = [
        variance.RunSummary(run=1, top1=v.decision, failed_gates=(), gates_total=3, errors=0),
        variance.RunSummary(run=2, top1=v.decision, failed_gates=("unsafe_flag_recall",), gates_total=3, errors=1),
    ]
    text = "\n".join(variance.render(v, summaries, calls=variance.CallCount(calls=7, retries=1), mode=Mode.LIVE))
    assert text.startswith("## Run-to-run variance (2 LIVE runs)")
    assert "Decision disagreement" in text and "Flag-set disagreement" in text
    assert "Field disagreement" in text and "Any disagreement" in text
    assert "1/3 33%" in text
    assert "7 model calls" in text and "1 transient retr" in text
    assert "FAIL: unsafe_flag_recall" in text
    assert "| a |" in text


def test_decision_text_shows_top1_only_when_proposed() -> None:
    assert variance.decision_text(_out()) == "PROPOSED SHF-001"
    assert variance.decision_text(Outcome(status=NM, candidates=("SHF-001",))) == "NO_MATCH"
    assert variance.decision_text(_out(MAN)) == "MANUAL"
    assert variance.decision_text(Outcome()) == "none"


def test_placeholder_when_single_run() -> None:
    text = "\n".join(variance.not_measured(Mode.REPLAY))
    assert text.startswith("## Run-to-run variance")
    assert "--runs" in text


# --- --runs in the harness -----------------------------------------------------------------------


def _main(tmp_path: Path, *extra: str, client: Any = None) -> int:
    argv = ["--results-dir", str(tmp_path / "results"), "--date", DAY.isoformat(), "--cases", str(SEED), *extra]
    return run_eval.main(argv, client=client)


def _results(tmp_path: Path) -> str:
    return (tmp_path / "results" / f"{DAY.isoformat()}.md").read_text(encoding="utf-8")


def test_runs_flag_defaults_to_one_and_parses() -> None:
    assert run_eval._parser().parse_args([]).runs == 1
    assert run_eval._parser().parse_args(["--runs", "3"]).runs == 3


def test_runs_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        _main(tmp_path, "--runs", "0")


def test_replay_three_runs_writes_a_variance_section_with_zero_disagreement(tmp_path: Path) -> None:
    """REPLAY is deterministic, so three runs agree; the section is filled, not the placeholder."""
    assert _main(tmp_path, "--mode", "replay", "--runs", "3", "--enforce-gates") == 0
    text = _results(tmp_path)
    assert "## Run-to-run variance (3 REPLAY runs)" in text
    assert "0/5 0%" in text
    assert "Not measured" not in text
    assert text.count("## Run-to-run variance") == 1


def test_single_run_keeps_the_placeholder(tmp_path: Path) -> None:
    _main(tmp_path, "--mode", "replay")
    assert "Not measured" in _results(tmp_path)


def test_record_mode_rejects_several_runs(tmp_path: Path) -> None:
    """Several RECORD runs would overwrite the recordings; refuse before any call."""
    assert _main(tmp_path, "--mode", "record", "--runs", "3") == run_eval.EXIT_GATE_FAILED


class _FlakyFlagClient:
    """Answers with no tool call (so MANUAL) and counts calls."""

    def __init__(self) -> None:
        self.config = ModelConfig(model_id="fake-model", max_tokens=10)
        self.calls = 0

    def complete(self, **_: Any) -> dict[str, Any]:
        self.calls += 1
        return {"content": [{"type": "text", "text": "no"}], "stop_reason": "end_turn"}


def test_runs_call_the_client_once_per_attempt_per_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    client = _FlakyFlagClient()
    _main(tmp_path, "--runs", "2", client=client)
    # no tool call -> extract retries once -> 2 calls per case, 5 cases, 2 runs
    assert client.calls == 2 * 5 * 2
    assert "model calls: 20" in capsys.readouterr().out
    assert "## Run-to-run variance (2 REPLAY runs)" in _results(tmp_path)


def test_gate_failure_in_a_later_run_fails_enforce_gates(tmp_path: Path) -> None:
    """A hard gate must hold in every run, not only the first."""

    class _GoodThenBad:
        def __init__(self) -> None:
            self.config = ModelConfig(model_id="claude-sonnet-5-5", max_tokens=10)
            self.replay = run_eval.make_client("replay")
            self.calls = 0

        def complete(self, **kw: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls > 5:  # run 2: every case goes MANUAL with no extraction
                raise RuntimeError("boom")
            return self.replay.complete(**kw)

    assert _main(tmp_path, "--runs", "1", "--enforce-gates", client=_GoodThenBad()) == 0
    assert _main(tmp_path, "--runs", "2", "--enforce-gates", client=_GoodThenBad()) == run_eval.EXIT_GATE_FAILED


def test_missing_recording_in_any_run_exits_2(tmp_path: Path) -> None:
    class _MissingSecond:
        def __init__(self) -> None:
            self.config = ModelConfig(model_id="claude-sonnet-5-5", max_tokens=10)
            self.replay = run_eval.make_client("replay")
            self.calls = 0

        def complete(self, **kw: Any) -> dict[str, Any]:
            self.calls += 1
            if self.calls > 5:
                raise MissingRecordingError("gone")
            return self.replay.complete(**kw)

    assert _main(tmp_path, "--runs", "2", client=_MissingSecond()) == run_eval.EXIT_MISSING_RECORDING


# --- call counting and bounded retries -----------------------------------------------------------


def _status_error(code: int) -> anthropic.APIStatusError:
    """A real SDK status error over a stand-in response (no transport library needed)."""
    response: Any = SimpleNamespace(request=None, status_code=code, headers={})
    return anthropic.APIStatusError("err", response=response, body=None)


class _Scripted:
    def __init__(self, *effects: Any) -> None:
        self.config = ModelConfig(model_id="fake-model", max_tokens=10)
        self.mode = Mode.LIVE
        self.effects = list(effects)

    def complete(self, **_: Any) -> dict[str, Any]:
        effect = self.effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def test_counting_client_counts_calls_and_retries_transient_errors() -> None:
    inner = _Scripted(_status_error(529), {"ok": 1}, {"ok": 2})
    client = variance.CountingClient(inner, retry_budget=10, sleep=lambda _: None)
    assert client.complete(prompt_hash="h", system="s", user_input="u") == {"ok": 1}
    assert client.complete(prompt_hash="h", system="s", user_input="u") == {"ok": 2}
    assert (client.count.calls, client.count.retries) == (3, 1)
    assert client.mode is Mode.LIVE and client.config.model_id == "fake-model"


def test_retry_budget_is_shared_and_bounded() -> None:
    inner = _Scripted(_status_error(500), _status_error(429), _status_error(503))
    client = variance.CountingClient(inner, retry_budget=2, sleep=lambda _: None)
    with pytest.raises(anthropic.APIStatusError):
        client.complete(prompt_hash="h", system="s", user_input="u")
    assert (client.count.calls, client.count.retries) == (3, 2)


@pytest.mark.parametrize("error", [_status_error(400), MissingRecordingError("x"), ValueError("x")])
def test_non_transient_errors_are_not_retried(error: Exception) -> None:
    client = variance.CountingClient(_Scripted(error, {"ok": 1}), retry_budget=10, sleep=lambda _: None)
    with pytest.raises(type(error)):
        client.complete(prompt_hash="h", system="s", user_input="u")
    assert (client.count.calls, client.count.retries) == (1, 0)


def test_connection_error_is_transient() -> None:
    request: Any = SimpleNamespace()
    assert variance.is_transient(anthropic.APIConnectionError(request=request))
    assert not variance.is_transient(_status_error(401))


def test_call_limit_stops_further_calls() -> None:
    client = variance.CountingClient(_Scripted({"ok": 1}, {"ok": 2}), max_calls=1, sleep=lambda _: None)
    client.complete(prompt_hash="h", system="s", user_input="u")
    with pytest.raises(variance.CallBudgetExceeded):
        client.complete(prompt_hash="h", system="s", user_input="u")
    assert client.count.calls == 1


# --- LIVE client: no SDK-hidden retries, no recordings written -----------------------------------


def test_live_client_disables_sdk_retries_and_never_writes_recordings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[dict[str, Any]] = []

    class _FakeMessages:
        def create(self, **_: Any) -> Any:
            class _Msg:
                def to_dict(self) -> dict[str, Any]:
                    return {"content": [], "stop_reason": "end_turn"}

            return _Msg()

    class _FakeAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeAnthropic)
    client = variance.live_model_client(cassette_dir=tmp_path)
    assert client.mode is Mode.LIVE
    client.complete(prompt_hash="h", system="s", user_input="u")
    assert built == [{"max_retries": 0}]
    assert list(tmp_path.iterdir()) == []
