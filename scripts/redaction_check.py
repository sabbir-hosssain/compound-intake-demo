#!/usr/bin/env python3
"""Fail if any denylisted term appears in a tracked file. The terms come from the env var REDACTION_DENYLIST
(comma-separated, a CI secret) or the gitignored file .redaction-denylist (one per line). Fails closed in CI."""
import os
import re
import subprocess
import sys
from pathlib import Path

# Whole-word, case-insensitive matching, so a short name can't match inside an ordinary word.
terms = [t.strip() for t in os.environ.get("REDACTION_DENYLIST", "").split(",") if t.strip()]
local = Path(".redaction-denylist")
if local.exists():
    terms += [line.strip() for line in local.read_text().splitlines() if line.strip()]
patterns = [re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in terms]
if not terms:
    if os.environ.get("CI"):
        sys.exit("redaction: no denylist available in CI; failing closed")
    print("redaction: no local denylist; skipping (create .redaction-denylist)")
    sys.exit(0)

hits = []
for f in subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split():
    try:
        text = Path(f).read_text(errors="ignore")
    except (IsADirectoryError, FileNotFoundError):
        continue
    hits += [(f, i) for i, p in enumerate(patterns) if p.search(text)]
if hits:
    for f, i in hits:
        print(f"redaction: denylisted term #{i} found in {f}")  # never print the term itself
    sys.exit(1)
print(f"redaction: clean ({len(terms)} terms)")
