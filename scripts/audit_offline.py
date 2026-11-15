"""Replay-cache audit (rule 9). Runs every sample through the real API in replay mode with all network access blocked,
down both recorded decision paths, and fails loudly on any cache miss or error.

  backend/.venv/bin/python scripts/audit_offline.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.environ["RECLAIM_LLM_MODE"] = "replay"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["LANGSMITH_TRACING"] = "false"

# Block every outbound connection except loopback: if anything tries to reach the internet, the audit fails.
_real = socket.socket.connect


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else str(addr)
    if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
        raise OSError(f"NETWORK BLOCKED by audit: {addr}")
    return _real(self, addr)


socket.socket.connect = _guard

from fastapi.testclient import TestClient  # noqa: E402

from reclaim.api.main import Settings, create_app  # noqa: E402

PATHS = {"first-then-skip": ["approve", "skip", "skip", "skip"], "approve-all": ["approve"] * 4}


def wait(c, run, want, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/runs/{run}").json()
        if st["status"] in want:
            return st
        time.sleep(0.05)
    raise SystemExit(f"timeout waiting for {want}")


def main() -> int:
    samples = [x["file"] for x in json.loads((ROOT / "fixtures" / "samples.json").read_text())]
    bad = 0
    for f in samples:
        for name, decisions in PATHS.items():
            tmp = Path(tempfile.mkdtemp())
            shutil.copytree(ROOT / "data", tmp / "data", ignore=shutil.ignore_patterns("uploads", "checkpoints.db*"))
            c = TestClient(create_app(Settings(data=tmp / "data", cases=tmp / "cases", today=date(2026, 11, 14))))
            run = c.post("/api/runs", json={"fixture": f}).json()["run_id"]
            decided = []
            for i in range(20):          # however many prompts there are; the last decision repeats for the rest
                st = wait(c, run, {"waiting_approval", "done", "error"})
                if st["status"] != "waiting_approval":
                    break
                d = decisions[min(i, len(decisions) - 1)]
                decided.append(d)
                c.post(f"/api/runs/{run}/cases/{st['pending_case']}/decision", json={"decision": d})
            st = wait(c, run, {"done", "error"})
            ok = st["status"] == "done"
            err = "" if ok else next((e["payload"] for e in c.get(f"/api/runs/{run}/events.json").json() if e["type"] == "error"), "")
            print(f"{'PASS' if ok else 'FAIL'}  {f:55s} {name:16s} decisions={len(decided)} {err}")
            bad += not ok
            shutil.rmtree(tmp, ignore_errors=True)
    print("\nAUDIT", "FAILED" if bad else "PASSED", f"({bad} failing)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
