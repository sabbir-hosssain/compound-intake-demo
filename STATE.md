# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: none (code lane next: #10 S1.10 architecture test)
Last merges: #7 S1.7 audit v0 (PR #37, 0 rounds) · #6 S1.6 matcher (PR #36, 0) · #4 S1.4 rules (PR #34, 0) · #3 S1.3 adapter (PR #32, 0) · #2 S1.2 seed (PR #31, 0)
Blocked (architect):
- #5 S1.5 extraction: RECORD needs a real ANTHROPIC_API_KEY (env has a placeholder). Draft PR #35 ready apart from 3 recordings. Blocks S1.8 → S1.9 → M1 exit.
- #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.10 architecture test · then S1.8 CLI and S1.9 eval harness once #5 lands
Notes:
- Audit: `connect/append/read_all/next_seq/db_path`; SQLite triggers block UPDATE/DELETE/out-of-order INSERT; hashes stored as given (chain = S3.2).
- Matcher: reads eval/thresholds.yaml; M-01 uses source_pass=2 + `MATCH_VERSION`.
- Rules: `RULES_VERSION="0.1.0"`; passes return `[*existing, *new]`.
- Extraction (PR #35): `extract(text, *, client) -> ExtractResult(status OK|MANUAL, ...)`.
- S1.10: invariant-1 scan must also catch relative imports.
- eval-replay is a placeholder until S1.9.
