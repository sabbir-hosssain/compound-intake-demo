# ADR-0001: AI proposes, the pharmacist confirms
Status: Accepted · Date: 2026-11-24 · Consequences measured: 2026-11-26 (Gate 3)

## Context
A free-text compound prescription has to be interpreted into a formulation. An interpretation error becomes a dispensing error, and dispensing is irreversible.

## Decision
The LLM produces proposal objects only. There is no code path from model output to a committed record. Only a ReviewAction by a human creates a committed decision. There's no bulk confirm and no auto-confirm at any confidence. An architecture test enforces the import boundary.

## Consequences
Every case costs pharmacist time, so the measurable benefit is time and accuracy of interpretation, not an automation rate. High-confidence proposals may sort first in the queue, but they still need a click.

Measured in `results/2026-11-26.md` (LIVE, run 1 of 3, 64 synthetic cases; test split unless stated). Where CI REPLAY differs, it says so.
- The confirm step is still needed. Top-1 match accuracy is 16/19 (84% [62–94]), so 3 of 19 test cases with a gold formula reach the pharmacist without it as the top proposal (g019 and g039 `NO_MATCH`, g040 a different formula).
- Simulated override rate is 4/22 (18% [7–39]) against 9/22 (41% [23–61]) for the no-LLM baseline. The gold label stands in for the pharmacist, so this is a proxy; no pharmacist decision or review time was measured.
- Every case still reaches review. Schema-valid or `MANUAL` was 64/64 over all cases, in each of the 3 LIVE runs.
- The zero-write-path gate is not in the results file. It is enforced by `tests/test_architecture.py` in the CI `test` job.
