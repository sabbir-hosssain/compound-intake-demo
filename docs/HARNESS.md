# Harness report
How this repo was built: AI coding agents (Claude Code subagents) under an architect-defined harness. Design: docs/HARNESS_DESIGN.md.

| Milestone | Issues closed | Median fix rounds | Escalations | Reviewer catches | Hard-gate fails on main | Architect min | Wall-clock | Spend |
|---|---|---|---|---|---|---|---|---|
| M1 | 10 (+1 chore) | 0 | 2 (#5 API key, resolved; #33 SPEC §7, open) | 1 blocking (privacy: personal path in public doc, #39) · 8 non-blocking (weak invariant test, spec divergence, 2 test-coverage gaps, vacuous conditional test, non-atomic audit append, live-eval flag contract gap, stale PR body) | 0 | (architect to log) | ~1 h 20 min (03:30Z–04:50Z) | UNKNOWN (agent tokens not visible to the orchestrator; 5 Sonnet 5.5 recording calls) |
| M2 | 8 (#11–#18) | 0 (one issue took 1 round: #12) | 0 | 1 blocking (#45: schema-valid AC claimed but untested) · 5 non-blocking (test assertion weaker than its name, 3 file-list gaps with stated reasons, vague AC defined in the PR) · orchestrator catches: wrong case IDs in a data-author report, a reviewer report returned as "placeholder", 2 SPEC divergences left unaddressed by reviewers | 0 | (architect to log) | ~1 h 25 min (13:49Z–15:15Z) | UNKNOWN agent tokens; 240 live Sonnet 5.5 calls (60 record + 180 variance), 0 retries |
| M3 | | | | | | | | |
| M4 | | | | | | | | |

## What I'd change in the harness
(filled in at M4)

## M1 notes (orchestrator)
Harness defects found in the M1 run, and the fix applied:
1. **Reviewer reported actions that never reached GitHub (PR #40).** The reviewer said it had added `reviewer-approved` and a comment; neither existed, and the orchestrator merged on the report. Fix: the merge step now checks GitHub for the label *and* a verdict comment, and reviewer briefs ask it to re-read the PR after each gh write. A post-merge review approved #40 with no required fixes.
2. **Key validity not checked at start.** The orchestrator checked that `ANTHROPIC_API_KEY` was set, not that it was real (it was a 3-char placeholder), so S1.5 blocked mid-run. Fix: the architect's env-file rule (DECISIONS-LOG); check by length only, never by value.
3. **Personal path leaked into public docs** (STATE.md via PR #38, DECISIONS-LOG via PR #39) when copying the architect's instruction. Caught by the reviewer on #39 and fixed. Fix: committed text uses `<repo-root>`; builder briefs say so.
4. **Builders and the orchestrator both rewrite STATE.md**, which causes merge conflicts across parallel PRs. The orchestrator overwrites it on the PR branch before merging (one extra CI run per issue). Worth simplifying: builders should leave STATE.md alone.
5. **Labels re-trigger CI** (`protected-paths` listens to label events), so reviewers often saw "pending" jobs. Harmless, but merges wait for the re-run.
6. **Environment:** builder sandboxes refused shell commands containing the word "eval"; an orchestrator scratch worktree was deleted externally mid-run.

## M2 notes (orchestrator)
1. **Reviewers blocked on STATE.md** (PR #45, two rounds) because CLAUDE.md's definition of done doesn't say who rewrites it. Fix: DECISIONS-LOG row (orchestrator writes it at merge) and reviewer briefs say so; the CLAUDE.md wording is for the architect (protected).
2. **Agent-cited IDs can be wrong.** The S2.2 data-author listed uncertain cases by patient-ref numbers, not case IDs. Fix: the orchestrator verifies every cited case ID against the file before it goes into a packet.
3. **A reviewer's hand-back was the literal word "placeholder"** (PR #48). The M1 merge check (label + verdict comment on GitHub) showed the review had happened; the merge went on that evidence, not the report.
4. **PR-number-only reviewer briefs miss orchestrator concerns.** Reviewers didn't address the baseline-flag SPEC divergence (#48) or `ModelClient._live` (#50). The orchestrator checked both itself and queued them for Gate 2. Worth considering: let the orchestrator attach a "check also" list without its conclusions.
5. **Inferred dependencies:** #13 started before S2.2 with its merge held; that worked and kept the code lane busy, at the cost of one extra builder round-trip after S2.2 landed.
6. **Permission denial not proxied:** the S2.4 builder was denied `gh issue` writes and asked the orchestrator to make them; it refused and raised the denial for the architect.
7. **Environment:** label events still re-trigger CI (an extra run before every merge); the auto-mode classifier rejected some backgrounded commands after a directory change until they were re-issued unchanged.

8. **S2.9 (#53): a data change forced a test change.** The new dev cases moved the baseline cut-off plateau midpoint from 0.80 to 0.79, so the data-author rewrote a pinned test. The reviewer flagged it under invariant 6. The orchestrator didn't loop the data-author: the only "fixes" were weakening the test or fitting the data to it. It escalated to the architect in session, who accepted the change, recorded on the issue and in DECISIONS-LOG. Lesson: tests that pin a tuned value to a re-derivation break whenever the data grows; they should pin "the frozen value is still optimal". 1 round, 4 live calls.
