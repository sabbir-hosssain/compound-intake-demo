# ADR-0001: AI proposes, the pharmacist confirms
Status: Accepted (Gate 1) · Date: 2026-11-24

## Context
A free-text compound prescription has to be interpreted into a formulation. An interpretation error becomes a dispensing error, and dispensing is irreversible.

## Decision
The LLM produces proposal objects only. There is no code path from model output to a committed record. Only a ReviewAction by a human creates a committed decision. There's no bulk confirm and no auto-confirm at any confidence. An architecture test enforces the import boundary.

## Consequences
Every case costs pharmacist time, so the measurable benefit is time and accuracy of interpretation, not an automation rate. High-confidence proposals may sort first in the queue, but they still need a click.
