# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · **COMPLETE — stopped at Gate 2** (run 2026-11-25 13:49Z → ~15:15Z)
Active: none · waiting on the architect (Gate 2)
Last merges: #18 S2.8 threshold tuning (PR #51) · #17 S2.7 variance (PR #50) · #16 S2.6 recordings (PR #49) · #15 S2.5 metrics (PR #48) · #14 S2.4 baseline (PR #47)
Blocked (architect): Gate 2 — see docs/gate2-packet.md §2 (10 decisions)
Next up: Gate 2 → apply thresholds, label fixes, `data/golden/LOCKED` → M3 (review screen, audit chain, reasons)
## M2 summary
- Exit criteria on the final tree: every hard gate passes on dev and test (REPLAY, 60 golden cases): adversarial 6/6 + 4/4, unsafe recall 7/7 + 3/3, schema 60/60; CI runs the golden set by default. Packet: docs/gate2-packet.md (12-case sample, proposed thresholds, system-vs-baseline table).
- 8/8 issues closed (#11–#18, PRs #44–#51). Median fix rounds 0 (#12 took 1). Escalations 0. 521 tests.
- Headline: unsafe-flag recall 10/10 vs baseline 2/10; top-1 dev 30/35 = baseline, test 14/17 vs 11/17; weak spots are ambiguous cases and M-01 false alarms from score ties.
- Live calls: 240 (60 record, 180 variance). Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
- Carried: #41 (atomic audit append; M3). Harness notes: docs/HARNESS.md "M2 notes".
