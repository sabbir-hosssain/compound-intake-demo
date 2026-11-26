# STATE (rewritten after every issue; one screen max)
Milestone: M3 — review screen, audit chain, reasons · **IN PROGRESS** (started 2026-11-26)
Active: code #55 S3.7 constants from config/data (builder) · data: idle (#23 closes with #62)
Last merges: #54 S3.6 (PR #75) · #41 (PR #73) · #22 S3.4 (PR #71) · #21 S3.3 (PR #68) · #20 S3.2 (PR #66)
Blocked (architect): none
Next up (code): #56 M-01 not on NO_MATCH · #57 public max_retries · #62 `intake demo` + demo recordings (**M3 exit path**) · then #64 acknowledged_flags, #69 wire explanation
## M3 start: REPLAY `--enforce-gates`, locked golden set (main 0fd0456)
- Gates: adversarial 10/10, unsafe recall 10/10, schema 64/64. Test split (22): top-1 16/19 (baseline 11/19) · top-3 17/19 (13/19) · unsafe recall 3/3 (1/3) · M-01 recall 2/2 · M-01 false alarms 7/20 (6/20) · NO_MATCH P 2/4, R 2/3 · simulated override 4/22 (9/22) · fields 151/176.
## Merged so far (all 0 fix rounds unless noted)
- #19 review screen (PR #63): BLOCK disables CONFIRM in UI, build and submit; REVIEW flags need acknowledging; fixed reason codes per action. Gap → #64.
- #23 demo fixtures (PR #61, 2 rounds): clean SHF-009 · unsafe SHF-014 R2-02 · injection SHF-003 R1-05, checked with no model. `make demo` → #62.
- #20 audit chain (PR #66): `intake audit verify`, 24 tamper tests. Truncating the newest records still verifies (no stored length).
- #21 explanation (PR #68): reasons cite flags and scores, can't change decisions. **58 live calls**. Not yet wired in → #69.
- #22 override metric (PR #71): already existed; label and definition now pinned by tests.
- #41 (PR #73): `audit.write_lock` for `log_pending` and `review.submit`; fixed a real chain fork and a double review in `submit`.
- #54 (PR #75): R1-04 list in `data/rules/controlled_terms.yaml`; golden results identical before and after. 711 tests.
## Harness notes (for HARNESS.md)
- Plain `gh pr merge` is refused by policy; `--auto` works. "Closes #N" sometimes doesn't close the issue, so the orchestrator closes it.
- The worktree guard refuses Bash containing "eval" (even in paths) and chained commands. The #21 builder used wrapper scripts to get around it, and copied `.redaction-denylist` into its worktree (the copy is deleted). Builders are now told to report blocks instead. The guard config is for the architect.
- DECISIONS-LOG.md conflicts on every PR (#66), so builders rebase just before pushing. Issue file lists miss DECISIONS-LOG.md and shared helpers.
- Data-lane PRs needing tests: a builder adds the tests on the same branch (#61 caught a tie this way).
- Reviewers usually rely on CI rather than re-running the suite. `ruff format --check` drifts on main, and CI runs only `ruff check`.
