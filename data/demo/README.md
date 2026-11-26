# Demo fixtures

Three showcase prescriptions for `make demo` (synthetic, `illustrative: true`; strengths and maxima are not clinical).
Each line of `demo_cases.jsonl` follows the golden-case shape plus `sample_file` and `expect_confirm_disabled`.
`raw.text` equals the matching `samples/demo_*.txt` file (minus the trailing newline).

| Case | Sample | Expected |
|---|---|---|
| demo_1_clean | samples/demo_1_clean.txt | SHF-009, PROPOSED, no flags, CONFIRM enabled |
| demo_2_unsafe | samples/demo_2_unsafe.txt | SHF-002, PROPOSED, R2-02 (BLOCK), CONFIRM disabled |
| demo_3_injection | samples/demo_3_injection.txt | SHF-003, PROPOSED, R1-05 (BLOCK), CONFIRM disabled |

REPLAY needs a recording per case (keyed by model, prompt hash and input). They are not recorded yet; see the PR for #23.
These fixtures are separate from the locked golden set and are not scored by the eval.
