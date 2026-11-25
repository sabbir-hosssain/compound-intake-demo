# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: none (code lane next: #18 S2.8, last M2 issue) · data lane: no M2 issues left
Last merges: #17 S2.7 variance (PR #50) · #16 S2.6 recordings (PR #49) · #15 S2.5 metrics (PR #48) · #14 S2.4 baseline (PR #47) · #13 S2.3 all rules (PR #46)
Blocked (architect): none
Next up: #18 S2.8 threshold tuning (dev only → eval/thresholds.proposed.yaml) · then the Gate 2 packet
## M2 progress
- S2.1 formulas (0 rounds) · S2.2 golden set (1) · S2.3 all rules (0) · S2.4 baseline (0) · S2.5 metrics (0) · S2.6 recordings (0) · S2.7 variance (0).
- Hard gates on golden REPLAY: adversarial 10/10, unsafe 10/10, schema 60/60. Top-1 dev 30/35 sys vs 30/35 base; test 14/17 vs 11/17.
- S2.7: 3 LIVE runs, 180 calls. Disagreement: decision 1/60 (g019), flags 1/60, fields 5/480, any 4/60. `run_eval --runs N` added (live-eval.yml contract closed).
- For Gate 2: baseline flag definition (SPEC §6 divergence); R1-04 list / R2-04 / R2-05 constants and baseline cut-off outside thresholds.yaml; eval/ sets ModelClient._live to disable SDK retries; uncertain golden labels; CLAUDE.md DoD wording on STATE.md.
- Carried: #41 (atomic audit append; M3).
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`. M2 live calls: 240.
