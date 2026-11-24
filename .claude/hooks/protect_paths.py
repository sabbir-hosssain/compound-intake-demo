#!/usr/bin/env python3
"""PreToolUse hook: block Edit/Write on protected paths. Exit 2 = block (stderr is shown to the agent).
Note: this can't see writes made through Bash; CI (scripts/protected_paths_check.py) is the backstop."""
import fnmatch
import json
import os
import sys
from pathlib import Path

root = Path(os.environ.get("CLAUDE_PROJECT_DIR", ".")).resolve()
payload = json.load(sys.stdin)
target = payload.get("tool_input", {}).get("file_path") or payload.get("tool_input", {}).get("notebook_path")
if not target:
    sys.exit(0)
try:
    rel = Path(target).resolve().relative_to(root).as_posix()
except ValueError:
    sys.exit(0)

patterns = [line.strip() for line in (root / ".claude/protected-paths.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
if (root / "data/golden/LOCKED").exists():
    patterns.append("data/golden/*")

if any(fnmatch.fnmatch(rel, p) for p in patterns):
    print(f"BLOCKED: {rel} is a protected path. Open a blocked:architect issue instead "
          f"(see docs/HARNESS_DESIGN.md §5).", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
