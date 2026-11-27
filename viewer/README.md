# Replay viewer

A static page that plays back four synthetic prescriptions through the intake pipeline, stage by stage,
and ends at the pharmacist's review. It has no backend, makes no model calls and needs no API key.

- **Traces, not a live pipeline.** `traces/*.json` are exported from recorded REPLAY runs by `intake trace`
  (`src/intake/trace.py`). `tests/test_trace.py` regenerates them and fails if the committed copies drift.
- **Review actions are simulated.** Confirm, Correct and Clarify follow the same rules as `intake.review`
  (a BLOCK flag disables Confirm; a REVIEW flag needs acknowledging; Confirm takes the top candidate only;
  every action needs a reason code from that action's list). The "audit chain" is computed in the browser
  with SHA-256 and is saved nowhere.

| Scenario | Source case | What it shows |
|---|---|---|
| Clean | `demo_1_clean` | No flags, CONFIRM available |
| Ambiguous | golden `g027` | M-01 (REVIEW): CONFIRM opens only after acknowledging |
| Unsafe | `demo_2_unsafe` | R2-02 (BLOCK): CONFIRM disabled |
| Adversarial | `demo_3_injection` | R1-05 (BLOCK) from the raw-text rules |

## Run it locally

```sh
make viewer        # regenerates the traces (REPLAY), then serves viewer/ on http://localhost:8000
```

Opening `index.html` straight from disk won't load the traces (browsers block local `fetch`).

## Change it

Change the pipeline, then `make traces` and commit the JSON. Never hand-edit a trace.
Plain HTML, CSS and JavaScript: no build step, no framework, no third-party requests (system fonts only).
