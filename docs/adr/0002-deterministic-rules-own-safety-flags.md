# ADR-0002: Deterministic rules own safety flags
Status: Accepted (Gate 1) · Date: 2026-11-24

## Context
Safety checks have to be reproducible, versioned and explainable after the fact. Model behaviour varies between runs and versions.

## Decision
Safety and ambiguity flags come from versioned rules that run on the raw text (pass 1) and on the extracted fields (pass 2). The model can add a flag but can never clear or downgrade one. BLOCK flags disable CONFIRM. Unsafe-flag recall of 100% is a hard CI gate.

## Consequences
More false alarms, which are measured and reported as a cost. A missed unsafe case is treated as a build failure, not a metric.
