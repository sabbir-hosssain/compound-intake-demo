# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · **COMPLETE — stopped at Gate 2**; pre-lock fix #53 merged 2026-11-26 (PR #58)
Active: none · **Waiting on the architect to review g061–g064, then create `data/golden/LOCKED`**
Last merges: #53 S2.9 pre-lock golden fixes (PR #58) · Gate 2 (PR #52) · #18 S2.8 (PR #51) · #17 S2.7 (PR #50) · #16 S2.6 (PR #49)
Blocked (architect): none · Architect decisions on #53: cutoff-test change accepted; g062 [R2-04, M-01] and the g062/g064 exact ties accepted (DECISIONS-LOG)
Next up: architect creates `data/golden/LOCKED` → M3 (incl. Gate 2 follow-ups: controlled list file, constants from config, M-01 not on NO_MATCH, public max_retries)
## S2.9 (#53)
- Golden set is now 64 cases (dev 42, test 22). g056 labelled R1-01, R1-05, R2-04, R2-05. g061–g064 are new ambiguous M-01 cases.
- REPLAY `--enforce-gates`: adversarial 10/10, unsafe recall 10/10, schema 64/64. Ambiguity recall dev 4/4, test 2/2. 525 tests.
- 4 live calls (one RECORD per new case). 1 fix round (the reviewer flagged a weakened test, resolved by an architect decision).
## M2 summary
- Exit criteria on the final tree: every hard gate passes on dev and test (REPLAY, 60 golden cases): adversarial 6/6 + 4/4, unsafe recall 7/7 + 3/3, schema 60/60; CI runs the golden set by default. Packet: docs/gate2-packet.md (12-case sample, proposed thresholds, system-vs-baseline table).
- 8/8 issues closed (#11–#18, PRs #44–#51). Median fix rounds 0 (#12 took 1). Escalations 0. 521 tests.
- Headline: unsafe-flag recall 10/10 vs baseline 2/10; top-1 dev 30/35 = baseline, test 14/17 vs 11/17; weak spots are ambiguous cases and M-01 false alarms from score ties.
- Live calls: 240 (60 record, 180 variance). Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
- Carried: #41 (atomic audit append; M3). Harness notes: docs/HARNESS.md "M2 notes".
