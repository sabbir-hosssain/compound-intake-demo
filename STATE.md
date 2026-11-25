# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #6 S1.6 matcher (PR open, awaiting review)
Last merges: #4 S1.4 rules skeleton (PR #34, 0 rounds) · #3 S1.3 adapter (PR #32, 0) · #2 S1.2 seed (PR #31, 0) · #1 S1.1 schemas (PR #30, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.5 extraction v1 · S1.7 audit v0
Notes:
- Rules: `RULES_VERSION="0.1.0"`; `run_pass1(text, existing)` (R1-01, R1-05), `run_pass2(extraction, known, existing)` (R2-01); passes return `[*existing, *new]`.
- Adapter: `ModelClient.complete(prompt_hash, system, user_input, tools=None)`; INTAKE_MODE replay|record|live; no temperature sent (#33).
- S1.5: forced tool_choice 400s on Sonnet 5.5 — use `auto` + `strict: true`, or `output_config.format`. RECORD needs ANTHROPIC_API_KEY.
- Matcher: `match(extraction, formulas, thresholds, aliases, existing=())` -> `MatchResult` (top-3 candidates, confidence, margin, status, flags). `load_thresholds()` reads eval/thresholds.yaml; `library.load_formulas()`, `load_alias_map()`, `library_version()`. M-01 = REVIEW, `source_pass=2`, `MATCH_VERSION`.
- S1.10: invariant-1 scan must also catch relative imports (`from .. import audit`).
- eval-replay is a placeholder until S1.9.
