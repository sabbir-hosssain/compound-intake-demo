#!/usr/bin/env python3
"""CI: fail if the PR diff touches protected paths, unless the PR has the architect-approved label (env APPROVED=true)."""
import fnmatch
import os
import subprocess
import sys
from pathlib import Path

if os.environ.get("APPROVED") == "true":
    print("protected-paths: architect-approved, skipping")
    sys.exit(0)
base = os.environ.get("BASE_REF", "origin/main")
changed = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD"],
                         capture_output=True, text=True, check=True).stdout.split()
patterns = [line.strip() for line in Path(".claude/protected-paths.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
if Path("data/golden/LOCKED").exists():
    patterns.append("data/golden/*")
bad = [c for c in changed if any(fnmatch.fnmatch(c, p) for p in patterns)]
if bad:
    print("protected-paths: PR touches protected files:\n  " + "\n  ".join(bad))
    sys.exit(1)
print("protected-paths: clean")
