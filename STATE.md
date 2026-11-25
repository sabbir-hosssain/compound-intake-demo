# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #5 S1.5 extraction — recording with the architect's key (orchestrator, per architect instruction)
Last merges: #10 S1.10 architecture test (PR #38, 0 rounds) · #7 S1.7 audit (PR #37, 0) · #6 S1.6 matcher (PR #36, 0) · #4 S1.4 rules (PR #34, 0) · #3 S1.3 adapter (PR #32, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.5 (record → review → merge) · S1.8 CLI · S1.9 eval harness
Notes:
- Live-model steps use `env -u ANTHROPIC_API_KEY uv run --env-file /Users/turjo/code/compound-intake-demo/.env …` (never read .env; see DECISIONS-LOG).
- Architecture test walks the full import graph (relative + dynamic imports); old scan in tests/test_adapter.py is now redundant.
- Audit: append-only API + SQLite triggers. Matcher: thresholds.yaml, M-01 = pass 2 + MATCH_VERSION. Rules: RULES_VERSION="0.1.0".
- eval-replay is a placeholder until S1.9.
