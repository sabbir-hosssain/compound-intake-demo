"""Append-only, hash-chained SQLite audit log (SPEC §10).

The API can insert, read and verify records; it has no update or delete function. The table also
carries triggers that abort any UPDATE or DELETE and any INSERT that is not the next `seq`, so even
raw SQL on the connection cannot change or remove a written row.

Chain: `record_hash = sha256(prev_hash + canonical_json(record))`, where canonical JSON is the record
without its own `record_hash`, dumped in Pydantic JSON mode with sorted keys and compact separators.
The first record links to `GENESIS_HASH`. `append` stores hashes as the caller gives them; `verify`
recomputes the whole chain and reports the first broken link.
"""

import hashlib
import json
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from intake.models import AuditRecord

GENESIS_HASH = "0" * 64

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config.toml"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    seq         INTEGER PRIMARY KEY,
    prev_hash   TEXT NOT NULL,
    record_hash TEXT NOT NULL,
    input_hash  TEXT NOT NULL,
    at          TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is not allowed');
END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is not allowed');
END;
CREATE TRIGGER IF NOT EXISTS audit_log_next_seq_only
BEFORE INSERT ON audit_log
WHEN NEW.seq IS NOT (SELECT COALESCE(MAX(seq) + 1, 0) FROM audit_log)
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: seq must be the next number');
END;
"""

_INSERT = "INSERT INTO audit_log (seq, prev_hash, record_hash, input_hash, at, record_json) VALUES (?, ?, ?, ?, ?, ?)"


def db_path(config_path: Path = CONFIG_PATH) -> Path:
    """Audit DB path from `[paths].audit_db` in config.toml; relative paths resolve from the repo root."""
    config = tomllib.loads(Path(config_path).read_text(encoding="utf-8"))
    path = Path(config["paths"]["audit_db"])
    return path if path.is_absolute() else REPO_ROOT / path


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open (creating if needed) the audit DB. Defaults to the path in config.toml."""
    target = Path(path) if path is not None else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.executescript(_SCHEMA)
    return conn


def next_seq(conn: sqlite3.Connection) -> int:
    """The `seq` the next appended record must carry (0 for an empty log)."""
    (value,) = conn.execute("SELECT COALESCE(MAX(seq) + 1, 0) FROM audit_log").fetchone()
    return int(value)


def append(conn: sqlite3.Connection, record: AuditRecord) -> int:
    """Insert one record and commit. `record.seq` must equal `next_seq(conn)`. Returns the seq."""
    if not isinstance(record, AuditRecord):
        raise TypeError(f"append expects an AuditRecord, got {type(record).__name__}")
    expected = next_seq(conn)
    if record.seq != expected:
        raise ValueError(f"record seq {record.seq} is not the next seq {expected}")
    row = (
        record.seq,
        record.prev_hash,
        record.record_hash,
        record.input_hash,
        record.at.isoformat(),
        record.model_dump_json(),
    )
    with conn:
        conn.execute(_INSERT, row)
    return record.seq


def read_all(conn: sqlite3.Connection) -> list[AuditRecord]:
    """Every record in `seq` order."""
    rows = conn.execute("SELECT record_json FROM audit_log ORDER BY seq").fetchall()
    return [AuditRecord.model_validate_json(json_text) for (json_text,) in rows]


# --- hash chain ---------------------------------------------------------------------------------


def canonical_json(record: AuditRecord) -> str:
    """The record minus its own hash, as sorted, compact JSON."""
    payload = record.model_dump(mode="json", exclude={"record_hash"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev_hash: str, record: AuditRecord) -> str:
    """`sha256(prev_hash + canonical_json(record))` as lowercase hex."""
    return hashlib.sha256((prev_hash + canonical_json(record)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of `verify`: how many records were checked and the first broken link, if any."""

    records: int
    broken_seq: int | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.broken_seq is None


_SELECT_ROWS = "SELECT seq, prev_hash, record_hash, input_hash, at, record_json FROM audit_log ORDER BY seq"


def _row_problem(row: tuple, expected_seq: int, prev_hash: str) -> str | None:
    """Why this row breaks the chain, or None if it links correctly."""
    seq, col_prev, col_hash, col_input, col_at, record_json = row
    if seq != expected_seq:
        return f"seq gap: expected seq {expected_seq}, found {seq}"
    try:
        record = AuditRecord.model_validate_json(record_json)
    except ValidationError as error:
        return f"record_json does not parse as an AuditRecord ({error.error_count()} errors)"
    columns = {
        "seq": (seq, record.seq),
        "prev_hash": (col_prev, record.prev_hash),
        "record_hash": (col_hash, record.record_hash),
        "input_hash": (col_input, record.input_hash),
        "at": (col_at, record.at.isoformat()),
    }
    for name, (column, stored) in columns.items():
        if column != stored:
            return f"column {name} disagrees with record_json"
    if record.prev_hash != prev_hash:
        return f"prev_hash {record.prev_hash[:12]}... does not match the previous record_hash {prev_hash[:12]}..."
    recomputed = chain_hash(record.prev_hash, record)
    if record.record_hash != recomputed:
        return f"record_hash {record.record_hash[:12]}... does not match the recomputed {recomputed[:12]}..."
    return None


def verify(conn: sqlite3.Connection) -> VerifyResult:
    """Recompute the chain in `seq` order and stop at the first broken link. Read-only."""
    prev_hash = GENESIS_HASH
    checked = 0
    for row in conn.execute(_SELECT_ROWS):
        problem = _row_problem(row, checked, prev_hash)
        if problem is not None:
            return VerifyResult(records=checked, broken_seq=row[0], reason=problem)
        prev_hash = row[2]
        checked += 1
    return VerifyResult(records=checked)
