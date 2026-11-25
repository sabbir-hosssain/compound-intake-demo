# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: none (code lane next: #9 S1.9 eval harness — last M1 issue)
Last merges: #8 S1.8 CLI (PR #40, 0 rounds) · #5 S1.5 extraction (PR #35, 0; 1 key block) · #39 chore · #10 S1.10 arch test (PR #38, 0) · #7 S1.7 audit (PR #37, 0)
Blocked (architect): #33 SPEC §7 "Temperature 0" can't be sent to claude-sonnet-5-5 (non-blocking; batch at Gate 2)
Next up: S1.9 eval harness → M1 exit check
Notes:
- `uv run intake run samples/case_001.txt` works in REPLAY → PROPOSED SHF-001; writes one pending audit record (review_action = null). Missing recording → exit 2, no audit write.
- Pipeline (`intake.pipeline`): pass 1 → extract → MANUAL | pass 2 + match → Proposal. Records hash-linked per SPEC §10 in pipeline.py (S3.2 may move it to audit.py and add verify).
- S1.9 needs recordings for case_004/005: live step with `env -u ANTHROPIC_API_KEY uv run --env-file <repo-root>/.env …`.
- eval-replay is a placeholder until S1.9.
