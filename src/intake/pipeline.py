"""Intake pipeline (SPEC §3): raw text -> pass-1 flags -> extraction -> pass-2 flags -> match -> Proposal.

The proposal is logged to the audit as a PENDING record (`review_action = None`). Nothing here takes
or creates a ReviewAction: only a pharmacist's review (S3.1) commits a decision (ADR-0001).
Flags flow through every step as `[*existing, *new]`, so no step can drop one (invariant 2).

Records are hash-linked with `intake.audit.chain_hash` (SPEC §10); `intake audit verify` checks them.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from intake import audit
from intake.audit import GENESIS_HASH, chain_hash
from intake.extract import CompletionClient, ExtractStatus, extract
from intake.library import library_version, load_alias_map, load_formulas
from intake.match import Thresholds, load_thresholds, match
from intake.models import AuditRecord, Formula, Proposal, ProposalStatus, Severity
from intake.rules import (
    RULES_VERSION,
    IngredientLimit,
    load_ingredient_limits,
    load_ingredient_names,
    run_pass1,
    run_pass2,
)


class Library(BaseModel):
    """Everything deterministic the pipeline scores against."""

    model_config = ConfigDict(frozen=True)

    formulas: list[Formula]
    aliases: dict[str, str]
    known_ingredients: frozenset[str]
    ingredient_limits: dict[str, IngredientLimit]
    thresholds: Thresholds
    version: str


def load_library() -> Library:
    return Library(
        formulas=load_formulas(),
        aliases=load_alias_map(),
        known_ingredients=load_ingredient_names(),
        ingredient_limits=load_ingredient_limits(),
        thresholds=load_thresholds(),
        version=library_version(),
    )


def build_proposal(
    text: str,
    prescription_id: str,
    *,
    client: CompletionClient,
    library: Library | None = None,
    now: datetime | None = None,
) -> Proposal:
    """Run the pipeline on raw text. A failed extraction gives status MANUAL with the pass-1 flags kept."""
    library = library or load_library()
    flags = run_pass1(text, known=library.known_ingredients)
    result = extract(text, client=client)
    common = {
        "prescription_id": prescription_id,
        "model_id": result.model_id,
        "prompt_versions": result.prompt_versions,
        "rules_version": RULES_VERSION,
        "library_version": library.version,
        "created_at": now or datetime.now(UTC),
    }
    if result.status is ExtractStatus.MANUAL or result.extraction is None:
        return Proposal(confidence=0.0, margin=0.0, status=ProposalStatus.MANUAL, flags=flags, **common)
    flags = run_pass2(
        result.extraction,
        library.known_ingredients,
        flags,
        formulas=library.formulas,
        aliases=library.aliases,
        limits=library.ingredient_limits,
    )
    matched = match(result.extraction, library.formulas, library.thresholds, library.aliases, existing=flags)
    return Proposal(
        extraction=result.extraction,
        candidates=matched.candidates,
        confidence=matched.confidence,
        margin=matched.margin,
        status=matched.status,
        flags=matched.flags,
        **common,
    )


# --- audit (pending only) ----------------------------------------------------------------------


def pending_record(proposal: Proposal, text: str, *, seq: int, prev_hash: str) -> AuditRecord:
    """An audit record for a proposal awaiting review. It never carries a ReviewAction."""
    unsigned = AuditRecord(
        seq=seq,
        prev_hash=prev_hash,
        record_hash="",
        input_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        proposal=proposal,
        review_action=None,
        at=datetime.now(UTC),
    )
    return unsigned.model_copy(update={"record_hash": chain_hash(prev_hash, unsigned)})


def log_pending(proposal: Proposal, text: str, audit_db: Path | None = None) -> AuditRecord:
    """Append the proposal to the audit log as pending and return the stored record."""
    conn = audit.connect(audit_db)
    try:
        existing = audit.read_all(conn)
        prev_hash = existing[-1].record_hash if existing else GENESIS_HASH
        record = pending_record(proposal, text, seq=audit.next_seq(conn), prev_hash=prev_hash)
        audit.append(conn, record)
        return record
    finally:
        conn.close()


def run_file(
    path: Path, *, client: CompletionClient, audit_db: Path | None = None, library: Library | None = None
) -> tuple[Proposal, AuditRecord]:
    """Read a prescription file, build its proposal and log it as pending. ID = file stem."""
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    proposal = build_proposal(text, Path(path).stem, client=client, library=library)
    return proposal, log_pending(proposal, text, audit_db)


# --- display -----------------------------------------------------------------------------------


def _flag_lines(proposal: Proposal) -> list[str]:
    if not proposal.flags:
        return ["  (none)"]
    ordered = sorted(proposal.flags, key=lambda f: f.severity is not Severity.BLOCK)  # stable: BLOCK first
    return [f"  [{f.severity.value}] {f.rule_id} (pass {f.source_pass}): {f.message}" for f in ordered]


def _candidate_lines(proposal: Proposal) -> list[str]:
    if not proposal.candidates:
        return ["  (none)"]
    lines = []
    for rank, cand in enumerate(proposal.candidates, start=1):
        parts = ", ".join(f"{k} {v:.2f}" for k, v in cand.component_scores.items())
        lines.append(f"  {rank}. {cand.formula_id} v{cand.formula_version}  score {cand.score:.3f}  ({parts})")
    return lines


def format_proposal(proposal: Proposal) -> str:
    lines = [
        f"Prescription: {proposal.prescription_id}",
        f"Status:       {proposal.status.value}",
        f"Confidence:   {proposal.confidence:.3f}",
        f"Margin:       {proposal.margin:.3f}",
        "Candidates:",
        *_candidate_lines(proposal),
        "Flags:",
        *_flag_lines(proposal),
    ]
    if any(f.severity is Severity.BLOCK for f in proposal.flags):
        lines.append("CONFIRM disabled: a BLOCK flag is present.")
    lines.append(
        f"Versions:     model {proposal.model_id} · rules {proposal.rules_version} · library {proposal.library_version}"
    )
    return "\n".join(lines)
