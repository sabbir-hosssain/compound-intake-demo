# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: none (code lane next: #16 S2.6, needs the live key) · data lane: no M2 issues left
Last merges: #15 S2.5 metrics (PR #48) · #14 S2.4 baseline (PR #47) · #13 S2.3 all rules (PR #46) · #12 S2.2 golden set (PR #45) · #11 S2.1 formula library (PR #44)
Blocked (architect): none
Next up: #16 S2.6 recordings (live, all 60 golden cases) · #18 S2.8 threshold tuning (dep S2.5) · #17 S2.7 variance (cuttable)
## M2 progress
- S2.1: 15 illustrative formulas, 5 near-twin pairs. Fix rounds 0.
- S2.2: 60 golden cases (25/15/10/10; dev 40 / test 20; 8 NO_MATCH). Fix rounds 1.
- S2.3: all SPEC §5 rules + M-01; 13/13 dev unsafe/adversarial cases flag and block on gold extraction. Fix rounds 0.
- S2.4: rapidfuzz baseline, NO_MATCH cut-off 0.80 (dev). Fix rounds 0.
- S2.5: every SPEC §8 metric with Wilson 95% CI, per split/category, system vs baseline; `--cases` selects the golden set (REPLAY exits 2 until S2.6 records it). Default case set is still the seed set. Fix rounds 0.
- For S2.6: recordings are keyed on raw.text + "\n" + raw.notes; switch the run_eval default to the golden set once recorded.
- For Gate 2: baseline given pass-1 rules + M-01 (SPEC §6 says no flags); R1-04 list / R2-04 / R2-05 constants and the baseline cut-off live outside thresholds.yaml; uncertain golden labels.
- Carried from M1: #41 (atomic audit append; M3) · S2.7 adds `--runs` to run_eval.
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
