# PLAN — compound-intake-demo

Milestone → epic → story. Each **story becomes one GitHub issue**, with its acceptance criteria (AC) and lane copied in. Tasks are checklist items inside the issue. Sizes: S ≈ 1 agent session, M ≈ 2. `dep:` lists blocking stories. Lanes: `lane:code` (builder) and `lane:data` (data-author); at most one active issue per lane.

**Cut order if late:** S3.1 (screen → CLI review), then S2.7 (variance). Never cut M4.

---

## M0 — Harness and decision pack  ·  Gate 1
*Run by the setup chat (or terminal). These aren't created as issues; they're done directly.*
- **E0.1 Repo bootstrap.** Write every file in `05_Repo_Bootstrap_Pack.md`; `pyproject.toml` (uv, Python 3.12, ruff, pytest); the package layout `src/intake/`; `docs/SPEC.md`, `docs/PLAN.md`, `docs/HARNESS_DESIGN.md`; MIT license.
- **E0.2 CI.** `.github/workflows/ci.yml` with jobs `lint`, `test`, `eval-replay`, `redaction`, `protected-paths`. `live-eval.yml` is manual-only (`workflow_dispatch`).
- **E0.3 Harness.** `.claude/agents/*.md`, `.claude/settings.json` hooks, `.claude/hooks/protect_paths.py`, `.claude/protected-paths.txt`.
- **E0.4 GitHub setup.** Labels (see HARNESS_DESIGN §3), milestones M1–M4, one issue per story below.

**M0 exit:** CI is green on the skeleton · editing a protected path is blocked by the hook (shown in the PR description) and by CI · redaction fails on a planted test term in a throwaway branch · all M1–M4 issues exist · STATE.md is initialised · Gate 1 packet posted.

---

## M1 — Walking skeleton (one case end to end)
**E1.1 Foundations**
- **S1.1 Schemas** (code, S). Implement SPEC §4 models. *AC:* models import; round-trip JSON tests pass.
- **S1.2 Seed library** (data, S). 3 fictional non-sterile formulas plus an ingredient master. *AC:* loader validates them; every file has `illustrative: true`.
- **S1.3 Model adapter and recordings** (code, M). Anthropic client wrapper; REPLAY/RECORD/LIVE modes; recordings in `eval/cassettes/`. *AC:* in REPLAY, a missing recording raises; no network in CI.

**E1.2 Pipeline**
- **S1.4 Rules skeleton** (code, S, dep S1.1). Pass 1: R1-01, R1-05. Pass 2: R2-01. `RULES_VERSION`. *AC:* unit tests per rule; flags only ever added.
- **S1.5 Extraction v1** (code, M, dep S1.1, S1.3). `prompts/extract_v1.md` + `extract.py`; schema validation; the `MANUAL` fallback. *AC:* 3 recorded cases extract valid objects.
- **S1.6 Matcher** (code, S, dep S1.1, S1.2). SPEC §6 scoring; reads `eval/thresholds.yaml`. *AC:* deterministic tests on the seed formulas.
- **S1.7 Audit v0** (code, S, dep S1.1). Append-only insert; no update or delete API. *AC:* tests show there are no mutation functions.
- **S1.8 CLI** (code, S, dep S1.4–S1.7). `intake run <file>` prints the proposal and writes audit. *AC:* one sample runs end to end in REPLAY.

**E1.3 Evaluation spine**
- **S1.9 Eval harness v0** (code, M, dep S1.8). `eval/run_eval.py` over 5 seed cases; writes `results/`. *AC:* `eval-replay` job runs it in CI.
- **S1.10 Architecture test** (code, S). The LLM modules don't import `audit`. *AC:* the test fails if a forbidden import is added (shown in the test itself).

**M1 exit:** on `main`, `intake run` works on a sample in REPLAY; the eval runs in CI; all hard-gate jobs exist (passing on the current tiny set).

---

## M2 — Golden set, baseline, metrics  ·  Gate 2
**E2.1 Data** (data lane)
- **S2.1 Formula library** (data, M). 15 fictional non-sterile formulas, including 5 near-twin pairs (same actives, different base or strength), each with illustrative maxima. No GLP-1s, peptides, sterile or controlled items. *AC:* loader validates; a twin-pair list is in `data/formulas/README.md`.
- **S2.2 Golden set** (data, M, dep S2.1). ~60 cases per SPEC §8, stratified dev 40 / test 20, with realistic free-text patterns (truncated ingredient lists, missing units, "see notes", misuse of Notes, abbreviations). *AC:* schema-valid; the category counts are printed by a script.

**E2.2 Pipeline completion** (code lane)
- **S2.3 All rules** (code, M). The rest of SPEC §5 plus M-01. *AC:* one unit test per rule; the unsafe and adversarial dev cases flag correctly.
- **S2.4 Baseline matcher** (code, S). SPEC §6 baseline. *AC:* runs on the golden set in under 5 seconds.
- **S2.5 Metrics** (code, M, dep S2.2–S2.4). Every SPEC §8 metric, Wilson intervals, per split and per category, system vs baseline; the hard gates wired to the CI exit code. *AC:* a `results/` file is generated with all tables.
- **S2.6 Record recordings** (code, S, dep S2.5). One RECORD run over all 60 cases with the architect's key (run through the manual workflow or locally). *AC:* CI REPLAY covers the full set.
- **S2.7 Run-to-run variance** (code, S, cuttable). 3 LIVE runs; report the disagreement rate. *AC:* a section in the results.
- **S2.8 Threshold tuning** (code, S, dep S2.5). Grid search over T_match and T_margin **on dev only**; propose values in the Gate 2 packet. *AC:* the proposal file `eval/thresholds.proposed.yaml`; the architect applies it at Gate 2.

**M2 exit / Gate 2:** all hard gates pass on dev and test · the packet includes a 12-case random label sample for spot-checking, the proposed thresholds, and the system-vs-baseline table. **After Gate 2, the architect creates `data/golden/LOCKED` and the golden labels become protected.**

---

## M3 — Review screen, audit chain, reasons
- **S3.1 Review screen** (code, M, cuttable → CLI). SPEC §9. *AC:* BLOCK disables CONFIRM; REVIEW needs acknowledgment; the actions write ReviewActions.
- **S3.2 Hash-chained audit and verify** (code, S). SPEC §10. *AC:* a tamper test detects a modified record.
- **S3.3 Explanation v1** (code, S). `prompts/explain_v1.md`; the reasons cite component scores and flags; the explanation cannot change candidates or flags (a test checks this). *AC:* recorded for the full set.
- **S3.4 Simulated override metric** (code, S). *AC:* in the results, labelled "simulated".
- **S3.5 Demo fixtures** (data, S). Three showcase cases: clean, unsafe, injection. *AC:* `make demo` walks through them in REPLAY.

**M3 exit:** `make demo` works from a fresh clone with no API key.

---

## M4 — Publish  ·  Gate 3
- **S4.1 README** (code, M). Problem → principle → flow diagram (Mermaid) → what the AI does and doesn't do → results table (test split, CIs, baseline) → design decisions (ADR links) → limitations (SPEC §11 verbatim) → run instructions → credit line. *AC:* the honesty checklist in START_HERE §6 passes.
- **S4.2 ADRs final** (code, S). Status set to Accepted; consequences updated with the measured results. *Architect-approved PR, because ADRs are protected.*
- **S4.3 HARNESS.md** (code, S). Per-milestone metrics from STATE.md history.
- **S4.4 DEMO.md** (code, S). A 3–5 minute walkthrough script for the showcase cases.
- **S4.5 Final results** (code, S). Fresh RECORD/LIVE run; final `results/` file; tag `v0.1`.

**M4 exit / Gate 3:** the architect reads the README and DEMO.md, then makes the repo public.

---

## Issue template (used for every story)
```
Title: [S1.5] Extraction v1
Labels: lane:code, ready, M1
Milestone: M1
## Goal
<one sentence>
## Acceptance criteria
- [ ] ...
## Files expected to change
- src/intake/extract.py, prompts/extract_v1.md, tests/test_extract.py
## Out of scope
- ...
## Dependencies
- S1.1, S1.3
<details><summary>Agent notes</summary>

<builder plan and attempt log go here>
</details>
```
