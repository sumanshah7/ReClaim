"""Record the real model's responses into fixtures/llm_cache so the demo replays offline (rule 9).

Needs ANTHROPIC_API_KEY. The owner's decisions change later model calls, so record the path you will demo:
  python scripts/record_cache.py --decisions approve,skip
Any decision sequence you did not record raises a clear CacheMiss at demo time.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from langgraph.types import Command  # noqa: E402

from reclaim.agent.graph import build_agent  # noqa: E402
from reclaim import tracing  # noqa: E402
from reclaim.env import load_env  # noqa: E402
from reclaim.agent.session import Session  # noqa: E402
from reclaim.llm import make_model  # noqa: E402
from reclaim.triage.memory import Memory  # noqa: E402


def main():
    import os
    import shutil
    load_env()
    note = tracing.ensure_consistent()
    print('tracing:', 'on, project ' + tracing.status()['project'] if tracing.status()['enabled'] else 'off' + (f' ({note})' if note else ''))
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Export it to record the cache; the demo itself replays offline.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--payout", default="doordash_payout.csv")
    ap.add_argument("--decisions", default="approve,skip", help="comma list for each approval prompt: approve|skip")
    ap.add_argument("--memory", default=str(ROOT / "data"), help="memory dir; must match what the demo uses")
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp())
    data = work / "data"
    if Path(a.memory).exists():
        shutil.copytree(a.memory, data, ignore=shutil.ignore_patterns("uploads", "checkpoints.db*"))
    data.mkdir(exist_ok=True)
    s = Session(work / "cases", ROOT / "fixtures" / "tickets.json", date(2026, 11, 14),
                memory=Memory(data / "reclaim.db"), memory_dir=data / "memory")
    model = make_model(ROOT / "fixtures" / "llm_cache", mode="auto")
    agent = build_agent(s, model, work / "ckpt.db")
    cfg = {"configurable": {"thread_id": "record"}, "recursion_limit": 100, **tracing.run_config("record", "record", "synthetic-sample")}
    res = agent.invoke({"messages": [("user", f"Process the payout file at {ROOT / 'fixtures' / a.payout}.")]}, cfg)
    for d in a.decisions.split(","):
        if not res.get("__interrupt__"):
            break
        cid = res["__interrupt__"][0].value["action_requests"][0]["args"]["case_id"]
        print("approval prompt for", cid, "->", d)
        if d == "approve":
            s.approve(cid)
            res = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
        else:
            s.skip(cid)
            res = agent.invoke(Command(resume={"decisions": [{"type": "reject", "message": "The owner chose to skip this case."}]}), cfg)
    print("recorded; cache entries:", len(list((ROOT / "fixtures" / "llm_cache").glob("*.json"))))


if __name__ == "__main__":
    main()
