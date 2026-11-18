"""Measure what one live Re-Claim run costs and how long it takes (capstone, Milestone 3).

One run = one payout file taken through the real API path: start, the agent investigates, the owner approves the
first dispute and skips the rest, the agent finishes. Every model call is live: record mode never reads the cache and writes to a
temp dir, so nothing is replayed and fixtures/llm_cache is never touched. Memory is a throwaway copy of data/, so the
demo's memory is not changed either.

Dollars are computed from the token counts the API returned, at the published Sonnet 5.5 rates (a documented price,
applied to measured tokens). Needs ANTHROPIC_API_KEY. Spends real money.

  python scripts/measure_cost.py --runs 10
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# $ per million tokens, claude-sonnet-5-5 (input, output, 5-minute cache write = 1.25 x input, cache read).
PRICE = {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.10}


def dollars(u: dict) -> float:
    plain = max(u["input"] - u["cache_read"] - u["cache_creation"], 0)
    return (plain * PRICE["input"] + u["cache_creation"] * PRICE["cache_write"]
            + u["cache_read"] * PRICE["cache_read"] + u["output"] * PRICE["output"]) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--payout", default="doordash_payout.csv")
    ap.add_argument("--log", default=str(ROOT / "docs" / "capstone" / "run-log.jsonl"))
    ap.add_argument("--summary", default=str(ROOT / "docs" / "capstone" / "cost-summary.json"))
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="reclaim-measure-"))
    os.environ["RECLAIM_LLM_MODE"] = "record"                         # record mode never reads the cache: every call is live
    os.environ["RECLAIM_CACHE_DIR"] = str(work / "temp-cache")        # its recordings go to a temp dir, not fixtures/llm_cache
    os.environ["RECLAIM_DATA_DIR"] = str(work / "data")
    from reclaim.env import load_env
    load_env()
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        sys.exit("ANTHROPIC_API_KEY is not set.")
    os.environ["RECLAIM_LLM_MODE"] = "record"                         # load_env must not change the mode
    shutil.copytree(ROOT / "data", work / "data", ignore=shutil.ignore_patterns("uploads", "checkpoints.db*", "runs.jsonl"))

    from fastapi.testclient import TestClient
    from reclaim.api.main import Settings, create_app

    log = Path(a.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("")
    cfg = Settings(fixtures=ROOT / "fixtures", data=work / "data", cases=work / "cases", today=date(2026, 11, 14),
                   run_log=log)
    c = TestClient(create_app(cfg))
    print("health:", c.get("/api/health").json()["llm_mode"], "| run log:", log)

    results = []
    for i in range(1, a.runs + 1):
        t0 = time.monotonic()
        before = len(log.read_text().splitlines())
        rid = c.post("/api/runs", json={"fixture": a.payout}).json()["run_id"]
        status, approvals = "running", 0
        end = time.monotonic() + a.timeout
        while time.monotonic() < end:
            st = c.get(f"/api/runs/{rid}").json()
            status = st["status"]
            if status == "waiting_approval":
                decision = "approve" if approvals == 0 else "skip"
                c.post(f"/api/runs/{rid}/cases/{st['pending_case']}/decision", json={"decision": decision})
                approvals += 1
                time.sleep(0.3)
                continue
            if status in ("done", "error", "stopped"):
                break
            time.sleep(0.5)
        else:
            status = "timeout"
        wall = time.monotonic() - t0
        time.sleep(0.3)
        recs = [json.loads(x) for x in log.read_text().splitlines()[before:]]
        segs = [r for r in recs if r.get("event") == "segment" and r.get("run_id") == rid]
        u = {k: sum(s["usage"][k] for s in segs) for k in ("calls", "input", "cache_read", "cache_creation", "output")}
        res = {"run": i, "run_id": rid, "status": status, "wall_s": round(wall, 1), "approvals": approvals,
               "segments": len(segs), **u, "cost_usd": round(dollars(u), 4)}
        results.append(res)
        print(json.dumps(res))

    ok = [r for r in results if r["status"] == "done"]
    summ = {"runs": len(results), "completed": len(ok), "payout": a.payout, "model": "claude-sonnet-5-5", "price_per_mtok": PRICE,
            "per_run": results}
    if ok:
        walls, costs = [r["wall_s"] for r in ok], [r["cost_usd"] for r in ok]
        summ.update(mean_cost_usd=round(statistics.mean(costs), 4), min_cost_usd=min(costs), max_cost_usd=max(costs),
                    mean_wall_s=round(statistics.mean(walls), 1), median_wall_s=round(statistics.median(walls), 1),
                    min_wall_s=min(walls), max_wall_s=max(walls),
                    mean_calls=round(statistics.mean(r["calls"] for r in ok), 1),
                    cache_read_share=round(sum(r["cache_read"] for r in ok) / max(sum(r["input"] for r in ok), 1), 3))
    Path(a.summary).write_text(json.dumps(summ, indent=1))
    print("summary:", json.dumps({k: v for k, v in summ.items() if k != "per_run"}))


if __name__ == "__main__":
    main()
