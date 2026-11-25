"""LLM extraction: free text -> schema-valid `Extraction`, or status MANUAL (SPEC §3, §7).

The raw prescription is only ever sent wrapped as data. The model's tool input is validated against
`Extraction`; on failure there is at most one retry, then MANUAL. A missing recording in REPLAY is not
a failure mode of the model and propagates (CI must fail, never fall back).

This module must never import `intake.audit` (invariant 1).
"""

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from intake.adapters.anthropic_client import REPO_ROOT, ModelConfig
from intake.models import Extraction, Unit

PROMPT_PATH = REPO_ROOT / "prompts" / "extract_v1.md"
TOOL_NAME = "record_extraction"
MAX_ATTEMPTS = 2  # first try + at most one retry


class ExtractStatus(StrEnum):
    OK = "OK"
    MANUAL = "MANUAL"  # same value as ProposalStatus.MANUAL


class Prompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    text: str
    sha256: str


class ExtractResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ExtractStatus
    extraction: Extraction | None
    prompt_versions: dict[str, str]
    model_id: str
    attempts: int = Field(ge=1, le=MAX_ATTEMPTS)
    errors: list[str] = Field(default_factory=list)


class CompletionClient(Protocol):
    config: ModelConfig

    def complete(
        self, *, prompt_hash: str, system: str, user_input: str, tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]: ...


class _AttemptFailed(Exception):
    """The response held no single valid `record_extraction` call."""


def load_prompt(path: Path = PROMPT_PATH) -> Prompt:
    raw = Path(path).read_bytes()
    return Prompt(name=Path(path).stem, text=raw.decode("utf-8"), sha256=hashlib.sha256(raw).hexdigest())


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap_input(text: str) -> str:
    """Wrap raw text as data. Escaping means the text can never close the tag or open a new one."""
    return f"<prescription>\n{_escape(text)}\n</prescription>"


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def build_tool() -> dict[str, Any]:
    """Strict tool whose input mirrors `Extraction`. Every field is required but nullable (strict mode)."""
    ingredient = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "strength": _nullable({"type": "number"}),
            "unit": _nullable({"type": "string", "enum": [u.value for u in Unit]}),
        },
        "required": ["name", "strength", "unit"],
        "additionalProperties": False,
    }
    text = _nullable({"type": "string"})
    properties: dict[str, Any] = {
        "ingredients": {"type": "array", "items": ingredient},
        "dosage_form": text,
        "base": text,
        "route": text,
        "quantity": _nullable({"type": "number"}),
        "quantity_unit": text,
        "directions": text,
        "prescriber_name": text,
        "patient_ref": text,
        "species": text,
        "office_stock": _nullable({"type": "boolean"}),
        "extraction_notes": text,
    }
    return {
        "name": TOOL_NAME,
        "description": "Record the fields extracted from the prescription. Call exactly once.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


def _tool_input(response: dict[str, Any]) -> Any:
    calls = [
        block
        for block in response.get("content") or []
        if block.get("type") == "tool_use" and block.get("name") == TOOL_NAME
    ]
    if len(calls) != 1:
        stop = response.get("stop_reason")
        raise _AttemptFailed(f"expected one {TOOL_NAME} call, got {len(calls)} (stop_reason={stop})")
    payload = calls[0].get("input")
    if not isinstance(payload, str):
        return payload
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise _AttemptFailed(f"{TOOL_NAME} input is not valid JSON") from None


def _describe(error: ValidationError) -> str:
    """Deterministic summary (no input values, no URLs) so a retry's recording key is stable."""
    parts = []
    for item in error.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in item["loc"]) or "<root>"
        parts.append(f"{loc}: {item['msg']}")
    return "; ".join(parts)


def _parse(response: dict[str, Any]) -> Extraction:
    payload = _tool_input(response)
    try:
        return Extraction.model_validate(payload)
    except ValidationError as error:
        raise _AttemptFailed(f"schema validation failed: {_describe(error)}") from None


def _retry_input(wrapped: str, error: str) -> str:
    feedback = f"Your previous output was rejected: {error}. Call {TOOL_NAME} once with a valid object."
    return f"{wrapped}\n\n<validation_feedback>\n{_escape(feedback)}\n</validation_feedback>"


def extract(text: str, *, client: CompletionClient, prompt: Prompt | None = None) -> ExtractResult:
    """Extract fields from raw prescription text. Returns OK with an `Extraction`, or MANUAL after two failures."""
    prompt = prompt or load_prompt()
    wrapped = wrap_input(text)
    user_input = wrapped
    errors: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.complete(
            prompt_hash=prompt.sha256, system=prompt.text, user_input=user_input, tools=[build_tool()]
        )
        try:
            extraction = _parse(response)
        except _AttemptFailed as failure:
            errors.append(str(failure))
            user_input = _retry_input(wrapped, str(failure))
            continue
        return _result(ExtractStatus.OK, extraction, prompt, client, attempt, errors)
    return _result(ExtractStatus.MANUAL, None, prompt, client, MAX_ATTEMPTS, errors)


def _result(
    status: ExtractStatus,
    extraction: Extraction | None,
    prompt: Prompt,
    client: CompletionClient,
    attempts: int,
    errors: list[str],
) -> ExtractResult:
    return ExtractResult(
        status=status,
        extraction=extraction,
        prompt_versions={prompt.name: prompt.sha256},
        model_id=client.config.model_id,
        attempts=attempts,
        errors=errors,
    )
