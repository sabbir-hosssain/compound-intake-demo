# STATE (rewritten after every issue; one screen max)
Milestone: M2 — golden set, baseline, metrics · Gate 2 · run started 2026-11-25 13:49Z
Active: #13 S2.3 all rules (code lane; merge held until S2.2 lands) · data lane: next is #12 S2.2
Last merges: #11 S2.1 formula library (PR #44) · #33 SPEC §7 (PR #43) · #9 S1.9 eval harness (PR #42) · #8 S1.8 CLI (PR #40) · #5 S1.5 extraction (PR #35)
Blocked (architect): none
Next up: #12 S2.2 golden set (data) · #14 S2.4 baseline (code) · #15 S2.5 metrics (code, dep S2.2–S2.4)
## M2 progress
- S2.1: 15 illustrative formulas (SHF-001…015), 5 near-twin pairs listed in data/formulas/README.md; 230 tests. Fix rounds 0.
- Carried from M1: #41 (atomic audit append; M3) · S2.7 adds `--runs` to run_eval · unsafe_flag_recall gate vacuous until S2.2.
- Live-model steps: `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
