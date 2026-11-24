# ADR-0003: The LLM extracts; code scores the match
Status: Accepted (Gate 1) · Date: 2026-11-24

## Context
Options were: (a) the LLM picks the match and states a confidence; (b) the LLM extracts fields, code scores formulas, the LLM explains; (c) code retrieves candidates, the LLM re-ranks.

## Decision
(b). The score is reproducible, auditable and calibratable. Errors split cleanly into "extraction wrong" and "matching wrong", which makes the evaluation diagnostic. A no-LLM baseline (fuzzy matching on raw text) is reported alongside.

## Consequences
Matching quality is capped by the scoring function. Option (c) remains a later experiment to compare against.
