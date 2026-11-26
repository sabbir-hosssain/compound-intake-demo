"""S1.3 model adapter: modes, config, recording keys, REPLAY safety and the no-audit-import invariant."""

import ast
import json
from pathlib import Path
from typing import Any, ClassVar

import anthropic
import pytest

from intake.adapters import anthropic_client as ac
from intake.adapters.anthropic_client import Mode, ModelClient, ModelConfig, get_mode, load_model_config
from intake.adapters.cassette import Cassette, MissingRecordingError, recording_key

REPO = Path(__file__).resolve().parents[1]
ADAPTERS = REPO / "src" / "intake" / "adapters"

CONFIG = ModelConfig(model_id="claude-test-model", max_tokens=100)
PROMPT_HASH = "a" * 64
INPUT = "Synthetic Rx: illustrative cream 30 g, apply BID."


class _Boom(Exception):
    pass


def _explode(*_args: Any, **_kwargs: Any) -> Any:
    raise _Boom("a live client was constructed")


@pytest.fixture
def no_live_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any attempt to build a live Anthropic client fails the test."""
    monkeypatch.setattr(ac, "_make_live_client", _explode)
    monkeypatch.setattr(anthropic.Anthropic, "__init__", _explode)


# --- mode ---------------------------------------------------------------


def test_mode_defaults_to_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    assert get_mode() is Mode.REPLAY


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("replay", Mode.REPLAY), ("REPLAY", Mode.REPLAY), ("record", Mode.RECORD), (" Live ", Mode.LIVE)],
)
def test_mode_from_env(monkeypatch: pytest.MonkeyPatch, raw: str, expected: Mode) -> None:
    monkeypatch.setenv("INTAKE_MODE", raw)
    assert get_mode() is expected


def test_empty_mode_is_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_MODE", "")
    assert get_mode() is Mode.REPLAY


def test_unknown_mode_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTAKE_MODE", "online")
    with pytest.raises(ValueError, match="INTAKE_MODE"):
        get_mode()


# --- config ---------------------------------------------------------------


def test_model_id_read_from_repo_config() -> None:
    import tomllib

    raw = tomllib.loads((REPO / "config.toml").read_text())
    cfg = load_model_config()
    assert cfg.model_id == raw["model"]["model_id"]
    assert cfg.max_tokens == raw["model"]["max_tokens"]


def test_model_config_from_custom_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[model]\nmodel_id = "claude-other"\nmax_tokens = 50\n')
    cfg = load_model_config(path)
    assert cfg.model_id == "claude-other"
    assert cfg.max_tokens == 50


def test_default_cassette_dir_comes_from_config() -> None:
    assert ac.default_cassette_dir() == REPO / "eval" / "cassettes"


# --- recording key -----------------------------------------------------------


def test_recording_key_is_deterministic_sha256() -> None:
    key = recording_key("m", PROMPT_HASH, INPUT)
    assert key == recording_key("m", PROMPT_HASH, INPUT)
    assert len(key) == 64
    int(key, 16)


@pytest.mark.parametrize(
    "other",
    [("m2", PROMPT_HASH, INPUT), ("m", "b" * 64, INPUT), ("m", PROMPT_HASH, INPUT + " ")],
)
def test_recording_key_changes_with_each_part(other: tuple[str, str, str]) -> None:
    assert recording_key("m", PROMPT_HASH, INPUT) != recording_key(*other)


def test_recording_key_has_no_field_boundary_collisions() -> None:
    assert recording_key("ab", "c", "d") != recording_key("a", "bc", "d")


# --- REPLAY ------------------------------------------------------------------


def test_replay_missing_recording_raises(tmp_path: Path, no_live_client: None) -> None:
    client = ModelClient(CONFIG, mode=Mode.REPLAY, cassette_dir=tmp_path)
    with pytest.raises(MissingRecordingError):
        client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)


def test_replay_returns_recorded_response(tmp_path: Path, no_live_client: None) -> None:
    response = {"id": "msg_1", "content": [{"type": "text", "text": "ok"}]}
    Cassette(tmp_path).save(
        recording_key(CONFIG.model_id, PROMPT_HASH, INPUT),
        model_id=CONFIG.model_id,
        prompt_hash=PROMPT_HASH,
        input_text=INPUT,
        response=response,
    )
    client = ModelClient(CONFIG, mode=Mode.REPLAY, cassette_dir=tmp_path)
    assert client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT) == response


def test_replay_never_constructs_a_live_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_live_client: None
) -> None:
    """No network in CI: REPLAY must not build an Anthropic client, on a hit or a miss, even with a key set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.delenv("INTAKE_MODE", raising=False)
    client = ModelClient(CONFIG, cassette_dir=tmp_path)  # mode from env -> REPLAY
    assert client.mode is Mode.REPLAY
    with pytest.raises(MissingRecordingError):
        client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    assert client._live is None


def test_replay_does_not_write_cassettes(tmp_path: Path, no_live_client: None) -> None:
    client = ModelClient(CONFIG, mode=Mode.REPLAY, cassette_dir=tmp_path)
    with pytest.raises(MissingRecordingError):
        client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    assert list(tmp_path.iterdir()) == []


# --- RECORD / LIVE with a fake live client -----------------------------------------


class _FakeMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload


class _FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return _FakeMessage({"id": "msg_fake", "content": [{"type": "text", "text": "hi"}]})


class _FakeAnthropic:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


@pytest.fixture
def fake_live(monkeypatch: pytest.MonkeyPatch) -> _FakeAnthropic:
    fake = _FakeAnthropic()
    monkeypatch.setattr(ac, "_make_live_client", lambda: fake)
    return fake


def test_record_calls_live_and_saves(tmp_path: Path, fake_live: _FakeAnthropic) -> None:
    client = ModelClient(CONFIG, mode=Mode.RECORD, cassette_dir=tmp_path)
    tools = [{"name": "t", "description": "d", "input_schema": {"type": "object"}}]
    out = client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT, tools=tools)

    assert out["id"] == "msg_fake"
    (call,) = fake_live.messages.calls
    assert call["model"] == CONFIG.model_id
    assert call["max_tokens"] == CONFIG.max_tokens
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": INPUT}]
    assert call["tools"] == tools

    key = recording_key(CONFIG.model_id, PROMPT_HASH, INPUT)
    saved = json.loads((tmp_path / f"{key}.json").read_text())
    assert saved["response"] == out
    assert saved["model_id"] == CONFIG.model_id
    assert saved["prompt_hash"] == PROMPT_HASH

    # The recording now replays without any live client.
    replay = ModelClient(CONFIG, mode=Mode.REPLAY, cassette_dir=tmp_path)
    replay._live = None
    assert replay.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT) == out


def test_live_calls_live_and_does_not_save(tmp_path: Path, fake_live: _FakeAnthropic) -> None:
    client = ModelClient(CONFIG, mode=Mode.LIVE, cassette_dir=tmp_path)
    out = client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    assert out["id"] == "msg_fake"
    assert "tools" not in fake_live.messages.calls[0]
    assert list(tmp_path.iterdir()) == []


# --- max_retries (S3.9) -----------------------------------------------------------


class _KwargsAnthropic:
    """Stands in for anthropic.Anthropic and records the kwargs it was built with."""

    built: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        type(self).built.append(kwargs)
        self.messages = _FakeMessages()


@pytest.fixture
def sdk_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(_KwargsAnthropic, "built", built)
    monkeypatch.setattr(anthropic, "Anthropic", _KwargsAnthropic)
    return built


@pytest.mark.parametrize("mode", [Mode.RECORD, Mode.LIVE])
@pytest.mark.parametrize("retries", [0, 3])
def test_max_retries_is_passed_to_the_sdk_client(
    tmp_path: Path, sdk_kwargs: list[dict[str, Any]], mode: Mode, retries: int
) -> None:
    client = ModelClient(CONFIG, mode=mode, cassette_dir=tmp_path, max_retries=retries)
    assert client.max_retries == retries
    client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    assert sdk_kwargs == [{"max_retries": retries}]  # built once, with the setting


@pytest.mark.parametrize("mode", [Mode.RECORD, Mode.LIVE])
def test_default_max_retries_keeps_the_sdk_default(
    tmp_path: Path, sdk_kwargs: list[dict[str, Any]], mode: Mode
) -> None:
    client = ModelClient(CONFIG, mode=mode, cassette_dir=tmp_path)
    assert client.max_retries is None
    client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)
    assert sdk_kwargs == [{}]


def test_replay_with_max_retries_never_constructs_a_live_client(tmp_path: Path, no_live_client: None) -> None:
    client = ModelClient(CONFIG, mode=Mode.REPLAY, cassette_dir=tmp_path, max_retries=0)
    with pytest.raises(MissingRecordingError):
        client.complete(prompt_hash=PROMPT_HASH, system="sys", user_input=INPUT)


def test_negative_max_retries_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_retries"):
        ModelClient(CONFIG, mode=Mode.LIVE, cassette_dir=tmp_path, max_retries=-1)


def test_nothing_outside_adapters_touches_the_private_live_client() -> None:
    """Gate 2 decision 9: callers use `max_retries`, not `ModelClient._live`. Adapter tests are white-box."""
    roots = [REPO / "src", REPO / "app", REPO / "scripts", REPO / "eval"]
    offenders = [
        str(path.relative_to(REPO))
        for root in roots
        if root.is_dir()
        for path in root.rglob("*.py")
        if ADAPTERS not in path.parents and "._live" in path.read_text(encoding="utf-8").replace("._live_", "")
    ]
    assert offenders == []


# --- invariant 1 ---------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative import inside intake.adapters
                base = "intake." + base if node.level == 2 else "intake.adapters." + base
            names.add(base)
            names.update(f"{base}.{alias.name}".strip(".") for alias in node.names)
    return names


def test_adapters_never_import_audit() -> None:
    files = sorted(ADAPTERS.glob("*.py"))
    assert files, "no adapter modules found"
    for path in files:
        bad = {m for m in _imported_modules(path) if m == "intake.audit" or m.startswith("intake.audit.")}
        assert not bad, f"{path.name} imports {bad}"
        assert "import_module" not in path.read_text(), f"{path.name}: dynamic imports hide the audit check"
