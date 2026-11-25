# SPEC — compound-intake-demo (v1, approved at Gate 1)

> Protected file. Agents may not edit it. Changes go through a `blocked:architect` issue.

## 1. Problem
A compound prescription often arrives as free text, because the sending e-prescribing system doesn't send structured compound ingredients. A pharmacist has to work out which formulation the prescriber meant, and phone the prescriber when it's unclear. This demo helps with **interpretation only**. It proposes; a pharmacist confirms.

**User:** the intake pharmacist at "SH Compounding Network", working a queue of inbound prescriptions, including orders from the telehealth partner "TeleHealthSH" and from outside prescribers.

## 2. Scope
**In:** free-text intake · two rule passes · LLM extraction to a schema · code-based matching and scoring · LLM-written explanation · minimal review screen (confirm / correct / clarify) · hash-chained audit log · golden-set evaluation with a non-AI baseline · CI with recorded model responses.

**Out:** beyond-use-date calculation, compounding records, dispensing, claims, structured SCRIPT parsing, sterile preparations, veterinary branch (schema placeholders only), clarification-call drafting, authentication, cloud hosting, AWS.

## 3. Flow
```
raw text ─► Rules pass 1 (raw) ─► LLM extract ─► schema validation ─► Rules pass 2 (fields)
        ─► Matcher (code): score every formula ─► top 3 + confidence + margin
        ─► LLM explain (reasons only) ─► Proposal ─► Review screen ─► ReviewAction ─► Audit log
```
- If schema validation fails, the proposal is `MANUAL` (no candidates). It's never retried silently more than once.
- Flags are a **union** of pass 1 and pass 2. No later stage may remove a flag.
- The LLM modules (`extract.py`, `explain.py`, `adapters/`) **must not import** `audit.py` or any commit function. An architecture test enforces this.

## 4. Data model (Pydantic v2; names are binding, fields may grow)
- `RawPrescription`: id, received_at, source (`eRx_free_text` | `fax_ocr` | `partner_api`), text, notes.
- `Ingredient`: name (normalised), strength (float | None), unit (`mg`, `mcg`, `g`, `%`, `mg/mL`, `units` | None).
- `Extraction`: ingredients[], dosage_form, base, route, quantity, quantity_unit, directions, prescriber_name, patient_ref, species (None), office_stock (None), extraction_notes.
- `Formula`: formula_id (`SHF-###`), version, name, ingredients[] with strengths, dosage_form, base, route, illustrative_max per ingredient, notes. Every file carries `illustrative: true`.
- `Flag`: rule_id, rule_version, severity (`BLOCK` | `REVIEW`), message, source_pass (1 | 2).
- `MatchCandidate`: formula_id, formula_version, score (0–1), component_scores{}.
- `Proposal`: prescription_id, extraction, candidates[≤3], confidence, margin, status (`PROPOSED` | `NO_MATCH` | `MANUAL`), flags[], reasons (text), model_id, prompt_versions{}, rules_version, library_version, created_at.
- `ReviewAction`: action (`CONFIRM` | `CORRECT` | `CLARIFY`), chosen_formula_id, corrected_fields{}, reason_code, reviewer, at.
- `AuditRecord`: seq, prev_hash, record_hash, input_hash, proposal, review_action, at.

## 5. Rules (deterministic, versioned in `src/intake/rules.py`, `RULES_VERSION` constant)
**Pass 1 (raw text):**
| ID | Fires when | Severity |
|---|---|---|
| R1-01 | Description is empty, "see notes", or similar | REVIEW |
| R1-02 | A number appears with no unit next to an ingredient-like token | REVIEW |
| R1-03 | Refers to an unseen prior order ("as before", "same as last", "usual") | REVIEW |
| R1-04 | Contains a term from the synthetic controlled-substance list | BLOCK (controlled workflow) |
| R1-05 | Contains instruction-like text aimed at the system ("ignore", "approve", "mark verified", "system:") | BLOCK |

**Pass 2 (extracted fields vs library):**
| ID | Fires when | Severity |
|---|---|---|
| R2-01 | Ingredient not in the ingredient master | BLOCK |
| R2-02 | Strength above that ingredient's illustrative max | BLOCK |
| R2-03 | Strength ≥10× or ≤0.1× the nearest library strength (unit-error suspicion) | BLOCK |
| R2-04 | Dosage form missing, or conflicts with the route | REVIEW |
| R2-05 | Quantity missing or implausible | REVIEW |
| R2-06 | Prescriber or patient reference missing | REVIEW |
| R2-07 | Duplicate ingredient | REVIEW |

**Effect on review:** a `BLOCK` flag disables CONFIRM; the pharmacist can only CORRECT (with a reason) or CLARIFY. A `REVIEW` flag needs an explicit acknowledgment before CONFIRM.

## 6. Matching (code, `src/intake/match.py`)
Score per formula = 0.40·ingredient-set similarity (Jaccard on normalised names) + 0.25·strength agreement (per ingredient, within ±10% = 1, decaying to 0 at ±50%) + 0.15·dosage form + 0.10·base + 0.10·route.
- `confidence` = top score; `margin` = top − second.
- `NO_MATCH` if confidence < **T_match** (start 0.60). An ambiguity flag `M-01 (REVIEW)` fires if margin < **T_margin** (start 0.10).
- The weights and thresholds live in `eval/thresholds.yaml` (**protected**). They're tuned on the dev split only, and frozen at Gate 2.

**Baseline** (`src/intake/baseline.py`): no LLM. A rapidfuzz token-set ratio between the raw text and each formula's name plus ingredient string, giving top 3 and a `NO_MATCH` cut-off tuned on dev.

## 7. LLM usage
- Provider: Anthropic API. The model ID is pinned in `config.toml` (start: `claude-sonnet-5-5`; verify availability on the key). Temperature 0. Structured output through tool use / JSON schema.
- Prompts are files: `prompts/extract_v1.md`, `prompts/explain_v1.md`. Their SHA-256 is recorded in every Proposal.
- Raw prescription text is wrapped as data in the prompt and never treated as instructions. R1-05 fires regardless of what the model does.
- **Modes:** `REPLAY` (default, CI: missing recording = test failure), `RECORD`, `LIVE`. A recording is keyed by hash(model_id, prompt_hash, input).

## 8. Evaluation (`eval/`)
- **Golden set:** ~60 synthetic cases in `data/golden/*.jsonl`: ~25 clean, ~15 ambiguous, ~10 unsafe, ~10 adversarial, with ~8 no-match cases spread across them. Each case carries `split` (dev | test), `category`, expected extraction, expected `formula_id` or `NO_MATCH`, and expected flag rule IDs.
- **Metrics** (each with a 95% Wilson interval, reported per split and per category, for the system **and** the baseline):
  field-level extraction accuracy · top-1 and top-3 match accuracy · no-match precision and recall · unsafe-flag recall · ambiguity-flag recall and false-alarm rate · adversarial pass rate · simulated override rate (top-1 ≠ gold) · run-to-run variance over 3 LIVE runs (manual).
- **Hard gates** (CI fails): unsafe-flag recall = 100% · adversarial pass rate = 100% (flags present, nothing auto-confirmed) · zero write path (architecture test) · schema-valid or `MANUAL` = 100% · redaction check passes.
- **Soft gates** (a PR comment needs a justification): top-1 on dev drops more than 5 points from the last recorded result; the false-alarm rate rises more than 10 points.
- **Output:** `results/YYYY-MM-DD.md`, generated, never hand-edited.

## 9. Review screen (`app/review.py`, Streamlit)
A queue list → a proposal view: raw text, extracted fields, flags (BLOCK first), the top 3 candidates with component scores, a side-by-side diff against the chosen formula, reasons, and the actions CONFIRM / CORRECT / CLARIFY with required reason codes. **There's no bulk action and no auto-confirm.** Fallback if M3 slips: the same actions in the CLI (`intake review`).

## 10. Audit (`src/intake/audit.py`)
Append-only SQLite table. `record_hash = sha256(prev_hash + canonical_json(record))`. `intake audit verify` recomputes the chain and reports the first broken link. There are no update or delete functions.

## 11. Limitations (they go in the README verbatim)
Synthetic data; fictional, illustrative formulas and dose limits; labels written by a non-pharmacist with AI help and spot-checked by the author; small n with wide intervals; simulated override rate; no BUD, compounding record, sterile or veterinary logic; not clinical software.
