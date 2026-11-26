# compound-intake-demo — agent constitution

Read this, then STATE.md, then your issue. Nothing else unless the issue needs it.

## What this is
A public demo: free-text compound prescription → LLM extraction → code-scored formula match → deterministic flags → pharmacist confirms → hash-chained audit. Spec: docs/SPEC.md. Plan: docs/PLAN.md. Process: docs/HARNESS_DESIGN.md.

## Invariants (never break; the reviewer checks every PR)
1. No code path from LLM output to a committed record. src/intake/extract.py, explain.py and adapters/ never import audit.py.
2. Flags are only ever added. No function removes or downgrades a flag.
3. BLOCK flags disable CONFIRM.
4. CI never calls a live model. REPLAY mode only; a missing recording is a failure.
5. Don't edit protected paths (.claude/protected-paths.txt). If you need to, open a blocked:architect issue.
6. Fix failing evals in code. Never change labels, thresholds or tests to pass.
7. Public repo: only the placeholder names "SH Compounding Network" and "TeleHealthSH". No real organisations or people. Synthetic data only; formulas are fictional and marked illustrative.
8. No GLP-1s, peptides, sterile or controlled preparations in the library.

## Commands
- uv sync · uv run ruff check . · uv run pytest -q
- uv run python -m eval.run_eval --mode replay
- uv run intake run samples/case_001.txt
- uv run python scripts/redaction_check.py

## Layout
src/intake/{models,rules,extract,explain,match,baseline,audit,cli}.py · src/intake/adapters/ · prompts/ · data/formulas/ · data/golden/ · eval/ · app/review.py · results/ · docs/ · scripts/

## Definition of done (per issue)
AC checked in the PR · tests added and passing · CI green · reviewer-approved · STATE.md rewritten (by the orchestrator, at merge) · new decisions appended to DECISIONS-LOG.md.

## Style
Python 3.12, type hints, Pydantic v2, small functions, no frameworks beyond the stack in docs/SPEC.md. Prefer boring code.
