"""`intake` command line.

`intake run <file>` builds a proposal, prints it and logs it as pending.
`intake audit verify` recomputes the audit hash chain and reports the first broken link.

The mode comes from INTAKE_MODE (default REPLAY). A missing recording in REPLAY is a failure
(non-zero exit, nothing written), never a fallback to a live model (invariant 4).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from intake import audit
from intake.adapters.anthropic_client import ModelClient
from intake.adapters.cassette import MissingRecordingError
from intake.pipeline import format_proposal, run_file

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_RECORDING = 2
EXIT_CHAIN_BROKEN = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="intake", description="Compound prescription intake (synthetic demo).")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the pipeline on one prescription file and log it as pending.")
    run.add_argument("file", type=Path, help="Path to a free-text prescription.")
    run.add_argument("--audit-db", type=Path, default=None, help="Audit SQLite file (default: config.toml).")
    audit_cmd = commands.add_parser("audit", help="Audit log commands.")
    audit_commands = audit_cmd.add_subparsers(dest="audit_command", required=True)
    verify = audit_commands.add_parser("verify", help="Recompute the hash chain; report the first broken link.")
    verify.add_argument("--audit-db", type=Path, default=None, help="Audit SQLite file (default: config.toml).")
    return parser


def _run(file: Path, audit_db: Path | None) -> int:
    try:
        proposal, record = run_file(file, client=ModelClient(), audit_db=audit_db)
    except MissingRecordingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MISSING_RECORDING
    except (OSError, UnicodeDecodeError) as error:
        print(f"error: cannot read {file}: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(format_proposal(proposal))
    print(f"Audit:        seq {record.seq} logged as pending pharmacist review (review_action = null)")
    return EXIT_OK


def _verify(audit_db: Path | None) -> int:
    path = audit_db if audit_db is not None else audit.db_path()
    if not path.is_file():
        print(f"error: no audit log at {path}", file=sys.stderr)
        return EXIT_ERROR
    conn = audit.connect(path)
    try:
        result = audit.verify(conn)
    finally:
        conn.close()
    if result.ok:
        print(f"OK: {result.records} records, hash chain intact ({path})")
        return EXIT_OK
    print(f"BROKEN: first broken link at seq {result.broken_seq}: {result.reason}")
    print(f"        {result.records} records before it verify ({path})")
    return EXIT_CHAIN_BROKEN


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args.file, args.audit_db)
    if args.command == "audit" and args.audit_command == "verify":
        return _verify(args.audit_db)
    return EXIT_ERROR  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
