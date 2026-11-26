"""Anthropic client wrapper with REPLAY / RECORD / LIVE modes (SPEC §7).

REPLAY (default) reads recordings only and never builds a live client, so CI has no network path.
RECORD calls the model and saves the response; LIVE calls the model and saves nothing.
"""

import os
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from intake.adapters.cassette import Cassette, recording_key

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "config.toml"
MODE_ENV = "INTAKE_MODE"


class Mode(StrEnum):
    REPLAY = "REPLAY"
    RECORD = "RECORD"
    LIVE = "LIVE"


def get_mode() -> Mode:
    """Mode from INTAKE_MODE (case-insensitive). Unset or empty means REPLAY; anything unknown raises."""
    raw = os.environ.get(MODE_ENV, "").strip().upper()
    if not raw:
        return Mode.REPLAY
    try:
        return Mode(raw)
    except ValueError:
        allowed = ", ".join(m.value for m in Mode)
        raise ValueError(f"{MODE_ENV}={raw!r} is not one of {allowed}") from None


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)


def _read_config(path: Path) -> dict[str, Any]:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def load_model_config(path: Path = CONFIG_PATH) -> ModelConfig:
    model = _read_config(path)["model"]
    return ModelConfig(model_id=model["model_id"], max_tokens=model["max_tokens"])


def default_cassette_dir(path: Path = CONFIG_PATH) -> Path:
    return REPO_ROOT / _read_config(path)["paths"]["cassettes"]


def _make_live_client(**sdk_kwargs: Any) -> Any:
    """The only place a network client is built. Imported lazily so REPLAY never touches it."""
    import anthropic

    return anthropic.Anthropic(**sdk_kwargs)


class ModelClient:
    """Sends one system prompt + one user input and returns the raw Messages API response as a dict.

    `max_retries` is handed to the SDK client when RECORD or LIVE builds it; None keeps the SDK default.
    REPLAY ignores it and never builds a client.
    """

    def __init__(
        self,
        config: ModelConfig | None = None,
        *,
        mode: Mode | None = None,
        cassette_dir: Path | None = None,
        max_retries: int | None = None,
    ) -> None:
        if max_retries is not None and max_retries < 0:
            raise ValueError(f"max_retries must be >= 0 or None, got {max_retries}")
        self.config = config or load_model_config()
        self.mode = mode or get_mode()
        self.cassette = Cassette(cassette_dir or default_cassette_dir())
        self.max_retries = max_retries
        self._live: Any = None

    def complete(
        self,
        *,
        prompt_hash: str,
        system: str,
        user_input: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        key = recording_key(self.config.model_id, prompt_hash, user_input)
        if self.mode is Mode.REPLAY:
            return self.cassette.load(key)
        response = self._call_live(system, user_input, tools)
        if self.mode is Mode.RECORD:
            self.cassette.save(
                key,
                model_id=self.config.model_id,
                prompt_hash=prompt_hash,
                input_text=user_input,
                response=response,
            )
        return response

    def _call_live(self, system: str, user_input: str, tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        if self.mode is Mode.REPLAY:  # defence in depth; complete() already returned
            raise RuntimeError("REPLAY mode must never call a live model")
        if self._live is None:
            sdk_kwargs = {} if self.max_retries is None else {"max_retries": self.max_retries}
            self._live = _make_live_client(**sdk_kwargs)
        request: dict[str, Any] = {
            "model": self.config.model_id,
            "max_tokens": self.config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user_input}],
        }
        if tools:
            request["tools"] = tools
        return self._live.messages.create(**request).to_dict()
