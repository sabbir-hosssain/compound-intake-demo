# STATE (rewritten after every issue; one screen max)
Milestone: M3 — review screen, audit chain, reasons · **COMPLETE — exit criteria pass on main** (2026-11-26, main 593e4bf)
Active: none
Last merges: #62 + #23 `intake demo` (PR #83) · #57 S3.9 (PR #81) · #56 S3.8 (PR #79) · #55 S3.7 (PR #77) · #54 S3.6 (PR #75)
Blocked (architect): none · M3 items decided 2026-11-26 (#56 confirmed; allow rules for eval commands; reviewer quotes head SHA; DECISIONS-LOG)
Next up: M4 — #69 explanation in CLI/demo/review first, then #24–#28; #64 acknowledged flags (cut first if late) → Gate 3
## M3 summary
- **Exit criterion:** a fresh clone of main with no API key and no .env runs `make demo`, which exits 0 and prints "3/3 demo cases match their fixtures (mode REPLAY)", writing no audit DB. On the same clone: 817 tests pass, and REPLAY `--enforce-gates` passes adversarial 10/10, unsafe recall 10/10, schema 64/64.
- **Issues:** 11 closed: #19 review screen · #20 audit chain + `intake audit verify` · #21 explanation v1 · #22 override metric (pinned) · #23 + #62 demo fixtures and `intake demo` · #41 atomic append (also fixed a chain fork and double review in `review.submit`) · #54–#57 Gate 2 follow-ups. Median fix rounds 0 (#23 took 2). 0 escalations.
- **Test split at M3 start → end** (locked golden set, REPLAY): top-1 16/19 → 16/19 (baseline 11/19) · M-01 false alarms 7/20 → 3/20 (dev 7/38 → 2/38) · M-01 recall 2/2 → 2/2 · unsafe recall 3/3 · adversarial 4/4 · NO_MATCH P 2/4, R 2/3 unchanged · simulated override 4/22 (baseline 9/22). Baseline M-01 recall fell 4/6 → 2/6 by design (#56).
- **Live calls:** 70 (58 explain recordings, 9 re-recorded after #56, 3 demo), 0 retries.
- **Known limits:** truncating the newest audit records still verifies; explanations aren't shown in the CLI or screen yet (#69); acknowledged REVIEW flags aren't stored (#64).
- Harness metrics and notes: docs/HARNESS.md (M3 row, "M3 notes").
