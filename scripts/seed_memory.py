"""Seed the persistent memory with SYNTHETIC prior disputes so the demo can show learning from history.

These are invented, and labeled as such in the lessons file. Run: backend/.venv/bin/python scripts/seed_memory.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from reclaim.agent.session import LESSONS_HEADER  # noqa: E402
from reclaim.schemas import Outcome, OutcomeResult  # noqa: E402
from reclaim.triage.memory import Memory  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
SIG = "pickup_handoff+1|ticket_lists_item+1"
W, L = OutcomeResult.WON, OutcomeResult.LOST
SEED = [
    ("seed-1", W, 1850, "doordash:missing_item", SIG, "Green Smoothie", "Ticket listing the item plus a prompt handoff time won."),
    ("seed-2", W, 1425, "doordash:missing_item", SIG, "Granola Cup", "Same pattern again: ticket and handoff times were enough."),
    ("seed-3", L, 0, "doordash:missing_item", SIG, "Fruit Bowl", "Lost despite ticket and handoff; the claim named a side item not itemised on the ticket."),
]


def main():
    DATA.mkdir(exist_ok=True)
    (DATA / "memory").mkdir(exist_ok=True)
    m = Memory(DATA / "reclaim.db")
    lessons = DATA / "memory" / "AGENTS.md"
    if not lessons.exists():
        lessons.write_text(LESSONS_HEADER + "- (Synthetic demo history, not real disputes.)\n")
    for cid, res, cents, pat, sig, item, lesson in SEED:
        m.record(Outcome(case_id=cid, result=res, recovered_cents=cents, reason_pattern=pat, signature=sig,
                         claimed_item=item, lesson=lesson))
        line = f"- {pat} [{sig}] {res.value}. {lesson}\n"
        if line not in lessons.read_text():
            with open(lessons, "a") as fh:
                fh.write(line)
    print(f"seeded {len(SEED)} synthetic outcomes into {DATA}")


if __name__ == "__main__":
    main()
