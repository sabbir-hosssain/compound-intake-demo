# ADR-0003: The LLM extracts; code scores the match
Status: Accepted · Date: 2026-11-24 · Consequences measured: 2026-11-26 (Gate 3)

## Context
Options were: (a) the LLM picks the match and states a confidence; (b) the LLM extracts fields, code scores formulas, the LLM explains; (c) code retrieves candidates, the LLM re-ranks.

## Decision
(b). The score is reproducible, auditable and calibratable. Errors split cleanly into "extraction wrong" and "matching wrong", which makes the evaluation diagnostic. A no-LLM baseline (fuzzy matching on raw text) is reported alongside.

## Consequences
Matching quality is capped by the scoring function. Option (c) remains a later experiment to compare against.

Measured in `results/2026-11-26.md` (LIVE, run 1 of 3, 64 synthetic cases; test split unless stated). Where CI REPLAY differs, it says so.
- Code-scored matching on extracted fields beats the no-LLM baseline on test: top-1 16/19 (84% [62–94]) vs 11/19 (58% [36–77]), top-3 17/19 vs 13/19. The intervals overlap, so the gap is suggestive, not precise. On dev the two are close: top-1 32/37 vs 31/37, and the baseline's top-3 is higher (34/37 vs 33/37).
- Extraction is measured on its own: field-level accuracy is 153/176 (87% [81–91]). In CI REPLAY it is 151/176.
- The scorer is deterministic, so run-to-run variation comes from extraction: across the 3 LIVE runs the decision differed on 1/64 cases (g030) and extracted fields on 4/512 case-field pairs.
- Option (c) was not built, so it has no measured comparison.
