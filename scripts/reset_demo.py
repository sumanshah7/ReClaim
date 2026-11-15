"""Return the demo to its clean state: exactly the 3 synthetic seed outcomes, no pending or resolved cases from earlier
runs, and AGENTS.md rebuilt to the seeded lessons. The seeded file is byte-identical to the state the replay cache was
recorded with, so the offline demo keeps hitting the cache.

  make reset            (then restart `make api` so the in-memory phone log starts empty)
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_memory  # noqa: E402

DB = ROOT / "data" / "reclaim.db"
LESSONS = ROOT / "data" / "memory" / "AGENTS.md"


def main() -> None:
    if DB.exists():
        con = sqlite3.connect(DB)
        con.execute("DELETE FROM outcomes")   # table is created by Memory() on first use; absent only on a fresh clone
        con.commit()
        con.close()
    LESSONS.unlink(missing_ok=True)
    seed_memory.main()
    con = sqlite3.connect(DB)
    n, pending = con.execute("SELECT COUNT(*), SUM(result = 'pending') FROM outcomes").fetchone()
    con.close()
    assert n == 3 and not pending, f"reset failed: {n} outcomes, {pending} pending"
    print(f"reset OK: {n} outcomes, 0 pending, AGENTS.md {LESSONS.stat().st_size} bytes. Restart `make api`.")


if __name__ == "__main__":
    main()
