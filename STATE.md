# STATE (rewritten after every issue; one screen max)
Milestone: M4 — publish · Gate 3 · started 2026-11-26
Active: #27 S4.4 DEMO.md (lane:code)
Last merges: #24 README (PR #90) · #28 final results (PR #88) · #69 explanation in CLI/demo/review (PR #86) · #62 + #23 `intake demo` (PR #83) · #57 S3.9 (PR #81)
Blocked (architect): none · #25 (ADRs, protected) will need `architect-approved` at Gate 3
Next up: #27 DEMO.md → #26 HARNESS.md → #25 ADRs · #64 last, cut first if late · #91 `make eval` overwrite (scope-question, Gate 3)
## M4 progress
- #69 (PR #86): reasons shown in `intake run`, `intake demo` and the review screen; pending audit record carries `reasons`. 5 live RECORD calls, 0 retries. 839 tests; REPLAY gates adversarial 10/10, unsafe 10/10, schema 64/64. 0 fix rounds.
- #28 (PR #88): final results `results/2026-11-26.md`, LIVE ×3 over 64 golden cases, 192 live calls, 0 retries. Gates 10/10 · 10/10 · 64/64 in all runs. Test top-1 16/19 (baseline 11/19); M-01 FA test 2/20 (REPLAY 3/20). Variance: any-measure 4/64, decisions 1/64. CI recordings unchanged (LIVE, not RECORD). No tag (Gate 3). 0 fix rounds.
- #24 (PR #90): README; every test-split cell pinned to `results/2026-11-26.md` by `tests/test_readme.py` (874 tests). README names the two cells where CI REPLAY differs (field acc 151/176 vs 153/176; M-01 FA 3/20 vs 2/20). 0 fix rounds. Orchestrator catch: #28 report missed the field-accuracy difference.
## M3 summary
- **Exit criterion:** a fresh clone of main with no API key and no .env runs `make demo`, which exits 0 and prints "3/3 demo cases match their fixtures (mode REPLAY)", writing no audit DB. On the same clone: 817 tests pass, and REPLAY `--enforce-gates` passes adversarial 10/10, unsafe recall 10/10, schema 64/64.
- **Issues:** 11 closed: #19 review screen · #20 audit chain + `intake audit verify` · #21 explanation v1 · #22 override metric (pinned) · #23 + #62 demo fixtures and `intake demo` · #41 atomic append (also fixed a chain fork and double review in `review.submit`) · #54–#57 Gate 2 follow-ups. Median fix rounds 0 (#23 took 2). 0 escalations.
- **Test split at M3 start → end** (locked golden set, REPLAY): top-1 16/19 → 16/19 (baseline 11/19) · M-01 false alarms 7/20 → 3/20 (dev 7/38 → 2/38) · M-01 recall 2/2 → 2/2 · unsafe recall 3/3 · adversarial 4/4 · NO_MATCH P 2/4, R 2/3 unchanged · simulated override 4/22 (baseline 9/22). Baseline M-01 recall fell 4/6 → 2/6 by design (#56).
- **Live calls:** 70 (58 explain recordings, 9 re-recorded after #56, 3 demo), 0 retries.
- **Known limits:** truncating the newest audit records still verifies; explanations aren't shown in the CLI or screen yet (#69); acknowledged REVIEW flags aren't stored (#64).
- Harness metrics and notes: docs/HARNESS.md (M3 row, "M3 notes").
