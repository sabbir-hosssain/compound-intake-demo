"""Append-only SQLite audit log (SPEC §10), v0.

The API can insert and read records; it has no update or delete function. The table also carries
triggers that abort any UPDATE or DELETE and any INSERT that is not the next `seq`, so even raw SQL
on the connection cannot change or remove a written row.

Hash-chain computation and `intake audit verify` arrive in S3.2; here the caller supplies a fully
formed `AuditRecord` and the hashes are stored as given.
"""

import sqlite3
import tomllib
from pathlib import Path

from intake.models import AuditRecord

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
