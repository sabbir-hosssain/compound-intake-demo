# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #4 S1.4 rules skeleton (PR open, awaiting review)
Last merges: #3 S1.3 model adapter (PR #32, 0 rounds) · #2 S1.2 seed library (PR #31, 0) · #1 S1.1 schemas (PR #30, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.5 extraction v1 · S1.6 matcher (code lane, one at a time)
Notes:
- Rules: `run_pass1(text, existing)` / `run_pass2(extraction, known, existing)` return `[*existing, *new]`; `known = load_ingredient_names()`. `RULES_VERSION = "0.1.0"`. Only R1-01, R1-05, R2-01 so far (rest in S2.3).
- Adapter: `ModelClient.complete(prompt_hash, system, user_input, tools=None)`; INTAKE_MODE replay|record|live; cassettes eval/cassettes/<sha256>.json. No temperature sent (#33).
- S1.5: forced tool_choice (any/tool) 400s on Sonnet 5.5 — use `auto` + `strict: true`, or `output_config.format`. RECORD needs ANTHROPIC_API_KEY (exported in the architect's terminal).
- S1.6: `Flag.source_pass` is 1|2; M-01 needs a convention or a blocked:architect SPEC change.
- S1.10: invariant-1 scan must also catch relative imports (`from .. import audit`) — reviewer note on PR #32.
- Reviewer notes: keep `Proposal.flags` append-only; case_002 "up to 3 times daily" may trip R1-02.
- eval-replay is a placeholder until S1.9.
