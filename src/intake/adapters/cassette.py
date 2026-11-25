"""Recordings of model responses in eval/cassettes/, keyed by hash(model_id, prompt_hash, input) (SPEC §7)."""

import hashlib
import json
from pathlib import Path
from typing import Any


class MissingRecordingError(LookupError):
    """REPLAY mode found no recording for a request. In CI this is a failure, never a cue to call a live model."""


def recording_key(model_id: str, prompt_hash: str, input_text: str) -> str:
    """SHA-256 over the canonical JSON of the three parts, so field boundaries can't collide."""
    canonical = json.dumps([model_id, prompt_hash, input_text], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Cassette:
    """One JSON file per recording: <dir>/<key>.json."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def load(self, key: str) -> dict[str, Any]:
        path = self.path_for(key)
        if not path.is_file():
            raise MissingRecordingError(
                f"no recording {path}; record it with INTAKE_MODE=record (never in CI)"
            )
        return json.loads(path.read_text(encoding="utf-8"))["response"]

    def save(
        self, key: str, *, model_id: str, prompt_hash: str, input_text: str, response: dict[str, Any]
    ) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "model_id": model_id,
            "prompt_hash": prompt_hash,
            "input": input_text,
            "response": response,
        }
        path = self.path_for(key)
        path.write_text(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return path
