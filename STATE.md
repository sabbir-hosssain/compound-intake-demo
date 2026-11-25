# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: #13 S2.3 all rules (PR #46, code lane; review after S2.2 merges) · data lane: idle (S2.1, S2.2 done)
Last merges: #12 S2.2 golden set (PR #45) · #11 S2.1 formula library (PR #44) · #33 SPEC §7 (PR #43) · #9 S1.9 eval harness (PR #42) · #8 S1.8 CLI (PR #40)
Blocked (architect): none
Next up: #14 S2.4 baseline (code) · #15 S2.5 metrics (code, dep S2.2–S2.4) · #16 S2.6 recordings (code)
## M2 progress
- S2.1: 15 illustrative formulas, 5 near-twin pairs (data/formulas/README.md). Fix rounds 0.
- S2.2: 60 golden cases in data/golden/golden_cases.jsonl — clean 25 / ambiguous 15 / unsafe 10 / adversarial 10, dev 40 / test 20, 8 NO_MATCH; schema test added. Fix rounds 1. Uncertain labels (g026, g027, g031, g038, g041, g042, g045–g050, g054, g016/g017/g025) queued for the Gate 2 spot-check.
- `unsafe_flag_recall` is no longer vacuous once S2.5 points the eval at the golden set (CI still evaluates the seed set until S2.6 records it).
- Carried from M1: #41 (atomic audit append; M3) · S2.7 adds `--runs` to run_eval.
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
