"""`intake` command line.

`intake run <file>` builds a proposal, adds the explanation (`intake.explain.add_reasons`), prints it and
logs it as pending.
`intake audit verify` recomputes the audit hash chain and reports the first broken link.
`intake demo` runs the demo fixtures (data/demo/demo_cases.jsonl) through the same pipeline and prints
each review outcome with its explanation. It writes nothing to the audit log: only a pharmacist action
commits a record.

The explanation is added after matching and can only set `reasons` (see `intake.explain.with_reasons`);
candidates, flags and status are the code's. A missing explain recording fails like a missing extraction one.

The mode comes from INTAKE_MODE (default REPLAY). A missing recording in REPLAY is a failure
(non-zero exit, nothing written), never a fallback to a live model (invariant 4).
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from intake import audit
from intake.adapters.anthropic_client import REPO_ROOT, ModelClient
from intake.adapters.cassette import MissingRecordingError
from intake.explain import add_reasons
from intake.extract import CompletionClient
from intake.models import Proposal, Severity
from intake.pipeline import build_proposal, format_proposal, load_library, log_pending
from intake.review import confirm_blockers

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISSING_RECORDING = 2
EXIT_CHAIN_BROKEN = 3
EXIT_DEMO_MISMATCH = 4

DEMO_CASES = REPO_ROOT / "data" / "demo" / "demo_cases.jsonl"

Outcome = tuple[str | None, str, list[str], bool]  # top formula, status, sorted flag IDs, BLOCK present


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
    demo = commands.add_parser("demo", help="Run the demo fixtures; show flags and CONFIRM state (no audit write).")
    demo.add_argument("--cases", type=Path, default=DEMO_CASES, help="Demo cases JSONL (default: data/demo).")
    trace = commands.add_parser("trace", help="Export replay traces for the static viewer (no audit write).")
    trace.add_argument("--out", type=Path, default=None, help="Output directory (default: viewer/traces).")
    return parser


def format_reasons(proposal: Proposal) -> str:
    """The explanation as printed under the proposal; the scores and flags above it are the code's."""
    lines = proposal.reasons.strip().splitlines() or ["(no explanation)"]
    return "\n".join(["Reasons:      " + lines[0], *("              " + line for line in lines[1:])])


def explained_proposal(text: str, prescription_id: str, *, client: CompletionClient) -> Proposal:
    """extract -> pass-1/2 rules -> match, then the explanation. Raises MissingRecordingError in REPLAY."""
    proposal = build_proposal(text, prescription_id, client=client, library=load_library())
    return add_reasons(proposal, client=client)


def _run(file: Path, audit_db: Path | None) -> int:
    try:
        text = file.read_bytes().decode("utf-8")
        proposal = explained_proposal(text, file.stem, client=ModelClient())
    except MissingRecordingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_MISSING_RECORDING
    except (OSError, UnicodeDecodeError) as error:
        print(f"error: cannot read {file}: {error}", file=sys.stderr)
        return EXIT_ERROR
    record = log_pending(proposal, text, audit_db)  # only after every model call has succeeded
    print(format_proposal(proposal))
    print(format_reasons(proposal))
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


# --- demo ----------------------------------------------------------------------------------------


def load_demo_cases(path: Path = DEMO_CASES) -> list[dict[str, Any]]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def demo_case_text(case: dict[str, Any]) -> str:
    """The case's sample file, read exactly as `intake run` reads it, so one recording serves both."""
    return (REPO_ROOT / case["sample_file"]).read_bytes().decode("utf-8")


def demo_proposal(case: dict[str, Any], *, client: CompletionClient) -> Proposal:
    """extract -> pass-1/2 rules -> match -> explanation, exactly as `intake run`, but never logged."""
    return explained_proposal(demo_case_text(case), case["case_id"], client=client)


def _outcome(proposal: Proposal) -> Outcome:
    top = proposal.candidates[0].formula_id if proposal.candidates else None
    has_block = any(f.severity is Severity.BLOCK for f in proposal.flags)
    return top, proposal.status.value, sorted(f.rule_id for f in proposal.flags), has_block


def _expected(case: dict[str, Any]) -> Outcome:
    flags = sorted(case["expected_flags"])
    return case["expected_formula_id"], case["expected_status"], flags, bool(case["expect_confirm_disabled"])


def _describe(outcome: Outcome) -> str:
    top, status, flags, has_block = outcome
    confirm = "disabled" if has_block else "enabled"
    return f"formula {top} · status {status} · flags [{', '.join(flags)}] · CONFIRM {confirm}"


def _confirm_line(proposal: Proposal) -> str:
    """CONFIRM state as the review screen opens (no REVIEW flag acknowledged yet)."""
    blockers = confirm_blockers(proposal, acknowledged=())
    if not blockers:
        return "CONFIRM: enabled"
    if any(f.severity is Severity.BLOCK for f in proposal.flags):
        return "CONFIRM: disabled · " + " ".join(blockers)
    return "CONFIRM: pending · " + " ".join(blockers)


def _demo_case(case: dict[str, Any], client: CompletionClient) -> bool:
    proposal = demo_proposal(case, client=client)
    print(f"=== {case['case_id']} ({case['category']}) · {case['sample_file']} ===")
    print(format_proposal(proposal))
    print(format_reasons(proposal))
    print(_confirm_line(proposal))
    print("Audit:        nothing written to the audit log (demo; only a pharmacist action commits a record)")
    got, want = _outcome(proposal), _expected(case)
    if got == want:
        print(f"Result:       matches the fixture ({_describe(want)})")
    else:
        print(f"Result:       DIFFERS from the fixture: expected {_describe(want)}; got {_describe(got)}")
    print()
    return got == want


def _demo(cases_path: Path) -> int:
    try:
        cases = load_demo_cases(cases_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"error: cannot read {cases_path}: {error}", file=sys.stderr)
        return EXIT_ERROR
    client = ModelClient()
    matched = 0
    for case in cases:
        try:
            matched += _demo_case(case, client)
        except MissingRecordingError as error:
            print(f"error: {case['case_id']}: {error}", file=sys.stderr)
            return EXIT_MISSING_RECORDING
        except (OSError, UnicodeDecodeError) as error:
            print(f"error: {case['case_id']}: cannot read {case['sample_file']}: {error}", file=sys.stderr)
            return EXIT_ERROR
    print(f"{matched}/{len(cases)} demo cases match their fixtures (mode {client.mode.value}).")
    return EXIT_OK if matched == len(cases) else EXIT_DEMO_MISMATCH


# --- trace ---------------------------------------------------------------------------------------


def _trace(out: Path | None) -> int:
    from intake import trace  # imported here: trace imports this module's demo helpers

    client = ModelClient()
    try:
        written = trace.write_all(out or trace.VIEWER_TRACES, client=client)
    except MissingRecordingError as exc:
        print(f"ERROR: missing recording: {exc}", file=sys.stderr)
        return EXIT_MISSING_RECORDING
    for path in written:
        print(f"wrote {path}")
    print(f"{len(written) - 1} traces exported (mode {client.mode.value}).")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        return _run(args.file, args.audit_db)
    if args.command == "audit" and args.audit_command == "verify":
        return _verify(args.audit_db)
    if args.command == "demo":
        return _demo(args.cases)
    if args.command == "trace":
        return _trace(args.out)
    return EXIT_ERROR  # unreachable: argparse requires a known command


if __name__ == "__main__":
    sys.exit(main())
