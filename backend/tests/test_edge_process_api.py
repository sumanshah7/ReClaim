"""Areas 7-8: server/process edge cases (restart, code change) and model-API failures."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import ClassVar

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from reclaim.agent import session as session_mod
from reclaim.api.main import Settings, create_app
from reclaim.codewatch import CodeWatch
from reclaim.llm import MissingApiKey, make_model
from tests.policy_model import PolicyChatModel

BACKEND = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 14)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    """Never let the developer's real .env (which now holds a real key) leak into these tests."""
    monkeypatch.setattr("reclaim.api.main.load_env", lambda *a, **k: None)


def settings(tmp_path, fix, **kw):
    return Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                    model_factory=kw.pop("model_factory", lambda: PolicyChatModel()), **kw)


def wait_for(fn, timeout=15, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {what}")


def status(c, run):
    return c.get(f"/api/runs/{run}").json()["status"]


def start(c):
    return c.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]


# ================= Area 7a: the detector =====================================================================
def test_codewatch_notices_edits_additions_and_deletions_but_ignores_other_files(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1")
    w = CodeWatch([tmp_path])
    assert not w.changed()
    (tmp_path / "notes.txt").write_text("irrelevant")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "a.cpython-311.py").write_text("junk")
    assert not w.changed()
    f.write_text("x = 22")                       # edit (size differs)
    assert w.changed()
    w = CodeWatch([tmp_path])
    (tmp_path / "prompt.md").write_text("new prompt")      # addition (prompts are .md)
    assert w.changed()
    w = CodeWatch([tmp_path])
    f.unlink()                                   # deletion
    assert w.changed()


def test_codewatch_notices_a_same_size_edit_via_mtime(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1")
    w = CodeWatch([tmp_path])
    time.sleep(0.02)
    f.write_text("x = 2")
    os.utime(f, ns=(time.time_ns(), time.time_ns() + 5_000_000))
    assert w.changed()


# ================= Area 7b: stopping the old run when code changes ===========================================
class Hook:
    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1


@pytest.fixture
def watched(tmp_path, fix):
    wd = tmp_path / "src"
    wd.mkdir()
    (wd / "mod.py").write_text("v = 1")
    hook = Hook()
    c = TestClient(create_app(settings(tmp_path, fix, watch_dirs=[wd], restart_hook=hook, watch_interval=0.05)))
    return c, wd, hook, tmp_path


def edit(wd):
    (wd / "mod.py").write_text("v = 2  # edited while a run was in progress")


def test_a_code_change_stops_a_run_that_is_waiting_for_approval(watched):
    c, wd, hook, tmp = watched
    run = start(c)
    wait_for(lambda: status(c, run) == "waiting_approval", what="waiting_approval")
    case = c.get(f"/api/runs/{run}").json()["pending_case"]
    edit(wd)
    wait_for(lambda: status(c, run) == "stopped", 5, "stopped")
    evs = c.get(f"/api/runs/{run}/events.json").json()
    assert any(e["type"] == "error" and e["payload"]["kind"] == "code_changed" for e in evs)
    r = c.post(f"/api/runs/{run}/cases/{case}/decision", json={"decision": "approve"})
    assert r.status_code == 409 and "code changed" in r.json()["detail"]
    assert c.get(f"/api/runs/{run}/cases/{case}").json()["status"] != "sent"      # nothing was sent on stale code
    wait_for(lambda: hook.calls == 1, 3, "restart hook")
    marker = json.loads((tmp / "data" / "restart_pending.json").read_text())
    assert marker["runs"][0]["old_id"] == run and marker["runs"][0]["source"] == {"fixture": "doordash_payout.csv"}


class SlowModel(PolicyChatModel):
    def _generate(self, *a, **k):
        time.sleep(0.25)
        return super()._generate(*a, **k)


def test_a_code_change_stops_a_run_that_is_mid_flight_and_it_stays_stopped(tmp_path, fix):
    wd = tmp_path / "src"
    wd.mkdir()
    (wd / "mod.py").write_text("v = 1")
    hook = Hook()
    c = TestClient(create_app(settings(tmp_path, fix, watch_dirs=[wd], restart_hook=hook, watch_interval=0.05,
                                       model_factory=lambda: SlowModel())))
    run = start(c)
    wait_for(lambda: len(c.get(f"/api/runs/{run}/events.json").json()) >= 1, what="first event")
    assert status(c, run) == "running"
    edit(wd)
    wait_for(lambda: status(c, run) == "stopped", 5, "stopped")
    n = len(c.get(f"/api/runs/{run}/events.json").json())
    time.sleep(1.5)                              # the background thread must not revive or finish the run
    assert status(c, run) == "stopped"
    after = c.get(f"/api/runs/{run}/events.json").json()
    assert not any(e["type"] in ("interrupt", "done") for e in after)
    assert len(after) <= n + 1
    assert all(cs["status"] != "sent" for cs in c.get(f"/api/runs/{run}/cases").json()["cases"])


def test_a_code_change_with_no_active_run_still_restarts_without_a_marker(watched):
    c, wd, hook, tmp = watched
    edit(wd)
    wait_for(lambda: hook.calls == 1, 3, "restart hook")
    assert not (tmp / "data" / "restart_pending.json").exists()


def test_further_edits_do_not_trigger_a_second_restart(watched):
    c, wd, hook, _ = watched
    edit(wd)
    wait_for(lambda: hook.calls == 1, 3, "restart hook")
    for i in range(3):
        (wd / "mod.py").write_text(f"v = {i + 10}")
        time.sleep(0.15)
    assert hook.calls == 1


def test_non_source_changes_never_stop_a_run(watched):
    c, wd, hook, _ = watched
    run = start(c)
    wait_for(lambda: status(c, run) == "waiting_approval", what="waiting_approval")
    (wd / "log.txt").write_text("not source")
    time.sleep(0.5)
    assert status(c, run) == "waiting_approval" and hook.calls == 0


def test_the_fresh_process_relaunches_the_interrupted_run_on_new_code(watched, fix):
    c, wd, hook, tmp = watched
    old = start(c)
    wait_for(lambda: status(c, old) == "waiting_approval", what="waiting_approval")
    edit(wd)
    wait_for(lambda: hook.calls == 1, 3, "restart hook")
    # a brand-new app on the same data dir stands in for the re-exec'd process
    c2 = TestClient(create_app(settings(tmp, fix)))
    st = c2.get(f"/api/runs/{old}").json()
    assert st["status"] == "stopped" and st["replaced_by"]
    new = st["replaced_by"]
    assert new != old
    wait_for(lambda: status(c2, new) == "waiting_approval", what="fresh run waiting_approval")
    assert not (tmp / "data" / "restart_pending.json").exists()          # consumed exactly once
    assert c2.get(f"/api/runs/{old}/cases").status_code == 404           # the old run's state is gone, not half-alive


# ---- real processes -------------------------------------------------------------------------------------
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn(tmp_path, port, watch_dir=None):
    env = {**os.environ, "RECLAIM_LLM_MODE": "scripted", "RECLAIM_DATA_DIR": str(tmp_path / "data"),
           "RECLAIM_CASES_DIR": str(tmp_path / "cases"), "PYTHONUNBUFFERED": "1"}
    env.pop("ANTHROPIC_API_KEY", None)
    if watch_dir:
        env.update(RECLAIM_RESTART_ON_CODE_CHANGE="1", RECLAIM_WATCH_DIRS=str(watch_dir))
    else:
        env.pop("RECLAIM_RESTART_ON_CODE_CHANGE", None)
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "reclaim.api.main:create_app", "--factory",
                          "--port", str(port), "--log-level", "warning"], cwd=BACKEND, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"

    def up():
        try:
            return httpx.get(f"{base}/api/health", timeout=1).json()
        except Exception:
            return None

    try:
        h = wait_for(up, 30, "server to start")
    except AssertionError:
        p.kill()
        raise
    return p, base, h


def get(base, path):
    try:
        return httpx.get(base + path, timeout=2)
    except Exception:
        return None


def test_killing_the_server_mid_run_leaves_clean_state_and_the_next_start_works(tmp_path):
    port = free_port()
    p, base, _ = spawn(tmp_path, port)
    try:
        run = httpx.post(f"{base}/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
        wait_for(lambda: (r := get(base, f"/api/runs/{run}")) and r.json()["status"] == "waiting_approval", 20, "waiting")
    finally:
        p.kill()                                  # SIGKILL: no chance to clean up
        p.wait(10)
    p2, base2, _ = spawn(tmp_path, free_port())
    try:
        gone = httpx.get(f"{base2}/api/runs/{run}")
        assert gone.status_code == 404 and gone.json()["detail"] == "unknown run"          # clean refusal, not a crash
        assert httpx.post(f"{base2}/api/runs/{run}/cases/doordash:X/decision", json={"decision": "approve"}).status_code == 404
        con = sqlite3.connect(tmp_path / "data" / "reclaim.db")
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        for f in (tmp_path / "cases" / run).rglob("*.json"):
            json.loads(f.read_text())             # every persisted case file is whole, valid JSON
        new = httpx.post(f"{base2}/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
        wait_for(lambda: (r := get(base2, f"/api/runs/{new}")) and r.json()["status"] == "waiting_approval", 20, "new run")
    finally:
        p2.kill()
        p2.wait(10)


def test_editing_source_in_a_live_server_restarts_it_and_relaunches_the_run(tmp_path):
    wd = tmp_path / "src"
    wd.mkdir()
    (wd / "mod.py").write_text("v = 1")
    p, base, h1 = spawn(tmp_path, free_port(), watch_dir=wd)
    try:
        assert h1["code_watch"]
        old = httpx.post(f"{base}/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
        wait_for(lambda: (r := get(base, f"/api/runs/{old}")) and r.json()["status"] == "waiting_approval", 20, "waiting")
        (wd / "mod.py").write_text("v = 2  # edit while the run waits")

        def replaced():
            r = get(base, f"/api/runs/{old}")          # connection errors while the process re-execs are expected
            return r.json() if r is not None and r.status_code == 200 and r.json().get("replaced_by") else None

        st = wait_for(replaced, 40, "old run reported as replaced")
        new = st["replaced_by"]
        assert st["status"] == "stopped"
        wait_for(lambda: (r := get(base, f"/api/runs/{new}")) and r.json()["status"] == "waiting_approval", 20, "fresh run")
        h2 = httpx.get(f"{base}/api/health").json()
        assert h2["boot_id"] != h1["boot_id"]           # a genuinely new process image, so new code is loaded
    finally:
        p.kill()
        p.wait(10)


def test_a_crash_mid_write_leaves_the_previous_file_intact(tmp_path, monkeypatch):
    from reclaim.agent.session import atomic_write
    f = tmp_path / "case.json"
    atomic_write(f, '{"v": 1}')

    def boom(*a, **k):
        raise OSError("disk went away")

    monkeypatch.setattr(session_mod.os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(f, '{"v": 2}')
    assert json.loads(f.read_text()) == {"v": 1}


# ================= Area 8: the model API =====================================================================
REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _resp(code):
    return httpx.Response(code, request=REQ)


FAILS = {
    "timeout": (anthropic.APITimeoutError(request=REQ), "did not respond in time"),
    "network": (anthropic.APIConnectionError(request=REQ), "Could not reach the Anthropic API"),
    "auth": (anthropic.AuthenticationError("invalid x-api-key", response=_resp(401), body=None), "API key was rejected"),
    "rate": (anthropic.RateLimitError("slow down", response=_resp(429), body=None), "rate-limited"),
    "overloaded": (anthropic.InternalServerError("overloaded", response=_resp(529), body=None), "model service had a problem"),
}


def failing_factory(exc, when):
    """The first model fails according to `when(messages)`; later ones are healthy."""
    made = []

    class M(PolicyChatModel):
        def _generate(self, messages, *a, **k):
            if when(messages):
                raise exc
            return super()._generate(messages, *a, **k)

    def factory():
        made.append(1)
        return M() if len(made) == 1 else PolicyChatModel()

    return factory


@pytest.mark.parametrize("name", list(FAILS))
def test_a_model_failure_before_any_decision_ends_the_run_cleanly(tmp_path, fix, name):
    exc, words = FAILS[name]
    seen = []
    c = TestClient(create_app(settings(tmp_path, fix, model_factory=failing_factory(
        exc, lambda m: len(seen.append(1) or seen) >= 4))))
    run = start(c)
    wait_for(lambda: status(c, run) == "error", 15, "error")
    err = next(e for e in c.get(f"/api/runs/{run}/events.json").json() if e["type"] == "error")["payload"]
    assert words in err["message"], err
    assert all(cs["status"] != "sent" for cs in c.get(f"/api/runs/{run}/cases").json()["cases"])
    assert c.post(f"/api/runs/{run}/cases/doordash:DD-48230/decision", json={"decision": "approve"}).status_code == 409
    again = start(c)                                               # the app is not wedged: a new run works
    wait_for(lambda: status(c, again) == "waiting_approval", 15, "healthy run")


def test_a_failure_right_after_an_approval_keeps_the_sent_state_consistent(tmp_path, fix):
    after_send = lambda msgs: any(getattr(m, "type", "") == "tool" and getattr(m, "name", "") == "send_dispute" for m in msgs)
    c = TestClient(create_app(settings(tmp_path, fix, model_factory=failing_factory(FAILS["timeout"][0], after_send))))
    run = start(c)
    wait_for(lambda: status(c, run) == "waiting_approval", 15, "waiting")
    case = c.get(f"/api/runs/{run}").json()["pending_case"]
    assert c.post(f"/api/runs/{run}/cases/{case}/decision", json={"decision": "approve"}).status_code == 202
    wait_for(lambda: status(c, run) == "error", 15, "error")
    assert c.get(f"/api/runs/{run}/cases/{case}").json()["status"] == "sent"          # the approved action completed once
    sent = [e for e in c.get(f"/api/runs/{run}/events.json").json()
            if e["type"] == "tool_call" and e["payload"].get("tool") == "send_dispute"]
    assert len(sent) == 1
    assert (tmp_path / "cases" / run / case.replace(":", "_") / "packet.md").exists()
    assert c.post(f"/api/runs/{run}/cases/{case}/decision", json={"decision": "approve"}).status_code == 409


def test_error_messages_never_contain_the_api_key(tmp_path, fix, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SUPERSECRETKEY123456")
    boom = RuntimeError("request failed with x-api-key sk-ant-api03-SUPERSECRETKEY123456 and other sk-live-abcdefghijk")
    c = TestClient(create_app(settings(tmp_path, fix, model_factory=failing_factory(boom, lambda m: True))))
    run = start(c)
    wait_for(lambda: status(c, run) == "error", 15, "error")
    text = json.dumps(c.get(f"/api/runs/{run}/events.json").json())
    assert "SUPERSECRET" not in text and "abcdefghijk" not in text and "[redacted key]" in text


def test_replay_miss_is_reported_as_a_cache_miss_not_a_hang(tmp_path, fix):
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                                       model_factory=lambda: make_model(tmp_path / "empty_cache", mode="replay"))))
    run = start(c)
    wait_for(lambda: status(c, run) == "error", 15, "error")
    err = next(e for e in c.get(f"/api/runs/{run}/events.json").json() if e["type"] == "error")["payload"]
    assert err["kind"] == "cache_miss"


@pytest.mark.parametrize("mode", ["record", "auto"])
@pytest.mark.parametrize("key", [None, "", "   "])
def test_live_mode_without_a_key_fails_at_startup_with_a_clear_message(tmp_path, fix, monkeypatch, mode, key):
    monkeypatch.setenv("RECLAIM_LLM_MODE", mode)
    if key is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    with pytest.raises(MissingApiKey, match="ANTHROPIC_API_KEY"):
        create_app(Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY))
    with pytest.raises(MissingApiKey, match="replay"):          # and the message says how to run without one
        make_model(tmp_path / "c", mode=mode)


def test_with_no_key_and_no_mode_the_app_runs_offline_in_replay(tmp_path, fix, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("RECLAIM_LLM_MODE", raising=False)
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY)))
    h = c.get("/api/health").json()
    assert h["llm_mode"] == "replay" and h["api_key"] == "missing"


def test_a_key_that_disappears_after_startup_gives_a_503_not_a_hang(tmp_path, fix, monkeypatch):
    monkeypatch.setenv("RECLAIM_LLM_MODE", "record")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-1234567890")
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY)))
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    r = c.post("/api/runs", json={"fixture": "doordash_payout.csv"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_live_model_calls_have_a_bounded_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-1234567890")
    inner = make_model(tmp_path / "c", mode="record").inner
    assert inner.default_request_timeout == 60 and inner.max_retries == 2
