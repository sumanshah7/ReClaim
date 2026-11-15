"""Persistent outcome memory in SQLite. Stays local (rule 10).

Outcomes are recorded with the evidence signature of the case, so similar cases can be recalled and so
win-rate priors can be as specific as the history allows.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from ..schemas import Evidence, Outcome, OutcomeResult

SCHEMA = """CREATE TABLE IF NOT EXISTS outcomes (
  case_id TEXT PRIMARY KEY, result TEXT NOT NULL, recovered_cents INTEGER NOT NULL DEFAULT 0,
  reason_pattern TEXT NOT NULL, signature TEXT NOT NULL DEFAULT '', claimed_item TEXT, lesson TEXT)"""
MIN_SIGNATURE_SAMPLES = 2  # a specific pattern needs this many resolved cases before it overrides the broad one


def signature_of(evidence: list[Evidence]) -> str:
    """Stable evidence pattern, e.g. 'pickup_handoff+1|ticket_lists_item+1'. Excludes repeat-claimant counts' detail."""
    return "|".join(sorted({f"{e.kind.value}{e.supports:+d}" for e in evidence}))


class Memory:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute(SCHEMA)
        self.db.commit()

    def record(self, o: Outcome) -> None:
        self.db.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?)",
                        (o.case_id, o.result.value, o.recovered_cents, o.reason_pattern, o.signature,
                         o.claimed_item, o.lesson))
        self.db.commit()

    def stats(self, reason_pattern: str, signature: str | None = None) -> tuple[int, int]:
        """(won, resolved). Pending outcomes are ignored. With a signature, only matching cases count."""
        q = "SELECT SUM(result = ?), COUNT(*) FROM outcomes WHERE reason_pattern = ? AND result != ?"
        args: list = [OutcomeResult.WON.value, reason_pattern, OutcomeResult.PENDING.value]
        if signature is not None:
            q += " AND signature = ?"
            args.append(signature)
        row = self.db.execute(q, args).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def best_stats(self, reason_pattern: str, signature: str) -> tuple[tuple[int, int], str]:
        """Most specific history with enough samples, else the broad pattern. Returns (stats, scope label)."""
        if signature:
            sig = self.stats(reason_pattern, signature)
            if sig[1] >= MIN_SIGNATURE_SAMPLES:
                return sig, "similar evidence pattern"
        return self.stats(reason_pattern), "same claim type"

    def similar(self, reason_pattern: str, signature: str, claimed_item: str | None = None, limit: int = 5) -> list[dict]:
        """Past cases, most similar first: same pattern and signature, then same pattern. Includes lessons."""
        rows = self.db.execute(
            "SELECT case_id, result, recovered_cents, signature, claimed_item, lesson FROM outcomes "
            "WHERE reason_pattern = ? AND result != ? ORDER BY (signature = ?) DESC, (claimed_item = ?) DESC, case_id "
            "LIMIT ?", (reason_pattern, OutcomeResult.PENDING.value, signature, claimed_item or "", limit)).fetchall()
        return [{"case_id": r[0], "result": r[1], "recovered_cents": r[2], "same_evidence_pattern": r[3] == signature,
                 "claimed_item": r[4], "lesson": r[5]} for r in rows]

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0])
