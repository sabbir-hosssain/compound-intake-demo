# ADR-0002: Deterministic rules own safety flags
Status: Accepted · Date: 2026-11-24 · Consequences measured: 2026-11-26 (Gate 3)

## Context
Safety checks have to be reproducible, versioned and explainable after the fact. Model behaviour varies between runs and versions.

## Decision
Safety and ambiguity flags come from versioned rules that run on the raw text (pass 1) and on the extracted fields (pass 2). The model can add a flag but can never clear or downgrade one. BLOCK flags disable CONFIRM. Unsafe-flag recall of 100% is a hard CI gate.

## Consequences
More false alarms, which are measured and reported as a cost. A missed unsafe case is treated as a build failure, not a metric.

Measured in `results/2026-11-26.md` (LIVE, run 1 of 3, 64 synthetic cases; test split unless stated). Where CI REPLAY differs, it says so.
- Unsafe-flag recall is 3/3 on test and 10/10 over all cases; adversarial pass rate is 4/4 on test and 10/10 over all cases. Both hard gates passed in each of the 3 LIVE runs.
- Ambiguity-flag (M-01) recall is 2/2 (100% [34–100]), against 1/2 for the baseline.
- The false-alarm cost: M-01 fires on 2/20 test cases not labelled M-01 (10% [3–30]); the baseline's rate is 3/20. In CI REPLAY the system's rate is 3/20, the same as the baseline.
- Rules do not catch every expected flag. Expected-flag recall over all cases is 49/51 (missed: R2-04 on g035, R1-01 on g040).
- Flags are stable across runs: the flag set differed between the 3 LIVE runs on 1/64 cases.
