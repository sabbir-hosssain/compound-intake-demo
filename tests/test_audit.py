"""S1.7 audit v0: append-only SQLite table, insert-only API, DB path from config.toml."""

import ast
import inspect
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from intake import audit
from intake.models import AuditRecord, Proposal, ProposalStatus, ReviewAction, ReviewActionType

REPO = Path(__file__).resolve().parents[1]
AUDIT_SRC = REPO / "src" / "intake" / "audit.py"
AT = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)

# Names that would suggest the API can change or remove what is already written.
MUTATION_NAME = re.compile(
    r"update|delete|remove|drop|truncate|clear|edit|modify|replace|purge|erase|amend|overwrite|set_|vacuum",
    re.IGNORECASE,
)
EXPECTED_PUBLIC_API = {
    "db_path",
    "connect",
    "append",
    "next_seq",
    "read_all",
    # S3.2: read-only hash-chain helpers and verify.
    "canonical_json",
    "chain_hash",
    "verify",
    "VerifyResult",
}


def _proposal(pid: str = "rx-001") -> Proposal:
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


def _record(seq: int, review: ReviewAction | None = None) -> AuditRecord:
    return AuditRecord(
        seq=seq,
        prev_hash="0" * 64,
        record_hash=f"{seq:064x}",
        input_hash="f" * 64,
        proposal=_proposal(f"rx-{seq:03d}"),
        review_action=review,
        at=AT,
    )


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = audit.connect(tmp_path / "audit.sqlite")
    yield c
    c.close()


# --- AC: insert-only API ------------------------------------------------------


def test_append_and_read_back_roundtrip(conn: sqlite3.Connection) -> None:
    review = ReviewAction(action=ReviewActionType.CLARIFY, reviewer="reviewer-1", at=AT)
    records = [_record(0), _record(1, review)]
    for r in records:
        audit.append(conn, r)
    assert audit.read_all(conn) == records


def test_next_seq_counts_from_zero(conn: sqlite3.Connection) -> None:
    assert audit.next_seq(conn) == 0
    audit.append(conn, _record(0))
    assert audit.next_seq(conn) == 1


def test_append_rejects_out_of_order_seq(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="seq"):
        audit.append(conn, _record(1))
    audit.append(conn, _record(0))
    with pytest.raises(ValueError, match="seq"):
        audit.append(conn, _record(0))
    assert len(audit.read_all(conn)) == 1


def test_append_rejects_non_record(conn: sqlite3.Connection) -> None:
    with pytest.raises(TypeError):
        audit.append(conn, _record(0).model_dump())  # type: ignore[arg-type]


def test_records_persist_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "audit.sqlite"
    c1 = audit.connect(path)
    audit.append(c1, _record(0))
    c1.close()
    c2 = audit.connect(path)
    assert audit.read_all(c2) == [_record(0)]
    c2.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_log SET record_json = '{}' WHERE seq = 0",
        "UPDATE audit_log SET record_hash = 'x'",
        "DELETE FROM audit_log WHERE seq = 0",
        "DELETE FROM audit_log",
    ],
)
def test_database_refuses_update_and_delete(conn: sqlite3.Connection, sql: str) -> None:
    """Defence in depth: even raw SQL on the connection cannot change or remove a row."""
    audit.append(conn, _record(0))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(sql)
    assert audit.read_all(conn) == [_record(0)]


def test_insert_or_replace_cannot_overwrite(conn: sqlite3.Connection) -> None:
    audit.append(conn, _record(0))
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(
            "INSERT OR REPLACE INTO audit_log (seq, prev_hash, record_hash, input_hash, at, record_json) "
            "VALUES (0, 'a', 'b', 'c', 'd', '{}')"
        )
    assert audit.read_all(conn) == [_record(0)]


# --- AC: introspection shows no mutation functions ------------------------------


def _module_functions() -> dict[str, object]:
    return {
        name: obj
        for name, obj in inspect.getmembers(audit, callable)
        if getattr(obj, "__module__", None) == audit.__name__
    }


def test_public_api_is_exactly_the_insert_and_read_functions() -> None:
    public = {name for name in _module_functions() if not name.startswith("_")}
    assert public == EXPECTED_PUBLIC_API


def test_no_function_name_suggests_mutation() -> None:
    offenders = [name for name in _module_functions() if MUTATION_NAME.search(name)]
    assert offenders == []


def test_source_defines_no_mutation_functions_or_classes() -> None:
    """AST scan also catches nested/private defs and methods that getmembers would miss."""
    tree = ast.parse(AUDIT_SRC.read_text(encoding="utf-8"))
    defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]
    assert defs, "expected audit.py to define functions"
    assert [d for d in defs if MUTATION_NAME.search(d)] == []


def test_only_sql_that_writes_rows_is_insert() -> None:
    """Every SQL string in audit.py that mentions UPDATE/DELETE must be a trigger that forbids them."""
    tree = ast.parse(AUDIT_SRC.read_text(encoding="utf-8"))
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    strings = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    assert any("INSERT INTO audit_log" in s for s in strings)
    for s in strings:
        upper = s.upper()
        if re.search(r"\b(UPDATE|DELETE|REPLACE|DROP|TRUNCATE)\b", upper):
            assert "CREATE TRIGGER" in upper and "RAISE(ABORT" in upper, s


def test_audit_imports_no_llm_module() -> None:
    tree = ast.parse(AUDIT_SRC.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(("." * node.level) + (node.module or ""))
    forbidden = ("extract", "explain", "adapters", "anthropic")
    assert [m for m in imported if any(f in m for f in forbidden)] == []


# --- AC: DB path from config.toml --------------------------------------------


def test_db_path_comes_from_repo_config() -> None:
    assert audit.db_path() == REPO / "intake_audit.sqlite"


def test_db_path_follows_config_value(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[paths]\naudit_db = "var/other_audit.sqlite"\n', encoding="utf-8")
    assert audit.db_path(cfg) == audit.REPO_ROOT / "var" / "other_audit.sqlite"


def test_db_path_absolute_value_kept(tmp_path: Path) -> None:
    target = tmp_path / "abs.sqlite"
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[paths]\naudit_db = "{target.as_posix()}"\n', encoding="utf-8")
    assert audit.db_path(cfg) == target


def test_db_path_missing_key_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text("[paths]\n", encoding="utf-8")
    with pytest.raises(KeyError):
        audit.db_path(cfg)


def test_connect_defaults_to_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "nested" / "from_config.sqlite"
    monkeypatch.setattr(audit, "db_path", lambda *_a, **_k: target)
    c = audit.connect()
    audit.append(c, _record(0))
    c.close()
    assert target.exists()
