#!/usr/bin/env python3
"""SessionStart hook (startup|resume|clear|compact): re-inject the invariants and STATE.md.
Plain-text stdout from a SessionStart hook is added to Claude's context (HARNESS_DESIGN §6.6).
Read-only: never writes anything, never blocks."""
import os
import sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()


def section(path: Path, start: str, end: str) -> str:
    if not path.exists():
        return ""
    text = path.read_text()
    if start not in text:
        return ""
    body = text.split(start, 1)[1]
    return start + body.split(end, 1)[0] if end in body else start + body


out = ["[session context] Re-read CLAUDE.md, STATE.md and your current issue before continuing.", ""]
out.append(section(root / "CLAUDE.md", "## Invariants", "## Commands").rstrip())
state = root / "STATE.md"
if state.exists():
    out += ["", state.read_text().rstrip()]
print("\n".join(out))
sys.exit(0)
