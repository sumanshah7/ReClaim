"""Outcome memory in SQLite. Stays local (rule 10)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..schemas import Outcome, OutcomeResult

SCHEMA = """CREATE TABLE IF NOT EXISTS outcomes (
  case_id TEXT PRIMARY KEY, result TEXT NOT NULL, recovered_cents INTEGER NOT NULL DEFAULT 0,
  reason_pattern TEXT NOT NULL)"""


class Memory:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(SCHEMA)
        self.db.commit()

    def record(self, o: Outcome) -> None:
        self.db.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?)",
                        (o.case_id, o.result.value, o.recovered_cents, o.reason_pattern))
        self.db.commit()

    def stats(self, reason_pattern: str) -> tuple[int, int]:
        """(won, resolved). Pending outcomes are ignored."""
        row = self.db.execute(
            "SELECT SUM(result = ?), COUNT(*) FROM outcomes WHERE reason_pattern = ? AND result != ?",
            (OutcomeResult.WON.value, reason_pattern, OutcomeResult.PENDING.value)).fetchone()
        return int(row[0] or 0), int(row[1] or 0)
