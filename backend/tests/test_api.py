import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reclaim.api.main import Settings, create_app
from tests.policy_model import PolicyChatModel


@pytest.fixture
def client(tmp_path, fix):
    cfg = Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=date(2026, 11, 14),
                   model_factory=lambda: PolicyChatModel())
    return TestClient(create_app(cfg))


def wait(c, run, status, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/runs/{run}").json()
        if st["status"] == status:
            return st
        time.sleep(0.05)
    raise AssertionError(f"never reached {status}: {c.get(f'/api/runs/{run}').json()}")


def start(c):
    r = c.post("/api/runs", json={"fixture": "doordash_payout.csv"})
    assert r.status_code == 202
    return r.json()["run_id"]


def test_full_flow_approve_edit_skip(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    first = st["pending_case"]
    detail = client.get(f"/api/runs/{run}/cases/{first}").json()
    assert detail["draft"] and detail["ticket"]["image_url"].endswith(".png")
    assert client.get(detail["ticket"]["image_url"]).status_code == 200

    # edits are checked like agent drafts (rule 4)
    bad = client.post(f"/api/runs/{run}/cases/{first}/decision", json={"decision": "edit", "body": "The customer lied about order."})
    assert bad.status_code == 422
    good = detail["draft"] + " Thank you for taking another look."
    assert client.post(f"/api/runs/{run}/cases/{first}/decision", json={"decision": "edit", "body": good}).status_code == 202
    st = wait(client, run, "waiting_approval")
    second = st["pending_case"]
    assert second != first
    assert "Thank you for taking another look" in (client.get(f"/api/runs/{run}/cases/{first}").json()["draft"])
    assert client.get(f"/api/runs/{run}/cases/{first}").json()["status"] == "sent"

    assert client.post(f"/api/runs/{run}/cases/{second}/decision", json={"decision": "skip"}).status_code == 202
    wait(client, run, "done")
    states = {c["case_id"]: c["status"] for c in client.get(f"/api/runs/{run}/cases").json()["cases"]}
    assert states[first] == "sent" and states[second] == "skipped"


def test_decision_requires_the_pending_case(client):
    run = start(client)
    wait(client, run, "waiting_approval")
    r = client.post(f"/api/runs/{run}/cases/doordash:DD-48211/decision", json={"decision": "approve"})
    assert r.status_code == 409


def test_events_stream_plan_replan_and_interrupt(client):
    run = start(client)
    wait(client, run, "waiting_approval")
    types = [e["type"] for e in client.get(f"/api/runs/{run}/events.json").json()]
    assert "replan" in types and types[-1] == "interrupt" and "tool_call" in types
    assert client.get(f"/api/runs/{run}/events.json?after=2").json()[0]["id"] == 3


def test_sse_stream_ends_when_run_done(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    for _ in range(2):
        pending = client.get(f"/api/runs/{run}").json()["pending_case"]
        client.post(f"/api/runs/{run}/cases/{pending}/decision", json={"decision": "skip"})
        wait_status = "done" if _ else "waiting_approval"
        wait(client, run, wait_status)
    with client.stream("GET", f"/api/runs/{run}/events") as r:
        body = "".join(r.iter_text())
    assert "event: end" in body and '"type": "done"' in body


def test_outcome_updates_persistent_memory(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    c = st["pending_case"]
    r = client.post(f"/api/runs/{run}/cases/{c}/outcome", json={"result": "won", "recovered_cents": 1875, "lesson": "Ticket plus handoff won."})
    assert r.json()["ok"]
    m = client.get("/api/memory").json()
    assert "Ticket plus handoff won." in m["lessons"] and m["outcomes"] >= 1


def test_missing_cache_surfaces_a_clear_error(tmp_path, fix):
    from reclaim.llm import CachedChatModel
    cfg = Settings(fixtures=fix, data=tmp_path / "d", cases=tmp_path / "c", today=date(2026, 11, 14),
                   model_factory=lambda: CachedChatModel(cache_dir=tmp_path / "empty", mode="replay"))
    c = TestClient(create_app(cfg))
    run = start(c)
    wait(c, run, "error")
    ev = c.get(f"/api/runs/{run}/events.json").json()[-1]
    assert ev["type"] == "error" and ev["payload"]["kind"] == "cache_miss"


def test_rejects_bad_requests(client):
    assert client.post("/api/runs", json={}).status_code == 422
    assert client.post("/api/runs", json={"fixture": "nope.csv"}).status_code == 404
    assert client.get("/api/runs/zzz").status_code == 404
    assert client.get("/api/tickets/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_upload_then_run(client, fix):
    up = client.post("/api/uploads", files={"file": ("p.csv", (fix / "doordash_payout.csv").read_bytes(), "text/csv")})
    r = client.post("/api/runs", json={"upload_id": up.json()["upload_id"]})
    assert r.status_code == 202
    wait(client, r.json()["run_id"], "waiting_approval")


def test_garbage_upload_is_refused_before_any_model_call(client):
    up = client.post("/api/uploads", files={"file": ("x.csv", b"hello,world\n1,2\n")}).json()["upload_id"]
    r = client.post("/api/runs", json={"upload_id": up})
    assert r.status_code == 422 and "payout" in r.json()["detail"]


def test_empty_upload_and_oversize_upload(client):
    up = client.post("/api/uploads", files={"file": ("x.csv", b"")}).json()["upload_id"]
    assert client.post("/api/runs", json={"upload_id": up}).status_code == 422
    assert client.post("/api/uploads", files={"file": ("big.csv", b"a" * (2 * 1024 * 1024 + 10))}).status_code == 413


def test_path_traversal_and_unknown_inputs(client):
    assert client.post("/api/runs", json={"fixture": "../../etc/passwd"}).status_code == 404
    assert client.post("/api/runs", json={"upload_id": "../../x"}).status_code == 404
    assert client.post("/api/runs", json={}).status_code == 422
    assert client.get("/api/tickets/..%2F..%2F.env").status_code == 404
    assert client.get("/api/runs/nope").status_code == 404


def test_uploading_a_bundled_sample_runs_as_that_sample(client, fix):
    raw = (fix / "doordash_payout.csv").read_bytes()
    up = client.post("/api/uploads", files={"file": ("my_payout.csv", raw)}).json()["upload_id"]
    run = client.post("/api/runs", json={"upload_id": up}).json()["run_id"]
    wait(client, run, "waiting_approval")
    changed = raw.replace(b"21.50", b"21.51")
    up2 = client.post("/api/uploads", files={"file": ("other.csv", changed)}).json()["upload_id"]
    assert client.post("/api/runs", json={"upload_id": up2}).status_code == 202   # a different file is still accepted


def test_agent_files_are_listed_and_traversal_is_refused(client):
    run = start(client)
    wait(client, run, "waiting_approval")
    files = [f["path"] for f in client.get(f"/api/runs/{run}/files").json()]
    assert any(f.endswith("case.json") for f in files) and any(f.endswith("evidence.json") for f in files)
    first = next(f for f in files if f.endswith("case.json"))
    assert client.get(f"/api/runs/{run}/files/{first}").json()["text"]
    assert client.get(f"/api/runs/{run}/files/..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get(f"/api/runs/{run}/files/%2Fetc%2Fpasswd").status_code == 404
