# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton · **COMPLETE** (exit criteria pass; run 2026-11-25 03:30Z → ~04:50Z)
Active: none
Last merges: #9 S1.9 eval harness (PR #42) · #8 S1.8 CLI (PR #40) · #5 S1.5 extraction (PR #35) · #39 chore · #10 S1.10 arch test (PR #38)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: M2 — S2.1 formula library (data) · S2.3 all rules (code) · S2.4 baseline (code)
## M1 summary
- Exit criteria, checked on the final tree: `uv run intake run samples/case_001.txt` (REPLAY) → PROPOSED SHF-001, one pending audit record · `eval-replay` CI runs `eval.run_eval --mode replay --enforce-gates` (adversarial 1/1, schema 5/5, unsafe n/a) · required jobs lint/test/eval-replay/redaction/protected-paths all exist and pass · 225 tests.
- 10/10 M1 issues closed + 1 chore PR (#39). Median fix rounds 0. Escalations 2 (#5 key: resolved by architect; #33 open).
- Follow-ups: #41 (atomic audit append, vacuous CLI test; M3) · S2.7 must add `--runs` to run_eval for live-eval.yml · unsafe_flag_recall gate is vacuous until S2.2 · R1-03 lands in S2.3 (case_004 recall 2/3 until then).
- Harness defects: see docs/HARNESS.md "M1 notes".
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …` (5 recording calls total in M1).
