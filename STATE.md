# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: none (code lane next: #18 S2.8) · data lane: no M2 issues left
Last merges: #16 S2.6 recordings (PR #49) · #15 S2.5 metrics (PR #48) · #14 S2.4 baseline (PR #47) · #13 S2.3 all rules (PR #46) · #12 S2.2 golden set (PR #45)
Blocked (architect): none
Next up: #18 S2.8 threshold tuning (dev only; proposal file) · #17 S2.7 variance (cuttable; ~180 live calls) · then Gate 2 packet
## M2 progress
- S2.1 formulas (0 rounds) · S2.2 golden set, 60 cases (1 round) · S2.3 all rules (0) · S2.4 baseline, cut-off 0.80 (0) · S2.5 metrics, Wilson CIs (0) · S2.6 recordings (0).
- S2.6: 60 live calls, 0 retries. CI REPLAY now runs all 60 golden cases by default (seed set covered by pytest). Hard gates: adversarial 10/10, unsafe 10/10, schema 60/60.
- Headline (system vs baseline): top-1 dev 30/35 vs 30/35, test 14/17 vs 11/17; unsafe recall dev 7/7 vs 1/7. Weak spots: ambiguous top-1 8/13 vs 10/13; M-01 false alarms dev 7/38, test 7/20.
- For Gate 2: baseline flag definition (SPEC §6 divergence), R1-04 list / R2-04 / R2-05 constants and baseline cut-off outside thresholds.yaml, uncertain golden labels, CLAUDE.md DoD wording on STATE.md.
- Carried: #41 (atomic audit append; M3) · S2.7 adds `--runs` to run_eval.
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`. M2 live calls so far: 60.
