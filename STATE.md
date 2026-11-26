# STATE (rewritten after every issue; one screen max)
Milestone: M3 — review screen, audit chain, reasons · **IN PROGRESS** (started 2026-11-26)
Active: code #20 S3.2 hash-chained audit (builder) · data #23 S3.5 demo fixtures (PR #61, fix round 1, in re-review)
Last merges: #19 S3.1 review screen (PR #63) · Gate 2 lock (PR #60) · #53 close-out (PR #59) · #53 S2.9 (PR #58) · Gate 2 (PR #52)
Blocked (architect): none
Next up (code): #21 S3.3 explanation (live RECORD) · #22 S3.4 override metric · #41 atomic audit append (after #20) · #54–#57 Gate 2 follow-ups · #62 `intake demo` + demo recordings (after #61) · #64 acknowledged_flags (after #20)
## M3 start: locked golden set, REPLAY `--enforce-gates` on main 0fd0456
- Hard gates: adversarial 10/10, unsafe recall 10/10, schema 64/64.
- Test split (22): top-1 16/19 (baseline 11/19) · top-3 17/19 (13/19) · unsafe recall 3/3 (1/3) · adversarial 4/4 · M-01 recall 2/2 · M-01 false alarms 7/20 (6/20) · NO_MATCH precision 2/4, recall 2/3 · simulated override 4/22 (9/22) · fields 151/176.
## #19 S3.1 (PR #63)
- Streamlit screen over `src/intake/review.py`. BLOCK disables CONFIRM (enforced in UI, build and submit). Every REVIEW flag must be acknowledged. Fixed reason codes per action. A review appends a chained record. 567 tests. 0 fix rounds.
- Gap: acknowledged flags are not stored, so #64 was filed. The CLI fallback was not built because the screen is done.
## Harness notes (for HARNESS.md)
- PR #61: tests the data-author can't write were added by a builder on the same branch. They caught a tie (M-01) in the unsafe fixture, which was replaced with a clear-match case.
- The plain `gh pr merge --squash` is refused by base-branch policy; `--auto` works.
- The worktree guard refuses Bash commands containing "eval" and chained/heredoc commands (data-author report).
- PR #63 reviewer did not read the whole test diff; it relied on the test run and the builder's mutation check.
