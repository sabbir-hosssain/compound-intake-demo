# STATE (rewritten after every issue; one screen max)
Milestone: M4 — publish · **Gate 3 decided** (2026-11-26) — release PR open; then tag v0.1 and go public
Active: none
Last merges: #64 acknowledged flags (PR #97) · #26 HARNESS.md (PR #95) · #27 DEMO.md (PR #93) · #24 README (PR #90) · #28 final results (PR #88)
Blocked (architect): none · Gate 3 decided 2026-11-26 (DECISIONS-LOG)
Next up: tag v0.1 → architect makes the repo public · v0.1.1: #91
## M4 summary
- **State of main:** a fresh clone with no API key and no .env: `make demo` exits 0 with "3/3 demo cases match their fixtures (mode REPLAY)" and writes no audit DB; 900 tests pass; ruff clean; REPLAY `--enforce-gates` passes adversarial 10/10, unsafe recall 10/10, schema 64/64. Local redaction check clean (19 terms).
- **Issues:** 6 closed: #69 explanation in CLI/demo/review · #28 final results (LIVE ×3, no tag) · #24 README · #27 DEMO.md · #26 HARNESS.md · #64 acknowledged flags. Median fix rounds 0 (#26 took 1). 1 escalation (#25, structural: protected path).
- **Final results** (`results/2026-11-26.md`, LIVE run 1 of 3, test split): top-1 16/19 (baseline 11/19) · top-3 17/19 (13/19) · field acc 153/176 (REPLAY 151/176) · M-01 recall 2/2, false alarms 2/20 (REPLAY 3/20) · unsafe 3/3 · adversarial 4/4 · NO_MATCH P 2/4, R 2/3 · simulated override 4/22 (9/22). Variance: decision 1/64, flags 1/64, fields 4/512.
- **Live calls:** 197 (5 explain RECORD, 192 LIVE), 0 retries. CI recordings unchanged by #28.
- **Known limits:** truncating the newest audit records still verifies; `make eval` same day overwrites the committed results file (#91).
- Harness metrics and notes: docs/HARNESS.md (M4 row, "M4 notes").
## M3 summary
- **Exit criterion:** a fresh clone of main with no API key and no .env runs `make demo`, which exits 0 and prints "3/3 demo cases match their fixtures (mode REPLAY)", writing no audit DB. On the same clone: 817 tests pass, and REPLAY `--enforce-gates` passes adversarial 10/10, unsafe recall 10/10, schema 64/64.
- **Issues:** 11 closed: #19 review screen · #20 audit chain + `intake audit verify` · #21 explanation v1 · #22 override metric (pinned) · #23 + #62 demo fixtures and `intake demo` · #41 atomic append (also fixed a chain fork and double review in `review.submit`) · #54–#57 Gate 2 follow-ups. Median fix rounds 0 (#23 took 2). 0 escalations.
- **Test split at M3 start → end** (locked golden set, REPLAY): top-1 16/19 → 16/19 (baseline 11/19) · M-01 false alarms 7/20 → 3/20 (dev 7/38 → 2/38) · M-01 recall 2/2 → 2/2 · unsafe recall 3/3 · adversarial 4/4 · NO_MATCH P 2/4, R 2/3 unchanged · simulated override 4/22 (baseline 9/22). Baseline M-01 recall fell 4/6 → 2/6 by design (#56).
- **Live calls:** 70 (58 explain recordings, 9 re-recorded after #56, 3 demo), 0 retries.
- **Known limits:** truncating the newest audit records still verifies; explanations aren't shown in the CLI or screen yet (#69); acknowledged REVIEW flags aren't stored (#64).
- Harness metrics and notes: docs/HARNESS.md (M3 row, "M3 notes").
