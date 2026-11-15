"""Detects that the backend's own source changed while the server is running.

A running Python server keeps executing the code it imported at start, so an edit mid-run is silently ignored until a
restart. CodeWatch fingerprints the source files (path, mtime, size of every .py and .md under the watched roots, which
includes the agent prompts). Any difference from the fingerprint taken at start means the process is running stale code.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

SUFFIXES = {".py", ".md"}
PACKAGE_DIR = Path(__file__).resolve().parent


class CodeWatch:
    def __init__(self, roots):
        self.roots = [Path(r) for r in roots]
        self.baseline = self.fingerprint()

    def fingerprint(self) -> str:
        h = hashlib.sha1()
        for root in self.roots:
            for p in sorted(root.rglob("*")):
                if p.suffix not in SUFFIXES or "__pycache__" in p.parts:
                    continue
                try:
                    st = p.stat()
                except OSError:          # renamed or deleted between listing and stat: that is itself a change
                    h.update(f"{p}:gone".encode())
                    continue
                h.update(f"{p}:{st.st_mtime_ns}:{st.st_size}".encode())
        return h.hexdigest()

    def changed(self) -> bool:
        return self.fingerprint() != self.baseline
