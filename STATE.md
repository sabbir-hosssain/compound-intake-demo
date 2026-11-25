# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #5 S1.5 extraction v1 — draft PR, blocked:architect (RECORD needs a real ANTHROPIC_API_KEY)
Last merges: #4 S1.4 rules skeleton (PR #34, 0 rounds) · #3 S1.3 adapter (PR #32, 0) · #2 S1.2 seed (PR #31, 0) · #1 S1.1 schemas (PR #30, 0)
Blocked (architect): #5 RECORD step (key in builder env is a placeholder → 401) · #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: record #5 cassettes · S1.6 matcher · S1.7 audit v0
Notes:
- Rules: `RULES_VERSION="0.1.0"`; `run_pass1(text, existing)` (R1-01, R1-05), `run_pass2(extraction, known, existing)` (R2-01); passes return `[*existing, *new]`.
- Adapter: `ModelClient.complete(prompt_hash, system, user_input, tools=None)`; INTAKE_MODE replay|record|live; no temperature sent (#33).
- Extract: `extract(text, client=...) -> ExtractResult(status OK|MANUAL, extraction, prompt_versions, model_id, attempts, errors)`; strict tool `record_extraction`, tool_choice auto; one retry with `<validation_feedback>`; missing recording raises.
- To unblock #5: on branch `s1.5-extraction-v1`, with a real key: `INTAKE_MODE=record` + `extract()` on samples/case_001–003 (writes 3 files to eval/cassettes/), then `uv run pytest -q` in REPLAY and commit the cassettes.
- S1.6: `Flag.source_pass` is 1|2; M-01 needs a convention or a blocked:architect SPEC change.
- S1.10: invariant-1 scan must also catch relative imports (`from .. import audit`).
- eval-replay is a placeholder until S1.9.
