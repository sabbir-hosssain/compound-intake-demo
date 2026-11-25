# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: none (code lane next: #5 S1.5 extraction v1)
Last merges: #4 S1.4 rules skeleton (PR #34, 0 rounds) · #3 S1.3 adapter (PR #32, 0) · #2 S1.2 seed (PR #31, 0) · #1 S1.1 schemas (PR #30, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.5 extraction v1 · S1.6 matcher · S1.7 audit v0
Notes:
- Rules: `RULES_VERSION="0.1.0"`; `run_pass1(text, existing)` (R1-01, R1-05), `run_pass2(extraction, known, existing)` (R2-01); passes return `[*existing, *new]`.
- Adapter: `ModelClient.complete(prompt_hash, system, user_input, tools=None)`; INTAKE_MODE replay|record|live; no temperature sent (#33).
- S1.5: forced tool_choice 400s on Sonnet 5.5 — use `auto` + `strict: true`, or `output_config.format`. RECORD needs ANTHROPIC_API_KEY.
- S1.6: `Flag.source_pass` is 1|2; M-01 needs a convention or a blocked:architect SPEC change.
- S1.10: invariant-1 scan must also catch relative imports (`from .. import audit`).
- eval-replay is a placeholder until S1.9.
