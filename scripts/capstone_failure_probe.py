"""Trigger the failure paths on purpose and leave their records in docs/capstone/failure-log.jsonl (capstone).

Spends nothing: rejected inputs never reach a model, the replay miss never calls one, and the bad-key call is refused
by the API before any tokens are billed. Uses a throwaway data dir, so demo memory is not touched.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
LOG = ROOT / "docs" / "capstone" / "failure-log.jsonl"


def app(mode: str, key: str | None = None):
    from reclaim.env import load_env
    from reclaim.api.main import Settings, create_app
    from fastapi.testclient import TestClient
    work = Path(tempfile.mkdtemp(prefix="reclaim-probe-"))
    shutil.copytree(ROOT / "data", work / "data", ignore=shutil.ignore_patterns("uploads", "checkpoints.db*", "runs.jsonl", "restart_pending.json"))
    os.environ["RECLAIM_LLM_MODE"] = mode
    os.environ["RECLAIM_CACHE_DIR"] = str(work / "temp-cache") if mode != "replay" else str(ROOT / "fixtures" / "llm_cache")
    load_env()
    os.environ["RECLAIM_LLM_MODE"] = mode
    if key is not None:
        os.environ["ANTHROPIC_API_KEY"] = key
    cfg = Settings(fixtures=ROOT / "fixtures", data=work / "data", cases=work / "cases", today=date(2026, 11, 14), run_log=LOG)
    return TestClient(create_app(cfg))


def settle(c, rid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/runs/{rid}").json()["status"]
        if st in ("done", "error", "stopped", "waiting_approval"):
            return st
        time.sleep(0.2)
    return "timeout"


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    c = app("replay")
    print("missing fixture   ->", c.post("/api/runs", json={"fixture": "nope.csv"}).status_code)
    print("no input          ->", c.post("/api/runs", json={}).status_code)
    up = c.post("/api/uploads", files={"file": ("junk.csv", b"hello,this,is\nnot,a,payout\n", "text/csv")}).json()["upload_id"]
    print("not a payout file ->", c.post("/api/runs", json={"upload_id": up}).status_code)
    big = c.post("/api/uploads", files={"file": ("big.csv", b"x" * (2 * 1024 * 1024 + 10), "text/csv")})
    print("oversize upload   ->", big.status_code)
    # A valid payout the offline cache has never seen: replay mode must say so instead of inventing an answer.
    new = (ROOT / "fixtures" / "doordash_payout.csv").read_text().replace("DD-48230", "DD-99999")
    up = c.post("/api/uploads", files={"file": ("new.csv", new.encode(), "text/csv")}).json()["upload_id"]
    rid = c.post("/api/runs", json={"upload_id": up}).json()["run_id"]
    print("unseen file, replay ->", settle(c, rid))
    # A rejected API key: the model call fails and the run must end in a readable error, not hang.
    c2 = app("record", key="sk-ant-invalid-key-for-failure-probe")
    rid = c2.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
    print("bad API key       ->", settle(c2, rid))
    time.sleep(0.5)
    print("records:", len(LOG.read_text().splitlines()))


if __name__ == "__main__":
    main()
