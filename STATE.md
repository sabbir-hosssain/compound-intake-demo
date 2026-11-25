# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #5 S1.5 extraction — recordings committed, PR #35 in review
Last merges: #39 chore (gitignore, key rule) · #10 S1.10 architecture test (PR #38, 0) · #7 S1.7 audit (PR #37, 0) · #6 S1.6 matcher (PR #36, 0) · #4 S1.4 rules (PR #34, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.5 merge · S1.8 CLI · S1.9 eval harness
Notes:
- Live-model steps use `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …` (absolute path; never read .env; see DECISIONS-LOG).
- Extraction: `extract(text, *, client) -> ExtractResult(status OK|MANUAL, ...)`; strict tool `record_extraction`, tool_choice auto; cassettes for case_001–003.
- Audit: append-only API + SQLite triggers. Matcher: thresholds.yaml, M-01 = pass 2 + MATCH_VERSION. Rules: RULES_VERSION="0.1.0".
- S1.8 "writes audit" = pending record (review_action = null), per Gate 1.
- eval-replay is a placeholder until S1.9.
