# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: none (code lane next: #14 S2.4) · data lane: no M2 issues left
Last merges: #13 S2.3 all rules (PR #46) · #12 S2.2 golden set (PR #45) · #11 S2.1 formula library (PR #44) · #33 SPEC §7 (PR #43) · #9 S1.9 eval harness (PR #42)
Blocked (architect): none
Next up: #14 S2.4 baseline (code) · #15 S2.5 metrics (code, dep S2.2–S2.4) · #16 S2.6 recordings (code, dep S2.5)
## M2 progress
- S2.1: 15 illustrative formulas, 5 near-twin pairs. Fix rounds 0.
- S2.2: 60 golden cases (25/15/10/10; dev 40 / test 20; 8 NO_MATCH), schema test. Fix rounds 1. Uncertain labels queued for the Gate 2 spot-check.
- S2.3: all SPEC §5 rules + M-01 tests; RULES_VERSION 0.2.0; 13/13 dev unsafe/adversarial cases flag and block (gold-extraction check). Fix rounds 0. pipeline.py wired for pass-2 rules.
- For S2.5: the eval must feed raw.text + raw.notes (Notes-only triggers g042, g052, g056). unsafe_flag_recall stays n/a until the eval reads the golden set.
- For Gate 2: R1-04 controlled list (illustrative, in rules.py) and R2-04/R2-05 constants are outside thresholds.yaml; g056 label may lack R2-04/R2-05.
- Carried from M1: #41 (atomic audit append; M3) · S2.7 adds `--runs` to run_eval.
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
