"""Pharmacist review screen (SPEC §9). Run: `uv run streamlit run app/review.py`.

A thin shell over `intake.review`: every rule (BLOCK disables CONFIRM, REVIEW flags need an
acknowledgment, reason codes are required) is enforced there, and the screen only mirrors it.
One proposal at a time; the only write is a single `review.submit` call behind a button.
There is no bulk action and no auto-confirm.

Environment: INTAKE_AUDIT_DB overrides the audit DB from config.toml; INTAKE_RAW_DIR adds a folder
to search for `<prescription_id>.txt` raw text (samples/ is always searched).
Synthetic demo data only; formulas are fictional and illustrative.
"""

import os
from pathlib import Path

import streamlit as st

from intake import audit, review
from intake.library import load_alias_map, load_formulas
from intake.match import tied_with
from intake.models import AuditRecord, Proposal, ReviewActionType, Severity

REPO_ROOT = Path(__file__).resolve().parents[1]
ACTIONS = (ReviewActionType.CONFIRM, ReviewActionType.CORRECT, ReviewActionType.CLARIFY)


def _db_path() -> Path:
    override = os.environ.get("INTAKE_AUDIT_DB")
    return Path(override) if override else audit.db_path()


def _raw_dirs() -> list[Path]:
    extra = os.environ.get("INTAKE_RAW_DIR")
    return [REPO_ROOT / "samples", *([Path(extra)] if extra else [])]


def _load_queue() -> list[AuditRecord]:
    conn = audit.connect(_db_path())
    try:
        return review.pending_queue(audit.read_all(conn))
    finally:
        conn.close()


def _show_flags(proposal: Proposal, seq: int) -> set[str]:
    """Flags, BLOCK first. Returns the REVIEW rule IDs the reviewer has acknowledged."""
    st.subheader("Flags")
    if not proposal.flags:
        st.write("No flags.")
    for flag in review.ordered_flags(proposal):
        text = f"**{flag.severity.value}** · {flag.rule_id} (pass {flag.source_pass}): {flag.message}"
        (st.error if flag.severity is Severity.BLOCK else st.warning)(text)
    acknowledged: set[str] = set()
    for rule_id in review.review_flag_ids(proposal):
        if st.checkbox(f"I have checked REVIEW flag {rule_id}", key=f"ack-{seq}-{rule_id}"):
            acknowledged.add(rule_id)
    return acknowledged


def _show_candidates(proposal: Proposal) -> None:
    st.subheader("Top candidates")
    if not proposal.candidates:
        st.write("No candidates.")
        return
    rows = [
        {"rank": rank, "formula": c.formula_id, "version": c.formula_version, "score": round(c.score, 3)}
        | {k: round(v, 3) for k, v in c.component_scores.items()}
        for rank, c in enumerate(proposal.candidates, start=1)
    ]
    tie = tied_with(proposal.candidates)
    if tie:
        st.warning(f"{proposal.candidates[0].formula_id} is tied with {tie} (equal scores; ranked by formula ID).")
    st.table(rows)


def _show_diff(proposal: Proposal, formulas: dict, aliases: dict[str, str]) -> None:
    if not proposal.candidates:
        return
    options = [c.formula_id for c in proposal.candidates if c.formula_id in formulas]
    if not options:
        return
    chosen = st.selectbox("Compare against", options, key=f"diff-{proposal.prescription_id}")
    st.subheader(f"Prescribed vs {chosen} (illustrative formula)")
    rows = review.formula_diff(proposal.extraction, formulas[chosen], aliases)
    st.table([{"field": r.field, "prescribed": r.prescribed, chosen: r.formula, "": "" if r.same else "≠"} for r in rows])


def _show_proposal(record: AuditRecord) -> None:
    proposal = record.proposal
    st.header(f"Prescription {proposal.prescription_id}")
    st.caption(
        f"Audit seq {record.seq} · status {proposal.status.value} · confidence {proposal.confidence:.3f} · "
        f"margin {proposal.margin:.3f} · model {proposal.model_id} · rules {proposal.rules_version} · "
        f"library {proposal.library_version}"
    )
    st.subheader("Raw text")
    raw = review.find_raw_text(proposal.prescription_id, record.input_hash, _raw_dirs())
    st.code(raw if raw is not None else "(raw text not found for this input hash)", language=None)
    st.subheader("Extracted fields")
    st.json(proposal.extraction.model_dump(mode="json") if proposal.extraction else {"extraction": None})
    st.subheader("Reasons")
    st.caption("Model-written explanation of the scores and flags; it cannot change them.")
    st.markdown(review.reasons_text(proposal))


def _action_inputs(record: AuditRecord, formula_ids: list[str], acknowledged: set[str]) -> ReviewActionType | None:
    """Reason pickers and one button per action. Returns the action whose button was clicked."""
    seq, proposal = record.seq, record.proposal
    blockers = review.confirm_blockers(proposal, acknowledged)
    for blocker in blockers:
        st.info(f"CONFIRM disabled: {blocker}")
    clicked: ReviewActionType | None = None
    for column, action in zip(st.columns(len(ACTIONS)), ACTIONS, strict=True):
        with column:
            codes = sorted(code.value for code in review.REASON_CODES[action])
            st.selectbox(f"{action.value} reason", codes, index=None, key=f"reason-{seq}-{action.value}")
            if action is ReviewActionType.CORRECT:
                st.selectbox("Correct formula", formula_ids, index=None, key=f"correct-formula-{seq}")
                st.selectbox("Correct field", sorted(review.EXTRACTION_FIELDS), index=None, key=f"field-{seq}")
                st.text_input("Corrected value", key=f"value-{seq}")
            disabled = action is ReviewActionType.CONFIRM and bool(blockers)
            if st.button(action.value, key=f"btn-{seq}-{action.value}", disabled=disabled):
                clicked = action
    return clicked


def _corrected_fields(seq: int) -> dict[str, str]:
    field, value = st.session_state.get(f"field-{seq}"), st.session_state.get(f"value-{seq}", "")
    return {field: value} if field and value.strip() else {}


def main() -> None:
    st.set_page_config(page_title="Compound intake review", layout="wide")
    st.title("Compound intake review")
    st.caption("Synthetic demo · SH Compounding Network · formulas are fictional and illustrative.")
    if message := st.session_state.pop("last_written", None):
        st.success(message)
    queue = _load_queue()
    if not queue:
        st.info("No proposals are waiting for review.")
        return
    labels = {r.seq: f"seq {r.seq} · {r.proposal.prescription_id} · {r.proposal.status.value}" for r in queue}
    seq = st.sidebar.radio("Queue", list(labels), format_func=labels.get, key="queue")
    record = next(r for r in queue if r.seq == seq)
    formulas = {f.formula_id: f for f in load_formulas()}
    aliases = load_alias_map()

    _show_proposal(record)
    acknowledged = _show_flags(record.proposal, record.seq)
    _show_candidates(record.proposal)
    _show_diff(record.proposal, formulas, aliases)

    st.subheader("Decision")
    reviewer = st.text_input("Reviewer", key="reviewer")
    clicked = _action_inputs(record, sorted(formulas), acknowledged)
    if clicked is None:
        return
    conn = audit.connect(_db_path())
    try:
        written = review.submit(
            conn,
            record,
            action=clicked,
            reason_code=st.session_state.get(f"reason-{seq}-{clicked.value}"),
            reviewer=reviewer,
            acknowledged=frozenset(acknowledged),
            chosen_formula_id=st.session_state.get(f"correct-formula-{seq}") if clicked.value == "CORRECT" else None,
            corrected_fields=_corrected_fields(seq) if clicked.value == "CORRECT" else None,
            known_formula_ids=frozenset(formulas),
        )
    except review.ReviewError as error:
        st.error(f"Not written: {error}")
        return
    finally:
        conn.close()
    st.session_state["last_written"] = f"{clicked.value} written as audit seq {written.seq}."
    st.rerun()


main()
