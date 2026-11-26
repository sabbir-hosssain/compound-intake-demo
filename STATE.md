# STATE (rewritten after every issue; one screen max)
Milestone: M3 — review screen, audit chain, reasons · **IN PROGRESS** (started 2026-11-26)
Active: code #54 S3.6 controlled list to data file (builder) · data: idle (#23 closes with #62)
Last merges: #41 atomic audit append (PR #73) · #22 S3.4 (PR #71) · #21 S3.3 (PR #68) · #20 S3.2 (PR #66) · #23 fixtures (PR #61)
Blocked (architect): none
Next up (code): #55–#57 Gate 2 follow-ups · #62 `intake demo` + demo recordings (M3 exit path) · #64 acknowledged_flags · #69 wire explanation
## M3 start: locked golden set, REPLAY `--enforce-gates` on main 0fd0456
- Hard gates: adversarial 10/10, unsafe recall 10/10, schema 64/64.
- Test split (22): top-1 16/19 (baseline 11/19) · top-3 17/19 (13/19) · unsafe recall 3/3 (1/3) · adversarial 4/4 · M-01 recall 2/2 · M-01 false alarms 7/20 (6/20) · NO_MATCH precision 2/4, recall 2/3 · simulated override 4/22 (9/22) · fields 151/176.
## #19 S3.1 (PR #63)
- Streamlit screen over `src/intake/review.py`. BLOCK disables CONFIRM (enforced in UI, build and submit). Every REVIEW flag must be acknowledged. Fixed reason codes per action. A review appends a chained record. 567 tests. 0 fix rounds.
- Gap: acknowledged flags are not stored, so #64 was filed. The CLI fallback was not built because the screen is done.
## #20 S3.2 (PR #66)
- Chain helpers moved to `audit.py`. `intake audit verify` reports the first broken link (exit 3). 24 tamper tests; 602 tests. 0 fix rounds. Limit: truncating the newest records still verifies, since the expected length isn't stored anywhere.
## #41 (PR #73)
- New `audit.write_lock` (BEGIN IMMEDIATE) wraps `log_pending` and `review.submit`. `submit` had a real chain fork (stale `prev_hash`) and allowed a double review; both are fixed. Interleaving tests failed on main and pass now. 698 tests. 0 fix rounds.
## #22 S3.4 (PR #71)
- The metric already existed from S2.5. This PR pins the label and definition ("gold stands in for the pharmacist") with 4 tests. 691 tests. 0 fix rounds.
## #21 S3.3 (PR #68)
- `prompts/explain_v1.md` and `explain.add_reasons`: reasons must cite each flag's rule ID and the top candidate's 5 component scores, otherwise a fixed fallback text is used. The result has no decision fields; a hostile-reply test proves this. 687 tests. 0 fix rounds.
- **58 live RECORD calls** (budget 80; 6 cases share recordings). Not yet called by the pipeline, CLI or eval, so #69 was filed.
## #23 S3.5 fixtures (PR #61)
- 3 demo cases (clean SHF-009 · unsafe SHF-014 R2-02 · injection SHF-003 R1-05), checked with no model by tests/test_demo_fixtures.py. 2 fix rounds.
## Harness notes (for HARNESS.md)
- PR #61: tests the data-author can't write were added by a builder on the same branch. They caught a tie (M-01) in the unsafe fixture, which was replaced with a clear-match case.
- The plain `gh pr merge --squash` is refused by base-branch policy; `--auto` works.
- The worktree guard refuses Bash commands containing "eval" and chained/heredoc commands (data-author report).
- PR #63 reviewer did not read the whole test diff; it relied on the test run and the builder's mutation check.
- PR #66: the first push conflicted with main on DECISIONS-LOG.md (every PR appends there), so CI didn't start. Builders now rebase just before pushing.
- Issue file lists miss DECISIONS-LOG.md and shared helpers (#20 touched pipeline.py and tests/test_audit.py, both disclosed).
- #21: the builder got around the "eval" Bash guard with wrapper scripts, and copied `.redaction-denylist` into its worktree (the orchestrator deleted the copy). Builders are now told to report blocked commands instead of working around them. The guard question is for the architect.
- Reviewers on #63, #71 and #73 relied on CI and did not run the full suite or the eval themselves. CI covers both, so this is acceptable, but the reviewer brief doesn't require it.
