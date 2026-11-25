# Harness report
How this repo was built: AI coding agents (Claude Code subagents) under an architect-defined harness. Design: docs/HARNESS_DESIGN.md.

| Milestone | Issues closed | Median fix rounds | Escalations | Reviewer catches | Hard-gate fails on main | Architect min | Wall-clock | Spend |
|---|---|---|---|---|---|---|---|---|
| M1 | 10 (+1 chore) | 0 | 2 (#5 API key, resolved; #33 SPEC §7, open) | 1 blocking (privacy: personal path in public doc, #39) · 8 non-blocking (weak invariant test, spec divergence, 2 test-coverage gaps, vacuous conditional test, non-atomic audit append, live-eval flag contract gap, stale PR body) | 0 | (architect to log) | ~1 h 20 min (03:30Z–04:50Z) | UNKNOWN (agent tokens not visible to the orchestrator; 5 Sonnet 5.5 recording calls) |
| M2 | | | | | | | | |
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

