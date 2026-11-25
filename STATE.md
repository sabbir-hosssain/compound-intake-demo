# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #7 S1.7 audit v0 (PR open, awaiting review)
Last merges: #6 S1.6 matcher (PR #36, 0 rounds) · #4 S1.4 rules (PR #34, 0) · #3 S1.3 adapter (PR #32, 0) · #2 S1.2 seed (PR #31, 0) · #1 S1.1 schemas (PR #30, 0)
Blocked (architect):
- #5 S1.5 extraction: RECORD needs a real ANTHROPIC_API_KEY (env has a placeholder). Draft PR #35 ready apart from 3 recordings. Blocks S1.8 → S1.9 → M1 exit.
- #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.10 architecture test · (S1.8 after #5)
Notes:
- Matcher: `match(extraction, library, thresholds, existing)`; reads eval/thresholds.yaml; M-01 uses source_pass=2 + `MATCH_VERSION="0.1.0"` (resolves the S1.6 open point without a SPEC change).
- Audit v0: `connect(path=None)` (default from config `[paths].audit_db`), `append(conn, AuditRecord)` (seq must be `next_seq`), `read_all`; DB triggers block UPDATE/DELETE/non-next INSERT. Hashes stored as given until S3.2.
- Rules: `RULES_VERSION="0.1.0"`; passes return `[*existing, *new]`.
- Extraction (PR #35): `extract(text, *, client) -> ExtractResult(status OK|MANUAL, ...)`; strict tool `record_extraction`, tool_choice auto.
- S1.10: invariant-1 scan must also catch relative imports.
- eval-replay is a placeholder until S1.9.
