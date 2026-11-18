"""Run the capstone criteria (criteria.md), three trials each, and save the raw results.

  python scripts/capstone_trials.py --label before --criteria 1,2        # free: offline replay
  python scripts/capstone_trials.py --label before --criteria 3,4        # live: 9 runs, real money
  python scripts/capstone_trials.py --label before --criteria 5          # live: 6 runs, real money

Results: docs/capstone/trials/<label>/ (raw logs and results-c<N>.json). Nothing in the criteria is changed between
trials. Every app gets a throwaway copy of data/, so demo memory and fixtures/llm_cache are never modified.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
PY = str(ROOT / "backend" / ".venv" / "bin" / "python")

SEG_FIELDS = ("ts", "event", "run_id", "llm_mode", "input", "output", "duration_s", "usage", "error")
REJ_FIELDS = ("ts", "event", "input", "status", "error")


def make_app(mode: str, log: Path, key: str | None = None, temp_cache: bool = False):
    from reclaim.env import load_env
    load_env()
    work = Path(tempfile.mkdtemp(prefix="reclaim-trial-"))
    shutil.copytree(ROOT / "data", work / "data", ignore=shutil.ignore_patterns("uploads", "checkpoints.db*", "runs.jsonl"))
    os.environ["RECLAIM_LLM_MODE"] = mode
    if temp_cache:
        os.environ["RECLAIM_CACHE_DIR"] = str(work / "temp-cache")
    else:
        os.environ.pop("RECLAIM_CACHE_DIR", None)
    if key is not None:
        os.environ["ANTHROPIC_API_KEY"] = key
    from fastapi.testclient import TestClient
    from reclaim.api.main import Settings, create_app
    cfg = Settings(fixtures=ROOT / "fixtures", data=work / "data", cases=work / "cases", today=date(2026, 11, 14), run_log=log)
    return TestClient(create_app(cfg))


def drive_to_end(c, rid, timeout=600):
    """Approve the first dispute, skip the rest. Returns (final status, decisions posted)."""
    decisions, end = 0, time.monotonic() + timeout
    while time.monotonic() < end:
        st = c.get(f"/api/runs/{rid}").json()
        if st["status"] == "waiting_approval":
            c.post(f"/api/runs/{rid}/cases/{st['pending_case']}/decision",
                   json={"decision": "approve" if decisions == 0 else "skip"})
            decisions += 1
            time.sleep(0.3)
        elif st["status"] in ("done", "error", "stopped"):
            return st["status"], decisions
        else:
            time.sleep(0.2)
    return "timeout", decisions


def read(log: Path):
    return [json.loads(x) for x in log.read_text().splitlines() if x.strip()] if log.exists() else []


# ---- criterion 1: complete records ---------------------------------------------------------------------------------
def c1(out: Path, trial: int) -> dict:
    log = out / f"c1-trial{trial}.jsonl"
    log.write_text("")
    expected_seg, got_seg = 0, 0
    for _ in range(10):
        c = make_app("replay", log)
        rid = c.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
        status, decisions = drive_to_end(c, rid, 120)
        time.sleep(0.4)
        expected_seg += 1 + decisions
        got_seg += sum(1 for r in read(log) if r.get("event") == "segment" and r.get("run_id") == rid)
    c = make_app("replay", log)
    c.post("/api/runs", json={"fixture": "nope.csv"})
    c.post("/api/runs", json={})
    junk = c.post("/api/uploads", files={"file": ("j.csv", b"a,b\nc,d\n", "text/csv")}).json()["upload_id"]
    c.post("/api/runs", json={"upload_id": junk})
    c.post("/api/uploads", files={"file": ("b.csv", b"x" * (2 * 1024 * 1024 + 10), "text/csv")})
    c.post("/api/runs", json={"upload_id": "doesnotexist"})
    time.sleep(0.4)
    recs = read(log)
    segs = [r for r in recs if r["event"] == "segment"]
    rej = [r for r in recs if r["event"] == "rejected"]
    complete = sum(all(k in r for k in SEG_FIELDS) for r in segs) + sum(all(k in r for k in REJ_FIELDS) for r in rej)
    total_expected, total_got = expected_seg + 5, len(segs) + len(rej)
    ok = total_got == total_expected and complete == total_got
    return {"trial": trial, "expected_records": total_expected, "records": total_got, "complete_records": complete,
            "segments_expected": expected_seg, "segments_found": got_seg, "rejected_found": len(rej), "pass": ok}


# ---- criterion 2: failures visible ---------------------------------------------------------------------------------
def c2(out: Path, trial: int) -> dict:
    log = out / f"c2-trial{trial}.jsonl"
    log.write_text("")
    rows = []

    def check(name, kind, resp_status=None, run_status=None, secs=0.0):
        recs = read(log)
        last = recs[-1] if recs else {}
        err = (last.get("error") or {}).get("kind")
        readable = (resp_status in (404, 413, 422)) if kind == "http" else (run_status == "error" and secs <= 30)
        rows.append({"failure": name, "http": resp_status, "run_status": run_status, "seconds": round(secs, 1),
                     "error_kind_logged": err, "pass": bool(readable and err)})

    c = make_app("replay", log)
    check("file not found", "http", c.post("/api/runs", json={"fixture": "nope.csv"}).status_code)
    check("no input", "http", c.post("/api/runs", json={}).status_code)
    junk = c.post("/api/uploads", files={"file": ("j.csv", b"hello,x\nnot,payout\n", "text/csv")}).json()["upload_id"]
    check("not a payout file", "http", c.post("/api/runs", json={"upload_id": junk}).status_code)
    big = c.post("/api/uploads", files={"file": ("b.csv", b"x" * (2 * 1024 * 1024 + 10), "text/csv")})
    check("upload over 2 MB", "http", big.status_code)
    new = (ROOT / "fixtures" / "doordash_payout.csv").read_text().replace("DD-48230", "DD-99999")
    up = c.post("/api/uploads", files={"file": ("n.csv", new.encode(), "text/csv")}).json()["upload_id"]
    t0 = time.monotonic()
    rid = c.post("/api/runs", json={"upload_id": up}).json()["run_id"]
    st, _ = drive_to_end(c, rid, 30)
    time.sleep(0.4)
    check("unseen report, replay", "run", run_status=st, secs=time.monotonic() - t0)
    c2_ = make_app("record", log, key="sk-ant-invalid-key-for-trial", temp_cache=True)
    t0 = time.monotonic()
    rid = c2_.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
    st, _ = drive_to_end(c2_, rid, 30)
    time.sleep(0.4)
    check("rejected API key", "run", run_status=st, secs=time.monotonic() - t0)
    return {"trial": trial, "rows": rows, "passed": sum(r["pass"] for r in rows), "of": len(rows), "pass": all(r["pass"] for r in rows)}


# ---- criteria 3 and 4: live cost and latency (reuses scripts/measure_cost.py) ------------------------------------------
def c34(out: Path, trial: int) -> dict:
    log, summ = out / f"c34-trial{trial}.jsonl", out / f"c34-trial{trial}-summary.json"
    subprocess.run([PY, str(ROOT / "scripts" / "measure_cost.py"), "--runs", "3", "--log", str(log), "--summary", str(summ)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=ROOT)
    s = json.loads(summ.read_text())
    runs = s["per_run"]
    costs, walls = [r["cost_usd"] for r in runs], [r["wall_s"] for r in runs]
    ok_runs = all(r["status"] == "done" for r in runs)
    return {"trial": trial, "costs_usd": costs, "mean_cost_usd": round(statistics.mean(costs), 4), "max_cost_usd": max(costs),
            "wall_s": walls, "all_done": ok_runs,
            "pass_c3": ok_runs and statistics.mean(costs) <= 0.50 and max(costs) <= 0.60,
            "pass_c4": ok_runs and max(walls) < 180}


# ---- criterion 5: concurrent attribution ------------------------------------------------------------------------------
def c5(out: Path, trial: int) -> dict:
    import threading
    from reclaim import llm
    log = out / f"c5-trial{trial}.jsonl"
    log.write_text("")
    c = make_app("record", log, temp_cache=True)
    before = llm.USAGE["calls"]
    rids = [c.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"] for _ in range(2)]
    res = {}
    ts = [threading.Thread(target=lambda r=r: res.__setitem__(r, drive_to_end(c, r))) for r in rids]
    [t.start() for t in ts]
    [t.join() for t in ts]
    time.sleep(0.5)
    actual = llm.USAGE["calls"] - before
    logged = sum(r["usage"]["calls"] for r in read(log) if r.get("event") == "segment")
    return {"trial": trial, "actual_model_calls": actual, "logged_calls_sum": logged, "difference": logged - actual,
            "statuses": {k: v[0] for k, v in res.items()}, "pass": logged == actual and all(v[0] == "done" for v in res.values())}


FUNCS = {"1": c1, "2": c2, "3": c34, "4": c34, "5": c5}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="before or after")
    ap.add_argument("--criteria", required=True)
    a = ap.parse_args()
    out = ROOT / "docs" / "capstone" / "trials" / a.label
    out.mkdir(parents=True, exist_ok=True)
    wanted = a.criteria.split(",")
    done34 = False
    for k in wanted:
        if k in ("3", "4"):
            if done34:
                continue
            done34 = True
            name, fn = "34", c34
        else:
            name, fn = k, FUNCS[k]
        results = []
        for t in (1, 2, 3):
            r = fn(out, t)
            results.append(r)
            print(f"criterion {name} trial {t}:", json.dumps({x: y for x, y in r.items() if x != 'rows'}), flush=True)
        (out / f"results-c{name}.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
