# STATE (rewritten after every issue; one screen max)
Milestone: M1 in progress
Active: none
Last merges: — (PR open for #1 S1.1 schemas, awaiting review)
Blocked (architect): none
Next up: S1.2, S1.3; then S1.4, S1.5, S1.6, S1.7 (unblocked by S1.1 once merged)
Notes: `intake.models` now provides every SPEC §4 model. Open point for S1.6: `Flag.source_pass` is 1|2 per SPEC, so matcher flag M-01 needs a convention (see DECISIONS-LOG #1). `eval/run_eval.py` doesn't exist until S1.9, so the replay eval step is a no-op.
