"""`intake` command line. `intake run <file>` builds a proposal, prints it and logs it as pending.

The mode comes from INTAKE_MODE (default REPLAY). A missing recording in REPLAY is a failure
(non-zero exit, nothing written), never a fallback to a live model (invariant 4).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from intake.adapters.anthropic_client import ModelClient
from intake.adapters.cassette import MissingRecordingError
from intake.pipeline import format_proposal, run_file

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_RECORDING = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="intake", description="Compound prescription intake (synthetic demo).")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run the pipeline on one prescription file and log it as pending.")
    run.add_argument("file", type=Path, help="Path to a free-text prescription.")
    run.add_argument("--audit-db", type=Path, default=None, help="Audit SQLite file (default: config.toml).")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args.file, args.audit_db)
    return EXIT_ERROR  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
