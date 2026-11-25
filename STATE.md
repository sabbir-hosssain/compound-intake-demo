# STATE (rewritten after every issue; one screen max)
Milestone: M1 — walking skeleton (in progress; started 2026-11-25 03:30Z)
Active: none (code lane next: #3 S1.3 · data lane next: #2 S1.2)
Last merges: #1 S1.1 schemas (PR #30, 0 fix rounds)
Blocked (architect): none
Next up: S1.2 (data), S1.3, S1.4 (code)
Notes:
- `intake.models` provides every SPEC §4 model (frozen Flag/AuditRecord, extra fields forbidden).
- Open for S1.6: SPEC fixes `Flag.source_pass` to 1|2; M-01 needs a convention or a blocked:architect SPEC change.
- Reviewer risk note: `Proposal.flags` is a mutable list inside frozen AuditRecord; S1.4/S1.8 must keep flags append-only.
- eval-replay is a placeholder until S1.9.
