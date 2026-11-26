"""LLM explanation (SPEC §3, §7): plain-text reasons for a proposal the code has already scored.

The model sees the scored facts (status, confidence, margin, candidates with component scores, flags,
extracted fields) wrapped as data and answers in plain text, with no tools. `explain` returns an
`Explanation`, which has no field for candidates, flags or status. `with_reasons` builds a new Proposal
that differs from the input only in `reasons` and `prompt_versions`, so the explanation can't change
the match or drop a flag (invariant 2).

Reasons must cite every flag by rule ID and every component score of the top candidate as
`name=value`. A reply that misses one is replaced by a deterministic text built from the same facts.

This module must never import `intake.audit` (invariant 1), directly or through `intake.pipeline`.
"""

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from intake.adapters.anthropic_client import REPO_ROOT
from intake.extract import CompletionClient, Prompt
from intake.extract import load_prompt as _load_prompt
from intake.models import MatchCandidate, Proposal, ProposalStatus, Severity

PROMPT_PATH = REPO_ROOT / "prompts" / "explain_v1.md"
PROMPT_PREFIX = "explain_"
COMPONENTS = ("ingredients", "strength", "dosage_form", "base", "route")


class ExplainSource(StrEnum):
    MODEL = "MODEL"
    FALLBACK = "FALLBACK"  # the model's reply missed a required citation


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reasons: str
    source: ExplainSource
    missing: list[str] = Field(default_factory=list)
    prompt_versions: dict[str, str]
    model_id: str


def load_prompt(path: Path = PROMPT_PATH) -> Prompt:
    return _load_prompt(path)


# --- input -------------------------------------------------------------------------------------


def _num(value: float) -> str:
    return f"{value:.2f}"


def _candidate(rank: int, cand: MatchCandidate) -> dict[str, Any]:
    scores = cand.component_scores
    return {
        "rank": rank,
        "formula_id": cand.formula_id,
        "score": _num(cand.score),
        "component_scores": {k: _num(scores[k]) for k in COMPONENTS if k in scores},
    }


def facts(proposal: Proposal) -> dict[str, Any]:
    """The scored facts the model may describe. No IDs or timestamps, so recordings are reproducible."""
    extraction = proposal.extraction
    return {
        "status": proposal.status.value,
        "confidence": _num(proposal.confidence),
        "margin": _num(proposal.margin),
        "candidates": [_candidate(i, c) for i, c in enumerate(proposal.candidates, start=1)],
        "flags": [{"rule_id": f.rule_id, "severity": f.severity.value, "message": f.message} for f in proposal.flags],
        "extraction": None
        if extraction is None
        else extraction.model_dump(mode="json", include={"ingredients", "dosage_form", "base", "route"}),
    }


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def explain_input(proposal: Proposal) -> str:
    """Canonical JSON of the facts, escaped so no quoted prescription text can close or open a tag."""
    body = json.dumps(facts(proposal), ensure_ascii=False, sort_keys=True, indent=1)
    return f"<facts>\n{_escape(body)}\n</facts>"


# --- citations ---------------------------------------------------------------------------------


def required_citations(proposal: Proposal) -> list[str]:
    """Top candidate's formula ID and `name=value` per component, then each flag's rule ID once."""
    required: list[str] = []
    if proposal.candidates:
        top = _candidate(1, proposal.candidates[0])
        required.append(top["formula_id"])
        required += [f"{k}={v}" for k, v in top["component_scores"].items()]
    for flag in proposal.flags:
        if flag.rule_id not in required:
            required.append(flag.rule_id)
    return required


def missing_citations(reasons: str, proposal: Proposal) -> list[str]:
    return [item for item in required_citations(proposal) if item not in reasons]


_STATUS_TEXT = {
    ProposalStatus.PROPOSED: "a formula is proposed for pharmacist review",
    ProposalStatus.NO_MATCH: "no formula scored above the match threshold",
    ProposalStatus.MANUAL: "extraction failed, so the prescription needs manual entry",
}


def fallback_reasons(proposal: Proposal) -> str:
    """Deterministic reasons from the same facts; always cites everything `required_citations` asks for."""
    f = facts(proposal)
    status = f"Status {f['status']}: {_STATUS_TEXT[proposal.status]}"
    parts = [f"{status} (confidence {f['confidence']}, margin {f['margin']})."]
    if f["candidates"]:
        top = f["candidates"][0]
        scores = ", ".join(f"{k}={v}" for k, v in top["component_scores"].items())
        parts.append(f"Top candidate {top['formula_id']} scored {top['score']}: {scores}.")
    if not proposal.flags:
        parts.append("No flags fired.")
    for flag in proposal.flags:
        effect = "CONFIRM is disabled" if flag.severity is Severity.BLOCK else "acknowledge before CONFIRM"
        parts.append(f"{flag.rule_id} ({flag.severity.value}, {effect}): {flag.message}")
    return " ".join(parts)


# --- explain -----------------------------------------------------------------------------------


def _reply_text(response: dict[str, Any]) -> str:
    blocks = response.get("content") or []
    return "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


def explain(proposal: Proposal, *, client: CompletionClient, prompt: Prompt | None = None) -> Explanation:
    """One model call, plain text only. A missing REPLAY recording propagates (never a fallback)."""
    prompt = prompt or load_prompt()
    response = client.complete(
        prompt_hash=prompt.sha256, system=prompt.text, user_input=explain_input(proposal), tools=None
    )
    reasons = _reply_text(response)
    missing = missing_citations(reasons, proposal)
    source = ExplainSource.MODEL
    if missing:
        reasons, source = fallback_reasons(proposal), ExplainSource.FALLBACK
    return Explanation(
        reasons=reasons,
        source=source,
        missing=missing,
        prompt_versions={prompt.name: prompt.sha256},
        model_id=client.config.model_id,
    )


def with_reasons(proposal: Proposal, explanation: Explanation) -> Proposal:
    """A new Proposal with the reasons set; every other field is re-validated from the input unchanged."""
    foreign = [k for k in explanation.prompt_versions if not k.startswith(PROMPT_PREFIX)]
    if foreign:
        raise ValueError(f"an explanation may only record explain prompts, got {foreign}")
    data = proposal.model_dump()
    data["reasons"] = explanation.reasons
    data["prompt_versions"] = {**proposal.prompt_versions, **explanation.prompt_versions}
    return Proposal.model_validate(data)


def add_reasons(proposal: Proposal, *, client: CompletionClient) -> Proposal:
    return with_reasons(proposal, explain(proposal, client=client))
