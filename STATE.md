# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: none (code lane next: #8 S1.8 CLI)
Last merges: #5 S1.5 extraction (PR #35, 0 code fix rounds; 1 architect block on the key) · #39 chore · #10 S1.10 arch test (PR #38, 0) · #7 S1.7 audit (PR #37, 0) · #6 S1.6 matcher (PR #36, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.8 CLI · S1.9 eval harness (then M1 exit check)
Notes:
- Live-model steps use `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …` (absolute path; never read .env; see DECISIONS-LOG).
- Extraction: `extract(text, *, client) -> ExtractResult(status OK|MANUAL, ...)`; strict tool `record_extraction`, tool_choice auto; cassettes for case_001–003.
- Audit: append-only API + SQLite triggers. Matcher: thresholds.yaml, M-01 = pass 2 + MATCH_VERSION. Rules: RULES_VERSION="0.1.0".
- S1.8 "writes audit" = pending record (review_action = null), per Gate 1.
- eval-replay is a placeholder until S1.9.
