"""Structured run log: one JSON object per line, written for every agent segment and every rejected input.

A "segment" is one stretch of agent work: from a start or a resume until the agent finishes, pauses for the owner,
errors, or is stopped. Fields are named so the file can be queried afterwards (jq, pandas) without new code.
Logging must never break a run, so every failure here is swallowed.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log_event(path: Path | str | None, **fields) -> None:
    if not path:
        return
    rec = {"ts": now_iso(), **fields}
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, default=str, ensure_ascii=False)
        with _LOCK, p.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def usage_delta(before: dict, after: dict) -> dict:
    """Token use during one segment. USAGE is process-wide, so overlapping runs would be mixed together;
    the measurement script runs one at a time, and the field name says what it is."""
    return {k: after.get(k, 0) - before.get(k, 0) for k in after}
