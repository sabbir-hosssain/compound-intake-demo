# HARNESS DESIGN — how the agents build compound-intake-demo

> Copied to `docs/HARNESS_DESIGN.md` in M0. Protected after Gate 1.
> Principle: **the gate goes where the irreversibility is.** The harness applies to itself the same rule the product applies to the model.

## 1. Roles (Claude Code subagents in `.claude/agents/`)
| Role | Does | Never does | Model (start) |
|---|---|---|---|
| **orchestrator** | Picks the next `ready` issue per lane, dispatches builder and reviewer, merges, updates STATE.md and HARNESS.md, stops at stop conditions | Writes product code; edits protected paths | sonnet |
| **builder** | One issue, one branch (`s1-5-extraction`), tests first, opens a PR with an AC checklist | Touches files outside the issue's list without logging why; edits tests to make them pass loosely; edits protected paths | default (strongest available) |
| **reviewer** | Fresh context. Checks the PR against the AC, SPEC invariants, and §5 below. Verdict: `reviewer-approved` label + comment, or a change request with a numbered list | Writes code; approves its own fixes | sonnet |
| **data-author** | Formulas, golden cases, fixtures in `data/` | Writes code; reads `src/` to fit labels to behaviour | sonnet |

*(INFERENCE: the agents share one GitHub identity, so they can't formally approve their own PRs. The reviewer's verdict is the `reviewer-approved` label plus a comment.)*

## 2. The loop
```
orchestrator: read STATE.md → pick next ready issue (lane-aware, dependencies met)
  → label in-progress → builder (worktree/branch) → PR
  → CI → reviewer (fresh) → [changes? → builder, attempt += 1]
  → green + reviewer-approved → squash auto-merge → close issue
  → rewrite STATE.md → log metrics → next
```
- **Retries:** at most 2 fix rounds per issue. On the 3rd failure: label `blocked:architect`, write the options and a recommendation in the issue, and move on.
- **Parallelism:** at most one active issue in `lane:code` and one in `lane:data`, in separate worktrees.
- **Merge:** squash; the commit message includes the issue number. Branch protection requires `lint`, `test`, `eval-replay`, `redaction` and `protected-paths`.

## 3. GitHub labels
`ready` · `in-progress` · `needs-review` · `reviewer-approved` · `changes-requested` · `blocked:architect` · `scope-question` · `architect-approved` (only the architect applies this) · `lane:code` · `lane:data` · `M1` … `M4`

## 4. Stop conditions (orchestrator halts and writes a summary)
1. The milestone's exit criteria pass on `main`.
2. A gate is reached (M0, M2, M4).
3. The spend or turn cap for the run is reached (start: ~150 turns or 3 hours per milestone run; INFERENCE, adjust after M1).
4. Every remaining issue in the milestone is blocked.
5. Any hard-gate failure on `main` itself; fixing `main` comes before new issues.

## 5. Gates
**Deterministic (machines):**
| Gate | Mechanism |
|---|---|
| Protected paths | Hook `.claude/hooks/protect_paths.py` blocks Edit/Write on globs in `.claude/protected-paths.txt`. CI job `protected-paths` fails any PR touching them unless it has the `architect-approved` label |
| Locked golden labels | After Gate 2, `data/golden/LOCKED` exists; the hook and CI then treat `data/golden/**` as protected |
| Redaction | `scripts/redaction_check.py` scans tracked files for terms from `REDACTION_DENYLIST` (CI secret) or `.redaction-denylist` (local, gitignored). Fails closed if neither source is present in CI |
| Product invariants | Architecture test (no write path), hard eval gates (SPEC §8) |

**Protected paths (start):** `docs/SPEC.md`, `docs/adr/**`, `docs/HARNESS_DESIGN.md`, `CLAUDE.md`, `eval/thresholds.yaml`, `.claude/settings.json`, `.claude/hooks/**`, `.claude/protected-paths.txt`, `.claude/agents/**`, `.github/workflows/**`, `scripts/redaction_check.py`, and `data/golden/**` once LOCKED exists.

**Human (architect):** Gate 1 (decision pack, harness), Gate 2 (label spot-check, thresholds, lock), Gate 3 (publish). Plus any `blocked:architect` item, answered in batches at the gates unless it stops all lanes.

## 6. Context engineering rules
1. **No agent relies on chat history.** Each agent starts with `CLAUDE.md` + its role brief + one issue. Handoffs go through issue comments, PRs, STATE.md and DECISIONS-LOG.md.
2. **CLAUDE.md stays short** (~150 lines): invariants, commands, file map, definition of done. Detail lives in `docs/` and is read on demand.
3. **STATE.md is rewritten, not appended:** one screen covering the current milestone, active issues, last 5 merges, blockers, next 3 issues.
4. **Each issue lists its expected files.** That's the builder's working set.
5. **ADRs are final.** Agents cite them; they don't re-argue them.
6. **Compaction safety:** after a context compaction, re-read CLAUDE.md, STATE.md and the current issue before continuing. (A hook can re-inject these; verify against the docs.)
7. **Small decisions** go in `DECISIONS-LOG.md`: date | decision | why | reversible (Y/N) | issue.

## 7. Definition of done (per issue)
AC checked in the PR · tests added and passing · CI green · reviewer-approved · STATE.md updated · any new decision logged.

## 8. Harness metrics (`docs/HARNESS.md`, per milestone)
Issues closed · median fix rounds · issues escalated · reviewer catches (defects found before merge, by category) · hard-gate failures on `main` · architect minutes (logged by the architect at each gate) · wall-clock time · model and agent spend (from the Console / `/cost`, UNKNOWN precision).

## 9. Failure playbook
| Symptom | Response |
|---|---|
| Builder loops on the same failure | Stop after 2 rounds; escalate with a diagnosis |
| A test passes only after weakening it | The reviewer rejects it; repeat offences are logged as a harness defect |
| The eval regresses | Fix the code; never change thresholds or labels (they're protected) |
| Scope pressure | File a `scope-question` issue, continue with the in-scope minimum |
| Over the spend cap | Stop; summarise; the architect decides |
| Two lanes conflict | The code lane rebases; data-lane files never overlap code-lane files by design |
