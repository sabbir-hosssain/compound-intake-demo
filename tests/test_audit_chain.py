"""S3.2: SPEC §10 hash chain and `intake audit verify`."""

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intake import audit, pipeline
from intake.cli import EXIT_CHAIN_BROKEN, EXIT_ERROR, EXIT_OK, main
from intake.models import AuditRecord, Proposal, ProposalStatus, ReviewAction, ReviewActionType

AT = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


def _proposal(pid: str) -> Proposal:
    return Proposal(
        prescription_id=pid,
        confidence=0.0,
        margin=0.0,
        status=ProposalStatus.MANUAL,
        model_id="claude-test-model",
        rules_version="0.1.0",
        library_version="abc123",
        created_at=AT,
    )


def _signed(seq: int, prev_hash: str, review: ReviewAction | None = None) -> AuditRecord:
    unsigned = AuditRecord(
        seq=seq,
        prev_hash=prev_hash,
        record_hash="",
        input_hash="f" * 64,
        proposal=_proposal(f"rx-{seq:03d}"),
        review_action=review,
        at=AT,
    )
    return unsigned.model_copy(update={"record_hash": audit.chain_hash(prev_hash, unsigned)})


def _write_chain(conn: sqlite3.Connection, n: int) -> list[AuditRecord]:
    records: list[AuditRecord] = []
    prev = audit.GENESIS_HASH
    for seq in range(n):
        review = ReviewAction(action=ReviewActionType.CLARIFY, reviewer="reviewer-1", at=AT) if seq % 2 else None
        record = _signed(seq, prev, review)
        audit.append(conn, record)
        records.append(record)
        prev = record.record_hash
    return records


def _force(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    """Simulate tampering outside the API: drop the guard trigger, then edit the file directly."""
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    with conn:
        conn.execute(sql, params)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = audit.connect(tmp_path / "audit.sqlite")
    yield c
    c.close()


# --- AC: record_hash = sha256(prev_hash + canonical_json(record)) --------------------------------


def test_chain_hash_is_sha256_of_prev_hash_plus_canonical_json() -> None:
    record = _signed(0, audit.GENESIS_HASH)
    payload = record.model_dump(mode="json", exclude={"record_hash"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert audit.canonical_json(record) == canonical
    expected = hashlib.sha256((audit.GENESIS_HASH + canonical).encode("utf-8")).hexdigest()
    assert audit.chain_hash(audit.GENESIS_HASH, record) == expected == record.record_hash


def test_canonical_json_ignores_the_records_own_hash() -> None:
    record = _signed(0, audit.GENESIS_HASH)
    assert audit.canonical_json(record) == audit.canonical_json(record.model_copy(update={"record_hash": "x"}))


def test_chain_hash_depends_on_prev_hash() -> None:
    record = _signed(0, audit.GENESIS_HASH)
    assert audit.chain_hash("a" * 64, record) != audit.chain_hash(audit.GENESIS_HASH, record)


def test_genesis_hash_is_64_zeros() -> None:
    assert audit.GENESIS_HASH == "0" * 64


def test_pipeline_uses_the_same_chain_functions() -> None:
    assert pipeline.chain_hash is audit.chain_hash
    assert pipeline.GENESIS_HASH == audit.GENESIS_HASH


# --- verify: intact chains -----------------------------------------------------------------------


def test_verify_empty_log_is_ok(conn: sqlite3.Connection) -> None:
    result = audit.verify(conn)
    assert result.ok and result.records == 0 and result.broken_seq is None


def test_verify_intact_chain_is_ok(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 5)
    result = audit.verify(conn)
    assert result.ok
    assert result.records == 5
    assert result.broken_seq is None and result.reason is None


def test_verify_accepts_pipeline_pending_records(conn: sqlite3.Connection) -> None:
    prev = audit.GENESIS_HASH
    for seq in range(3):
        record = pipeline.pending_record(_proposal(f"rx-{seq}"), f"text {seq}", seq=seq, prev_hash=prev)
        audit.append(conn, record)
        prev = record.record_hash
    assert audit.verify(conn).ok


def test_verify_does_not_write(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 3)
    before = conn.total_changes
    audit.verify(conn)
    assert conn.total_changes == before


# --- AC: a tamper test detects a modified record; verify reports the first broken link ----------


def _tampered_json(conn: sqlite3.Connection, seq: int, **changes: object) -> str:
    (text,) = conn.execute("SELECT record_json FROM audit_log WHERE seq = ?", (seq,)).fetchone()
    data = json.loads(text)
    data.update(changes)
    return json.dumps(data)


def test_tamper_modified_record_body_is_detected(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 4)
    tampered = _tampered_json(conn, 2, input_hash="e" * 64)
    _force(conn, "UPDATE audit_log SET record_json = ?, input_hash = ? WHERE seq = 2", (tampered, "e" * 64))
    result = audit.verify(conn)
    assert not result.ok
    assert result.broken_seq == 2
    assert "record_hash" in result.reason


def test_tamper_nested_field_is_detected(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 3)
    (text,) = conn.execute("SELECT record_json FROM audit_log WHERE seq = 1").fetchone()
    data = json.loads(text)
    data["review_action"]["action"] = "CONFIRM"
    _force(conn, "UPDATE audit_log SET record_json = ? WHERE seq = 1", (json.dumps(data),))
    result = audit.verify(conn)
    assert result.broken_seq == 1


def test_rehashed_record_breaks_the_next_link(conn: sqlite3.Connection) -> None:
    """A tamperer who also recomputes the record's own hash is caught at the next record."""
    records = _write_chain(conn, 4)
    forged = _signed(1, records[0].record_hash).model_copy(update={"input_hash": "e" * 64})
    forged = forged.model_copy(update={"record_hash": audit.chain_hash(forged.prev_hash, forged)})
    _force(
        conn,
        "UPDATE audit_log SET record_json = ?, record_hash = ?, input_hash = ? WHERE seq = 1",
        (forged.model_dump_json(), forged.record_hash, forged.input_hash),
    )
    result = audit.verify(conn)
    assert result.broken_seq == 2
    assert "prev_hash" in result.reason


def test_first_broken_link_is_reported_when_several_are_broken(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 5)
    for seq in (3, 1):
        tampered = _tampered_json(conn, seq, input_hash="d" * 64)
        _force(conn, "UPDATE audit_log SET record_json = ?, input_hash = ? WHERE seq = ?", (tampered, "d" * 64, seq))
    assert audit.verify(conn).broken_seq == 1


def test_wrong_genesis_prev_hash_is_detected(conn: sqlite3.Connection) -> None:
    audit.append(conn, _signed(0, "a" * 64))
    result = audit.verify(conn)
    assert result.broken_seq == 0
    assert "prev_hash" in result.reason


def test_deleted_record_is_detected(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 4)
    _force(conn, "DELETE FROM audit_log WHERE seq = 1")
    result = audit.verify(conn)
    assert not result.ok
    assert result.broken_seq == 2


def test_deleted_tail_is_not_detectable_but_rest_still_verifies(conn: sqlite3.Connection) -> None:
    """Truncating the tail leaves a valid shorter chain; documented limit of a hash chain without an anchor."""
    _write_chain(conn, 4)
    _force(conn, "DELETE FROM audit_log WHERE seq = 3")
    result = audit.verify(conn)
    assert result.ok and result.records == 3


def test_column_that_disagrees_with_the_json_is_detected(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 3)
    _force(conn, "UPDATE audit_log SET input_hash = ? WHERE seq = 1", ("e" * 64,))
    result = audit.verify(conn)
    assert result.broken_seq == 1
    assert "input_hash" in result.reason


def test_unparseable_record_json_is_detected(conn: sqlite3.Connection) -> None:
    _write_chain(conn, 3)
    _force(conn, "UPDATE audit_log SET record_json = ? WHERE seq = 2", ("{not json",))
    result = audit.verify(conn)
    assert result.broken_seq == 2
    assert "parse" in result.reason


# --- AC: still no update or delete functions ----------------------------------------------------


def test_verify_result_is_frozen() -> None:
    result = audit.VerifyResult(records=0)
    with pytest.raises((AttributeError, TypeError)):
        result.records = 1  # type: ignore[misc]


def test_module_exposes_no_update_or_delete_function() -> None:
    names = {name.lower() for name in dir(audit) if not name.startswith("_")}
    assert not any("update" in n or "delete" in n for n in names)


# --- CLI: intake audit verify -------------------------------------------------------------------


def test_cli_verify_ok(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "audit.sqlite"
    c = audit.connect(db)
    _write_chain(c, 3)
    c.close()
    assert main(["audit", "verify", "--audit-db", str(db)]) == EXIT_OK
    out = capsys.readouterr().out
    assert "OK" in out and "3 records" in out


def test_cli_verify_reports_first_broken_link(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "audit.sqlite"
    c = audit.connect(db)
    _write_chain(c, 4)
    tampered = _tampered_json(c, 2, input_hash="e" * 64)
    _force(c, "UPDATE audit_log SET record_json = ?, input_hash = ? WHERE seq = 2", (tampered, "e" * 64))
    c.close()
    assert main(["audit", "verify", "--audit-db", str(db)]) == EXIT_CHAIN_BROKEN
    out = capsys.readouterr().out
    assert "BROKEN" in out and "seq 2" in out


def test_cli_verify_missing_db_is_an_error_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "nope.sqlite"
    assert main(["audit", "verify", "--audit-db", str(db)]) == EXIT_ERROR
    assert not db.exists()
    assert "no audit log" in capsys.readouterr().err


def test_cli_verify_after_intake_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Records written by `intake run` (REPLAY) verify cleanly."""
    from intake.adapters import anthropic_client

    monkeypatch.setenv(anthropic_client.MODE_ENV, "replay")
    db = tmp_path / "audit.sqlite"
    case = Path(__file__).resolve().parents[1] / "samples" / "case_001.txt"
    assert main(["run", str(case), "--audit-db", str(db)]) == EXIT_OK
    assert main(["run", str(case), "--audit-db", str(db)]) == EXIT_OK
    assert main(["audit", "verify", "--audit-db", str(db)]) == EXIT_OK
