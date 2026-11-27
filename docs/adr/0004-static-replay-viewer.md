# ADR-0004: A static replay viewer on GitHub Pages, fed by recorded traces
Status: Accepted · Date: 2026-11-26

## Context
v0.1 shows that the gate works, but only to someone who clones the repo and runs `make demo` or Streamlit.
A link that plays the flow, step by step, shows *where* the gate is. SPEC §2 lists cloud hosting as out of scope,
and SPEC §9 defines only the Streamlit review screen. Options were: (a) host the Streamlit app; (b) animate the
steps inside Streamlit and keep it local; (c) a static page on GitHub Pages that replays traces exported from
REPLAY runs.

## Decision
(c). `intake trace` exports four scenarios (clean, ambiguous, unsafe, prompt injection) from recorded REPLAY
responses into `viewer/traces/*.json`. `viewer/` is plain HTML, CSS and JavaScript with no build step. Review
actions in the viewer are simulated in the browser: they follow `intake.review`'s rules and write nothing anywhere.
A GitHub Actions workflow deploys `viewer/` only to GitHub Pages.

## Consequences
- No server, no API key and no model calls in public. Cost: none. The viewer can't run a new prescription.
- The traces can drift from the pipeline. `tests/test_trace.py` regenerates them in CI and fails on any difference;
  the fix is `make traces`, never a hand edit.
- The review rules exist twice (Python and JavaScript). The traces carry the Python-computed blockers
  (`confirm_blockers` with and without acknowledgment) and the reason-code lists, so the browser only applies them.
- Invariant 1 holds: `intake.trace` never imports the audit module and never builds a ReviewAction; a test pins this.
- The page is public, so it carries the same honesty lines as the README and passes the redaction check.
