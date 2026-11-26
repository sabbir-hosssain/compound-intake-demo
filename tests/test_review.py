"""S3.1 review: action logic (src/intake/review.py) and the Streamlit screen (app/review.py).

AC: BLOCK disables CONFIRM · REVIEW needs an explicit acknowledgment before CONFIRM ·
CONFIRM / CORRECT / CLARIFY write ReviewActions with required reason codes · no bulk action, no auto-confirm.
"""

import ast
import hashlib
import inspect
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intake import audit, review
from intake.models import (
    AuditRecord,
    Extraction,
    Flag,
    Ingredient,
    MatchCandidate,
    Proposal,
    ProposalStatus,
    ReviewActionType,
    Severity,
    Unit,
)
from intake.pipeline import GENESIS_HASH, chain_hash, pending_record
from intake.review import ReasonCode, ReviewError

REPO = Path(__file__).resolve().parents[1]
REVIEW_SRC = REPO / "src" / "intake" / "review.py"
APP_SRC = REPO / "app" / "review.py"
AT = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
TEXT = "Salicylic acid 3% / urea 10% in vanishing cream base, topical, 30 g. Dr Placeholder. Pt ref P-1."

BLOCK = Flag(rule_id="R1-04", rule_version="0.1.0", severity=Severity.BLOCK, message="Controlled term.", source_pass=1)
REVIEW_A = Flag(rule_id="R1-03", rule_version="0.1.0", severity=Severity.REVIEW, message="Prior order.", source_pass=1)
REVIEW_B = Flag(rule_id="M-01", rule_version="0.1.0", severity=Severity.REVIEW, message="Close call.", source_pass=2)
KNOWN = frozenset({"SHF-001", "SHF-002", "SHF-007"})


def _proposal(
    flags: list[Flag] | None = None, status: ProposalStatus = ProposalStatus.PROPOSED, pid: str = "rx-001"
) -> Proposal:
    candidates = [
        MatchCandidate(formula_id="SHF-001", formula_version="1.0", score=0.9, component_scores={"ingredients": 1.0}),
        MatchCandidate(formula_id="SHF-007", formula_version="1.0", score=0.7, component_scores={"ingredients": 0.5}),
    ]
    extraction = Extraction(
        ingredients=[
            Ingredient(name="salicylic acid", strength=3.0, unit=Unit.PERCENT),
            Ingredient(name="urea", strength=12.0, unit=Unit.PERCENT),
        ],
        dosage_form="cream",
        base="vanishing cream base",
        route="topical",
    )
    return Proposal(
        prescription_id=pid,
        extraction=extraction,
        candidates=candidates,
        confidence=0.9,
        margin=0.2,
        status=status,
        flags=flags or [],
        model_id="claude-test-model",
        rules_version="0.1.0",
        library_version="abc123",
        created_at=AT,
    )


def _act(proposal: Proposal, **overrides: object):
    kwargs: dict[str, object] = {
        "action": ReviewActionType.CONFIRM,
        "reason_code": ReasonCode.MATCH_VERIFIED,
        "reviewer": "pharmacist-1",
        "acknowledged": frozenset(),
        "known_formula_ids": KNOWN,
        "at": AT,
    }
    kwargs.update(overrides)
    return review.build_action(proposal, **kwargs)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = audit.connect(tmp_path / "audit.sqlite")
    yield c
    c.close()


def _log_pending(conn: sqlite3.Connection, proposal: Proposal, text: str = TEXT) -> AuditRecord:
    records = audit.read_all(conn)
    prev = records[-1].record_hash if records else GENESIS_HASH
    record = pending_record(proposal, text, seq=audit.next_seq(conn), prev_hash=prev)
    audit.append(conn, record)
    return record


# --- AC1: BLOCK disables CONFIRM -----------------------------------------------------------------


def test_block_flag_disables_confirm() -> None:
    proposal = _proposal([BLOCK])
    assert not review.can_confirm(proposal, acknowledged=frozenset())
    assert any("BLOCK" in reason for reason in review.confirm_blockers(proposal, frozenset()))
    with pytest.raises(ReviewError, match="BLOCK"):
        _act(proposal)


def test_block_cannot_be_acknowledged_away() -> None:
    proposal = _proposal([BLOCK, REVIEW_A])
    every_id = frozenset({BLOCK.rule_id, REVIEW_A.rule_id})
    assert not review.can_confirm(proposal, acknowledged=every_id)
    with pytest.raises(ReviewError, match="BLOCK"):
        _act(proposal, acknowledged=every_id)


def test_block_still_allows_correct_and_clarify() -> None:
    proposal = _proposal([BLOCK])
    clarify = _act(proposal, action=ReviewActionType.CLARIFY, reason_code=ReasonCode.SAFETY_CONCERN)
    correct = _act(
        proposal, action=ReviewActionType.CORRECT, reason_code=ReasonCode.WRONG_CANDIDATE, chosen_formula_id="SHF-002"
    )
    assert clarify.action is ReviewActionType.CLARIFY
    assert correct.action is ReviewActionType.CORRECT


def test_no_flags_confirm_is_allowed() -> None:
    proposal = _proposal()
    assert review.can_confirm(proposal, acknowledged=frozenset())
    assert review.confirm_blockers(proposal, frozenset()) == []


# --- AC2: REVIEW needs explicit acknowledgment before CONFIRM ------------------------------------


def test_review_flag_without_ack_disables_confirm() -> None:
    proposal = _proposal([REVIEW_A])
    assert not review.can_confirm(proposal, acknowledged=frozenset())
    with pytest.raises(ReviewError, match="acknowledg"):
        _act(proposal)


def test_every_review_flag_must_be_acknowledged() -> None:
    proposal = _proposal([REVIEW_A, REVIEW_B])
    assert not review.can_confirm(proposal, acknowledged=frozenset({REVIEW_A.rule_id}))
    with pytest.raises(ReviewError, match=REVIEW_B.rule_id):
        _act(proposal, acknowledged=frozenset({REVIEW_A.rule_id}))
    both = frozenset({REVIEW_A.rule_id, REVIEW_B.rule_id})
    assert review.can_confirm(proposal, acknowledged=both)
    assert _act(proposal, acknowledged=both).action is ReviewActionType.CONFIRM


def test_acknowledging_an_absent_flag_does_not_help() -> None:
    proposal = _proposal([REVIEW_A])
    assert not review.can_confirm(proposal, acknowledged=frozenset({"R9-99"}))


def test_confirm_requires_a_proposed_status() -> None:
    for status in (ProposalStatus.NO_MATCH, ProposalStatus.MANUAL):
        proposal = _proposal(status=status)
        assert not review.can_confirm(proposal, acknowledged=frozenset())
        with pytest.raises(ReviewError, match="PROPOSED"):
            _act(proposal)


def test_confirm_is_the_top_candidate_only() -> None:
    proposal = _proposal()
    assert _act(proposal).chosen_formula_id == "SHF-001"
    with pytest.raises(ReviewError, match="CORRECT"):
        _act(proposal, chosen_formula_id="SHF-007")


# --- AC3: actions write ReviewActions with required reason codes ---------------------------------


@pytest.mark.parametrize("action", list(ReviewActionType))
def test_every_action_type_has_reason_codes(action: ReviewActionType) -> None:
    assert review.REASON_CODES[action], f"{action} has no reason codes"


@pytest.mark.parametrize("action", list(ReviewActionType))
def test_reason_code_is_required(action: ReviewActionType) -> None:
    for missing in (None, ""):
        with pytest.raises(ReviewError, match="reason"):
            _act(_proposal(), action=action, reason_code=missing, chosen_formula_id="SHF-002")


def test_reason_code_must_belong_to_the_action() -> None:
    with pytest.raises(ReviewError, match="reason"):
        _act(_proposal(), action=ReviewActionType.CONFIRM, reason_code=ReasonCode.SAFETY_CONCERN)
    with pytest.raises(ReviewError, match="reason"):
        _act(_proposal(), reason_code="MADE_UP")


def test_reason_code_sets_do_not_overlap() -> None:
    sets = list(review.REASON_CODES.values())
    assert sum(len(s) for s in sets) == len(set().union(*sets))


def test_reviewer_is_required() -> None:
    for blank in ("", "   "):
        with pytest.raises(ReviewError, match="reviewer"):
            _act(_proposal(), reviewer=blank)


def test_confirm_action_fields() -> None:
    action = _act(_proposal())
    assert action.action is ReviewActionType.CONFIRM
    assert action.reason_code == ReasonCode.MATCH_VERIFIED.value
    assert action.reviewer == "pharmacist-1"
    assert action.corrected_fields == {}
    assert action.at == AT


def test_correct_needs_a_formula_or_corrected_fields() -> None:
    kwargs = {"action": ReviewActionType.CORRECT, "reason_code": ReasonCode.EXTRACTION_ERROR}
    with pytest.raises(ReviewError, match="CORRECT"):
        _act(_proposal(), **kwargs)
    fixed = _act(_proposal(), corrected_fields={"route": "topical"}, **kwargs)
    assert fixed.corrected_fields == {"route": "topical"}
    assert fixed.chosen_formula_id is None


def test_correct_formula_must_be_in_the_library() -> None:
    with pytest.raises(ReviewError, match="library"):
        _act(
            _proposal(),
            action=ReviewActionType.CORRECT,
            reason_code=ReasonCode.WRONG_CANDIDATE,
            chosen_formula_id="SHF-999",
        )


def test_corrected_fields_must_be_extraction_fields() -> None:
    with pytest.raises(ReviewError, match="field"):
        _act(
            _proposal(),
            action=ReviewActionType.CORRECT,
            reason_code=ReasonCode.EXTRACTION_ERROR,
            corrected_fields={"confidence": 1.0},
        )


def test_clarify_carries_no_formula_or_fields() -> None:
    action = _act(_proposal(), action=ReviewActionType.CLARIFY, reason_code=ReasonCode.MISSING_INFORMATION)
    assert action.chosen_formula_id is None and action.corrected_fields == {}
    with pytest.raises(ReviewError, match="CLARIFY"):
        _act(
            _proposal(),
            action=ReviewActionType.CLARIFY,
            reason_code=ReasonCode.MISSING_INFORMATION,
            chosen_formula_id="SHF-001",
        )


def test_submit_appends_a_chained_review_record(conn: sqlite3.Connection) -> None:
    pending = _log_pending(conn, _proposal([REVIEW_A]))
    record = review.submit(
        conn,
        pending,
        action=ReviewActionType.CONFIRM,
        reason_code=ReasonCode.MATCH_VERIFIED,
        reviewer="pharmacist-1",
        acknowledged=frozenset({REVIEW_A.rule_id}),
        known_formula_ids=KNOWN,
        at=AT,
    )
    stored = audit.read_all(conn)
    assert stored[-1] == record and record.seq == pending.seq + 1
    assert record.prev_hash == pending.record_hash
    assert record.record_hash == chain_hash(record.prev_hash, record)
    assert record.proposal == pending.proposal and record.input_hash == pending.input_hash
    assert record.review_action is not None
    assert record.review_action.reason_code == ReasonCode.MATCH_VERIFIED.value


def test_submit_validates_and_writes_nothing_on_error(conn: sqlite3.Connection) -> None:
    pending = _log_pending(conn, _proposal([BLOCK]))
    with pytest.raises(ReviewError, match="BLOCK"):
        review.submit(
            conn,
            pending,
            action=ReviewActionType.CONFIRM,
            reason_code=ReasonCode.MATCH_VERIFIED,
            reviewer="pharmacist-1",
            acknowledged=frozenset(),
            known_formula_ids=KNOWN,
        )
    assert audit.read_all(conn) == [pending]


def test_submit_refuses_a_second_review_of_the_same_proposal(conn: sqlite3.Connection) -> None:
    pending = _log_pending(conn, _proposal())
    kwargs = {
        "action": ReviewActionType.CLARIFY,
        "reason_code": ReasonCode.AMBIGUOUS_ORDER,
        "reviewer": "pharmacist-1",
        "acknowledged": frozenset(),
        "known_formula_ids": KNOWN,
    }
    review.submit(conn, pending, **kwargs)
    with pytest.raises(ReviewError, match="already reviewed"):
        review.submit(conn, pending, **kwargs)
    assert len(audit.read_all(conn)) == 2


def test_submit_refuses_a_record_that_is_not_pending(conn: sqlite3.Connection) -> None:
    pending = _log_pending(conn, _proposal())
    done = review.submit(
        conn,
        pending,
        action=ReviewActionType.CLARIFY,
        reason_code=ReasonCode.AMBIGUOUS_ORDER,
        reviewer="pharmacist-1",
        acknowledged=frozenset(),
        known_formula_ids=KNOWN,
    )
    with pytest.raises(ReviewError, match="pending"):
        review.submit(
            conn,
            done,
            action=ReviewActionType.CLARIFY,
            reason_code=ReasonCode.AMBIGUOUS_ORDER,
            reviewer="pharmacist-1",
            acknowledged=frozenset(),
            known_formula_ids=KNOWN,
        )


def test_submit_refuses_a_pending_record_not_in_the_log(conn: sqlite3.Connection) -> None:
    _log_pending(conn, _proposal())
    stranger = pending_record(_proposal(pid="rx-999"), TEXT, seq=0, prev_hash=GENESIS_HASH)
    with pytest.raises(ReviewError, match="not in the audit log"):
        review.submit(
            conn,
            stranger,
            action=ReviewActionType.CLARIFY,
            reason_code=ReasonCode.AMBIGUOUS_ORDER,
            reviewer="pharmacist-1",
            acknowledged=frozenset(),
            known_formula_ids=KNOWN,
        )


def test_pending_queue_lists_unreviewed_records_only(conn: sqlite3.Connection) -> None:
    first = _log_pending(conn, _proposal(pid="rx-001"))
    second = _log_pending(conn, _proposal(pid="rx-002"))
    assert review.pending_queue(audit.read_all(conn)) == [first, second]
    review.submit(
        conn,
        first,
        action=ReviewActionType.CLARIFY,
        reason_code=ReasonCode.MISSING_INFORMATION,
        reviewer="pharmacist-1",
        acknowledged=frozenset(),
        known_formula_ids=KNOWN,
    )
    assert review.pending_queue(audit.read_all(conn)) == [second]


# --- display helpers ------------------------------------------------------------------------------


def test_flags_are_ordered_block_first() -> None:
    proposal = _proposal([REVIEW_A, BLOCK, REVIEW_B])
    assert [f.rule_id for f in review.ordered_flags(proposal)] == ["R1-04", "R1-03", "M-01"]


def test_formula_diff_marks_differences() -> None:
    from intake.library import load_alias_map, load_formulas

    formula = next(f for f in load_formulas() if f.formula_id == "SHF-001")
    rows = {row.field: row for row in review.formula_diff(_proposal().extraction, formula, load_alias_map())}
    assert rows["dosage_form"].same and rows["route"].same
    assert rows["ingredient: salicylic acid"].same
    assert not rows["ingredient: urea"].same  # 12% prescribed vs 10% in the formula


def test_formula_diff_handles_missing_extraction() -> None:
    from intake.library import load_formulas

    formula = load_formulas()[0]
    rows = review.formula_diff(None, formula, {})
    assert rows and not any(row.same for row in rows)


def test_raw_text_is_shown_only_when_the_hash_matches(tmp_path: Path) -> None:
    (tmp_path / "rx-001.txt").write_text(TEXT, encoding="utf-8")
    good = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    assert review.find_raw_text("rx-001", good, [tmp_path]) == TEXT
    assert review.find_raw_text("rx-001", "0" * 64, [tmp_path]) is None
    assert review.find_raw_text("rx-404", good, [tmp_path]) is None
    assert review.find_raw_text("../rx-001", good, [tmp_path / "sub"]) is None


# --- AC4: no bulk action, no auto-confirm --------------------------------------------------------


def test_actions_need_explicit_action_reason_and_reviewer() -> None:
    for func in (review.build_action, review.submit):
        params = inspect.signature(func).parameters
        for name in ("action", "reason_code", "reviewer", "acknowledged"):
            assert params[name].default is inspect.Parameter.empty, f"{func.__name__}({name}) has a default"
            assert params[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_actions_take_one_proposal_not_a_batch() -> None:
    assert next(iter(inspect.signature(review.build_action).parameters)) == "proposal"
    assert inspect.signature(review.build_action).parameters["proposal"].annotation is Proposal
    assert inspect.signature(review.submit).parameters["pending"].annotation is AuditRecord


def _calls(tree: ast.AST, name: str) -> list[ast.Call]:
    def called(node: ast.Call) -> str | None:
        func = node.func
        return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)

    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and called(n) == name]


def _inside_loop(tree: ast.AST, target: ast.AST) -> bool:
    loops = (ast.For, ast.While, ast.AsyncFor, ast.comprehension, ast.ListComp, ast.GeneratorExp)
    return any(
        isinstance(node, loops) and any(child is target for child in ast.walk(node)) for node in ast.walk(tree)
    )


def test_review_module_appends_in_one_place_never_in_a_loop() -> None:
    tree = ast.parse(REVIEW_SRC.read_text(encoding="utf-8"))
    appends = _calls(tree, "append")
    audit_appends = [c for c in appends if isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", "") == "audit"]
    assert len(audit_appends) == 1
    assert not _inside_loop(tree, audit_appends[0])


def test_app_submits_in_one_place_behind_a_button_never_in_a_loop() -> None:
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))
    submits = _calls(tree, "submit")
    assert len(submits) == 1, "the app should submit a review from exactly one place"
    assert not _inside_loop(tree, submits[0])
    assert not _calls(tree, "append"), "the app must write through review.submit only"


# --- the Streamlit screen (AppTest, no browser) ---------------------------------------------------


def _app(db: Path, monkeypatch: pytest.MonkeyPatch):
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("INTAKE_AUDIT_DB", str(db))
    app = AppTest.from_file(str(APP_SRC), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    return app


def _button(app, label: str):
    return next(b for b in app.button if b.label == label)


def _seed(tmp_path: Path, proposal: Proposal) -> Path:
    db = tmp_path / "audit.sqlite"
    conn = audit.connect(db)
    try:
        _log_pending(conn, proposal)
    finally:
        conn.close()
    return db


def _count(db: Path) -> int:
    conn = audit.connect(db)
    try:
        return len(audit.read_all(conn))
    finally:
        conn.close()


def test_app_empty_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(tmp_path / "audit.sqlite", monkeypatch)
    assert any("No proposals" in i.value for i in app.info)


def test_app_render_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _seed(tmp_path, _proposal())
    app = _app(db, monkeypatch)
    app.run()
    assert _count(db) == 1  # no auto-confirm: rendering never writes


def test_app_block_disables_confirm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(_seed(tmp_path, _proposal([BLOCK])), monkeypatch)
    assert _button(app, "CONFIRM").disabled
    assert not app.checkbox or all("R1-04" not in c.label for c in app.checkbox)  # BLOCK has no ack box


def test_app_review_flag_needs_ack_then_confirm_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _seed(tmp_path, _proposal([REVIEW_A]))
    app = _app(db, monkeypatch)
    assert _button(app, "CONFIRM").disabled
    app.text_input(key="reviewer").input("pharmacist-1")
    app.checkbox(key="ack-0-R1-03").check()
    app.run()
    assert not _button(app, "CONFIRM").disabled
    app.selectbox(key="reason-0-CONFIRM").select(ReasonCode.MATCH_VERIFIED.value)
    _button(app, "CONFIRM").click()
    app.run()
    assert not app.exception, app.exception
    assert _count(db) == 2
    conn = audit.connect(db)
    try:
        stored = audit.read_all(conn)[-1]
    finally:
        conn.close()
    assert stored.review_action is not None and stored.review_action.action is ReviewActionType.CONFIRM


def test_app_action_without_reason_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _seed(tmp_path, _proposal())
    app = _app(db, monkeypatch)
    app.text_input(key="reviewer").input("pharmacist-1")
    app.run()
    _button(app, "CLARIFY").click()
    app.run()
    assert _count(db) == 1
    assert any("reason" in e.value for e in app.error)


# --- #41: submit reads the chain head and appends in one transaction ---------------------------

CLARIFY_KWARGS: dict[str, object] = {
    "action": ReviewActionType.CLARIFY,
    "reason_code": ReasonCode.AMBIGUOUS_ORDER,
    "reviewer": "pharmacist-1",
    "acknowledged": frozenset(),
    "known_formula_ids": KNOWN,
}


def _interleaved_submits(
    db: Path, monkeypatch: pytest.MonkeyPatch, pending_a: AuditRecord, pending_b: AuditRecord
) -> tuple[AuditRecord | Exception, AuditRecord | Exception, list[bool]]:
    """Reviewer A reads the log, then pauses inside `build_action`; reviewer B submits in that gap."""
    real_build_action = review.build_action
    a_inside = threading.Event()
    b_done = threading.Event()
    b_finished_inside_a: list[bool] = []

    def pause_first_reviewer(*args: object, **kwargs: object):
        action = real_build_action(*args, **kwargs)
        if not a_inside.is_set():
            a_inside.set()
            b_finished_inside_a.append(b_done.wait(timeout=0.5))
        return action

    monkeypatch.setattr(review, "build_action", pause_first_reviewer)

    def submit_on_own_connection(pending: AuditRecord) -> AuditRecord | Exception:
        conn = audit.connect(db)
        try:
            return review.submit(conn, pending, **CLARIFY_KWARGS)
        except (ReviewError, ValueError, sqlite3.Error) as error:
            return error
        finally:
            conn.close()

    results: dict[str, AuditRecord | Exception] = {}

    def reviewer_b() -> None:
        a_inside.wait(timeout=5)
        results["b"] = submit_on_own_connection(pending_b)
        b_done.set()

    thread = threading.Thread(target=reviewer_b)
    thread.start()
    result_a = submit_on_own_connection(pending_a)
    thread.join(timeout=10)
    return result_a, results["b"], b_finished_inside_a


def _seed_two(tmp_path: Path) -> tuple[Path, AuditRecord, AuditRecord]:
    db = tmp_path / "audit.sqlite"
    conn = audit.connect(db)
    try:
        first = _log_pending(conn, _proposal(pid="rx-001"))
        second = _log_pending(conn, _proposal(pid="rx-002"))
    finally:
        conn.close()
    return db, first, second


def test_interleaved_submits_on_different_records_keep_one_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, first, second = _seed_two(tmp_path)
    result_a, result_b, b_finished_inside_a = _interleaved_submits(db, monkeypatch, first, second)
    assert isinstance(result_a, AuditRecord), result_a
    assert isinstance(result_b, AuditRecord), result_b
    assert b_finished_inside_a == [False]  # B waited for A's transaction
    assert (result_a.seq, result_b.seq) == (2, 3)
    assert result_b.prev_hash == result_a.record_hash
    conn = audit.connect(db)
    try:
        assert audit.verify(conn).ok  # no fork: every prev_hash is the previous record_hash
    finally:
        conn.close()


def test_interleaved_submits_on_the_same_record_review_it_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, first, _ = _seed_two(tmp_path)
    result_a, result_b, _ = _interleaved_submits(db, monkeypatch, first, first)
    assert isinstance(result_a, AuditRecord), result_a
    assert isinstance(result_b, ReviewError) and "already reviewed" in str(result_b)
    assert _count(db) == 3


# --- #69: the screen shows the explanation from `add_reasons` ----------------------------------

REASONS = "SHF-001 is proposed: ingredients=1.00. R1-03 needs acknowledging."


def test_reasons_text_shows_the_stored_explanation() -> None:
    proposal = _proposal().model_copy(update={"reasons": REASONS})
    assert review.reasons_text(proposal) == REASONS


def test_reasons_text_says_when_there_is_no_explanation() -> None:
    assert "no explanation" in review.reasons_text(_proposal()).lower()


def test_reasons_do_not_change_confirm_blockers() -> None:
    for flags in ([], [BLOCK], [REVIEW_A]):
        plain = _proposal(flags)
        explained = plain.model_copy(update={"reasons": REASONS})
        assert review.confirm_blockers(explained, ()) == review.confirm_blockers(plain, ())


def test_app_shows_reasons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(_seed(tmp_path, _proposal([REVIEW_A]).model_copy(update={"reasons": REASONS})), monkeypatch)
    assert any(h.value == "Reasons" for h in app.subheader)
    assert any(REASONS in m.value for m in app.markdown)


def test_app_says_when_a_proposal_has_no_reasons(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app(_seed(tmp_path, _proposal()), monkeypatch)
    assert any(h.value == "Reasons" for h in app.subheader)
    assert any("no explanation" in m.value.lower() for m in app.markdown)


def test_app_shows_reasons_from_intake_run_and_block_still_disables_confirm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end in REPLAY: `intake run` explains case_005 (R1-05 BLOCK); the screen shows those reasons."""
    from intake.adapters import anthropic_client
    from intake.cli import main

    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")
    db = tmp_path / "audit.sqlite"
    assert main(["run", str(REPO / "samples" / "case_005.txt"), "--audit-db", str(db)]) == 0
    conn = audit.connect(db)
    try:
        (record,) = audit.read_all(conn)
    finally:
        conn.close()
    assert record.proposal.reasons.strip() and "R1-05" in record.proposal.reasons
    app = _app(db, monkeypatch)
    assert any(record.proposal.reasons.strip() in m.value for m in app.markdown)
    assert _button(app, "CONFIRM").disabled
    assert _count(db) == 1
