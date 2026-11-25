# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: #3 S1.3 model adapter (PR #32 open, awaiting review)
Last merges: #2 S1.2 seed library (PR #31, 0 rounds) · #1 S1.1 schemas (PR #30, 0 rounds)
Blocked (architect): none yet; S1.3 raises a SPEC §7 question (temperature, see below)
Next up: S1.4 rules skeleton (code) · S1.5 extraction (needs S1.3) · data lane idle (no M1 data issues left)
Notes:
- Seed: SHF-001..003, ingredient_master.yaml, samples/case_001–005, data/seed/seed_cases.jsonl.
- Adapter: `intake.adapters.anthropic_client.ModelClient.complete(prompt_hash, system, user_input, tools)` → raw response dict. Mode from `INTAKE_MODE` (default REPLAY); REPLAY raises `MissingRecordingError` on a miss and never builds a live client. Recordings: `eval/cassettes/<sha256>.json`.
- Architect question (S1.3): `claude-sonnet-5-5` rejects `temperature`; the adapter doesn't send it, though SPEC §7 says temperature 0. S1.5 must not force `tool_choice` (400 on Sonnet 5.5).
- Open for S1.6: SPEC fixes `Flag.source_pass` to 1|2; M-01 needs a convention or a blocked:architect SPEC change.
- Reviewer notes: `Proposal.flags` is mutable inside frozen AuditRecord (keep append-only); case_002 "up to 3 times daily" may trip R1-02 later; formula loader validation needs a committed test (S1.5/S1.6).
- eval-replay is a placeholder until S1.9.
