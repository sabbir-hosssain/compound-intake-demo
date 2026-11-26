# Golden set (illustrative, synthetic)

64 fictional cases in `golden_cases.jsonl` (every record has `illustrative: true`): dev 42, test 22; clean 25, ambiguous 19, unsafe 10, adversarial 10.
g061-g064 are the pre-lock M-01 near-tie cases (2 dev, 2 test, each with a score margin under 0.07 at T_match 0.58). Print counts: `python data/golden/counts.py`.
Labels come from SPEC section 5 rule definitions and the formulas in `data/formulas/`, not from the implementation.

Fields: `case_id`, `split` (dev|test), `category` (clean|ambiguous|unsafe|adversarial), `raw` (RawPrescription shape),
`expected_extraction` (fields that are null are expected to be absent; directions are not scored),
`expected_formula_id` (SHF-### or NO_MATCH), `expected_status`, `expected_flags` (rule IDs, full expected set), `tags`, `rationale`.

Notes:
- Controlled-substance terms (R1-04) appear only as test inputs; they are not in the library.
- Cases whose rationale says UNSURE are flagged for the Gate 2 spot-check.
- `M-01` is expected only where the order itself fails to distinguish near-twin formulas.
