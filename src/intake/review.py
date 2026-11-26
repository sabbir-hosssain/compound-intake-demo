"""Pharmacist review (SPEC §9): the only code path that writes a ReviewAction to the audit log.

The Streamlit screen (app/review.py) is a thin shell over this module so every rule here is
testable without Streamlit:

- BLOCK disables CONFIRM, and no acknowledgment can lift it (invariant 3).
- Every REVIEW flag must be acknowledged, by rule ID, before CONFIRM.
- CONFIRM, CORRECT and CLARIFY each need a reason code from their own set, and a named reviewer.
- One proposal per call; `action`, `reason_code`, `reviewer` and `acknowledged` have no defaults,
  so there is no bulk action and no auto-confirm.

Flags are only read here, never changed (invariant 2). A review appends a new record that repeats
the pending proposal with the ReviewAction attached; the pending record itself is never touched.
"""

import hashlib
from collections.abc import Collection, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from pydantic import BaseModel, ConfigDict

from intake import audit
from intake.models import (
    AuditRecord,
    Extraction,
    Flag,
    Formula,
    Proposal,
    ProposalStatus,
    ReviewAction,
    ReviewActionType,
    Severity,
)
from intake.pipeline import GENESIS_HASH, chain_hash
from intake.rules import normalise_name


class ReviewError(ValueError):
    """The requested review action is not allowed; nothing was written."""


class ReasonCode(StrEnum):
    # CONFIRM
    MATCH_VERIFIED = "MATCH_VERIFIED"
    VERIFIED_WITH_PRESCRIBER = "VERIFIED_WITH_PRESCRIBER"
    # CORRECT
    WRONG_CANDIDATE = "WRONG_CANDIDATE"
    EXTRACTION_ERROR = "EXTRACTION_ERROR"
    PRESCRIBER_CONFIRMED_CHANGE = "PRESCRIBER_CONFIRMED_CHANGE"
    # CLARIFY
    MISSING_INFORMATION = "MISSING_INFORMATION"
    AMBIGUOUS_ORDER = "AMBIGUOUS_ORDER"
    SAFETY_CONCERN = "SAFETY_CONCERN"
    NOT_IN_LIBRARY = "NOT_IN_LIBRARY"


REASON_CODES: dict[ReviewActionType, frozenset[ReasonCode]] = {
    ReviewActionType.CONFIRM: frozenset({ReasonCode.MATCH_VERIFIED, ReasonCode.VERIFIED_WITH_PRESCRIBER}),
    ReviewActionType.CORRECT: frozenset(
        {ReasonCode.WRONG_CANDIDATE, ReasonCode.EXTRACTION_ERROR, ReasonCode.PRESCRIBER_CONFIRMED_CHANGE}
    ),
    ReviewActionType.CLARIFY: frozenset(
        {
            ReasonCode.MISSING_INFORMATION,
            ReasonCode.AMBIGUOUS_ORDER,
            ReasonCode.SAFETY_CONCERN,
            ReasonCode.NOT_IN_LIBRARY,
        }
    ),
}

EXTRACTION_FIELDS = frozenset(Extraction.model_fields)


# --- flags ---------------------------------------------------------------------------------------


def ordered_flags(proposal: Proposal) -> list[Flag]:
    """BLOCK first, otherwise in proposal order."""
    return sorted(proposal.flags, key=lambda f: f.severity is not Severity.BLOCK)


def review_flag_ids(proposal: Proposal) -> list[str]:
    """Rule IDs of the REVIEW flags that need acknowledging, in order, without repeats."""
    return list(dict.fromkeys(f.rule_id for f in proposal.flags if f.severity is Severity.REVIEW))


def confirm_blockers(proposal: Proposal, acknowledged: Collection[str]) -> list[str]:
    """Why CONFIRM is disabled; an empty list means CONFIRM is enabled."""
    blockers: list[str] = []
    blocks = [f.rule_id for f in proposal.flags if f.severity is Severity.BLOCK]
    if blocks:
        blockers.append(f"BLOCK flag present ({', '.join(blocks)}): use CORRECT or CLARIFY.")
    if proposal.status is not ProposalStatus.PROPOSED or not proposal.candidates:
        blockers.append(f"Status is {proposal.status.value}, not PROPOSED: there is no match to confirm.")
    missing = [rule_id for rule_id in review_flag_ids(proposal) if rule_id not in acknowledged]
    if missing:
        blockers.append(f"REVIEW flag not acknowledged: {', '.join(missing)}.")
    return blockers


def can_confirm(proposal: Proposal, acknowledged: Collection[str]) -> bool:
    return not confirm_blockers(proposal, acknowledged)


# --- building an action --------------------------------------------------------------------------


def _check_reason(action: ReviewActionType, reason_code: str | None) -> ReasonCode:
    allowed = REASON_CODES[action]
    if not reason_code or reason_code not in {code.value for code in allowed}:
        options = ", ".join(sorted(code.value for code in allowed))
        raise ReviewError(f"{action.value} needs a reason code, one of: {options}.")
    return ReasonCode(reason_code)


def _check_confirm(proposal: Proposal, acknowledged: Collection[str], chosen: str | None) -> str:
    blockers = confirm_blockers(proposal, acknowledged)
    if blockers:
        raise ReviewError("CONFIRM is disabled: " + " ".join(blockers))
    top = proposal.candidates[0].formula_id
    if chosen is not None and chosen != top:
        raise ReviewError(f"CONFIRM accepts the top candidate {top} only; use CORRECT to choose {chosen}.")
    return top


def _check_correct(chosen: str | None, fields: Mapping[str, Any], known: Collection[str] | None) -> None:
    if chosen is None and not fields:
        raise ReviewError("CORRECT needs a chosen formula or at least one corrected field.")
    if chosen is not None and known is not None and chosen not in known:
        raise ReviewError(f"{chosen} is not in the formula library.")
    unknown = sorted(set(fields) - EXTRACTION_FIELDS)
    if unknown:
        raise ReviewError(f"Unknown corrected field(s): {', '.join(unknown)}.")


def build_action(
    proposal: Proposal,
    *,
    action: ReviewActionType,
    reason_code: str | None,
    reviewer: str,
    acknowledged: Collection[str],
    chosen_formula_id: str | None = None,
    corrected_fields: Mapping[str, Any] | None = None,
    known_formula_ids: Collection[str] | None = None,
    at: datetime | None = None,
) -> ReviewAction:
    """Validate one reviewer decision on one proposal and return its ReviewAction. Raises ReviewError."""
    action = ReviewActionType(action)
    reason = _check_reason(action, reason_code)
    if not reviewer or not reviewer.strip():
        raise ReviewError("A named reviewer is required.")
    fields = dict(corrected_fields or {})
    if action is ReviewActionType.CONFIRM:
        if fields:
            raise ReviewError("CONFIRM takes no corrected fields; use CORRECT.")
        chosen_formula_id = _check_confirm(proposal, acknowledged, chosen_formula_id)
    elif action is ReviewActionType.CORRECT:
        _check_correct(chosen_formula_id, fields, known_formula_ids)
    elif chosen_formula_id is not None or fields:
        raise ReviewError("CLARIFY takes no formula and no corrected fields.")
    return ReviewAction(
        action=action,
        chosen_formula_id=chosen_formula_id,
        corrected_fields=fields,
        reason_code=reason.value,
        reviewer=reviewer.strip(),
        at=at or datetime.now(UTC),
    )


# --- queue and audit -----------------------------------------------------------------------------


def _same_case(a: AuditRecord, b: AuditRecord) -> bool:
    return a.input_hash == b.input_hash and a.proposal == b.proposal


def pending_queue(records: Sequence[AuditRecord]) -> list[AuditRecord]:
    """Pending records (no ReviewAction) that no later record has reviewed, in seq order."""
    reviewed = [r for r in records if r.review_action is not None]
    return [
        r
        for r in records
        if r.review_action is None and not any(d.seq > r.seq and _same_case(r, d) for d in reviewed)
    ]


def _check_pending(records: Sequence[AuditRecord], pending: AuditRecord) -> None:
    if pending.review_action is not None:
        raise ReviewError(f"seq {pending.seq} is a review record, not a pending one.")
    if not any(r == pending for r in records):
        raise ReviewError(f"seq {pending.seq} is not in the audit log as given.")
    if pending not in pending_queue(records):
        raise ReviewError(f"seq {pending.seq} is already reviewed.")


def submit(
    conn: Connection,
    pending: AuditRecord,
    *,
    action: ReviewActionType,
    reason_code: str | None,
    reviewer: str,
    acknowledged: Collection[str],
    chosen_formula_id: str | None = None,
    corrected_fields: Mapping[str, Any] | None = None,
    known_formula_ids: Collection[str] | None = None,
    at: datetime | None = None,
) -> AuditRecord:
    """Validate one decision on one pending record and append it as a new chained record."""
    records = audit.read_all(conn)
    _check_pending(records, pending)
    review_action = build_action(
        pending.proposal,
        action=action,
        reason_code=reason_code,
        reviewer=reviewer,
        acknowledged=acknowledged,
        chosen_formula_id=chosen_formula_id,
        corrected_fields=corrected_fields,
        known_formula_ids=known_formula_ids,
        at=at,
    )
    prev_hash = records[-1].record_hash if records else GENESIS_HASH
    unsigned = AuditRecord(
        seq=audit.next_seq(conn),
        prev_hash=prev_hash,
        record_hash="",
        input_hash=pending.input_hash,
        proposal=pending.proposal,
        review_action=review_action,
        at=review_action.at,
    )
    record = unsigned.model_copy(update={"record_hash": chain_hash(prev_hash, unsigned)})
    audit.append(conn, record)
    return record


# --- display helpers -----------------------------------------------------------------------------


class DiffRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    prescribed: str
    formula: str
    same: bool


def _text(value: object) -> str:
    return "—" if value is None or value == "" else str(value)


def _norm(value: object) -> str:
    return normalise_name(str(value)) if value is not None else ""


def _strength(strength: float | None, unit: object) -> str:
    if strength is None:
        return "—"
    return f"{strength:g} {getattr(unit, 'value', unit) or ''}".strip()


def formula_diff(extraction: Extraction | None, formula: Formula, aliases: Mapping[str, str]) -> list[DiffRow]:
    """Side-by-side rows: prescribed (extracted) vs the formula, for form, base, route and each ingredient."""
    ext = extraction or Extraction()
    rows = [
        DiffRow(
            field=name,
            prescribed=_text(getattr(ext, name)),
            formula=_text(getattr(formula, name)),
            same=extraction is not None and _norm(getattr(ext, name)) == _norm(getattr(formula, name)),
        )
        for name in ("dosage_form", "base", "route")
    ]

    def canonical(name: str) -> str:
        key = normalise_name(name)
        return aliases.get(key, key)

    prescribed = {canonical(i.name): _strength(i.strength, i.unit) for i in ext.ingredients}
    in_formula = {canonical(i.name): _strength(i.strength, i.unit) for i in formula.ingredients}
    for name in [*in_formula, *(n for n in prescribed if n not in in_formula)]:
        left, right = prescribed.get(name, "—"), in_formula.get(name, "—")
        rows.append(DiffRow(field=f"ingredient: {name}", prescribed=left, formula=right, same=left == right != "—"))
    return rows


def find_raw_text(prescription_id: str, input_hash: str, directories: Iterable[Path]) -> str | None:
    """The raw text `<dir>/<prescription_id>.txt`, only if its sha256 equals the record's input_hash."""
    if Path(prescription_id).name != prescription_id:
        return None
    for directory in directories:
        path = Path(directory) / f"{prescription_id}.txt"
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() == input_hash:
            return text
    return None
