import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from reclaim.api.main import Settings, create_app
from reclaim.photon.bridge import DEMO_OWNER, parse_reply
from tests.policy_model import PolicyChatModel
from tests.test_api import wait


@pytest.fixture
def client(tmp_path, fix):
    cfg = Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=date(2026, 11, 14),
                   model_factory=lambda: PolicyChatModel())
    return TestClient(create_app(cfg))


def text(c, body, sender=DEMO_OWNER):
    return c.post("/api/photon/inbound", json={"sender": sender, "text": body}).json()["reply"]


def start(c):
    return c.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]


@pytest.mark.parametrize("raw,kind", [("YES", "approve"), (" y ", "approve"), ("Yes!", "approve"), ("no", "skip"),
                                      ("skip", "skip"), ("lost", "lost"), ("WON $46.80", "won"), ("won 12", "won"),
                                      ("edit: new words", "edit"), ("yes but change it", "unknown"),
                                      ("yes please", "unknown"), ("maybe", "unknown"), ("", "unknown"),
                                      ("won lots", "unknown")])
def test_parse_reply_is_strict(raw, kind):
    assert parse_reply(raw).kind == kind


def test_won_amount_in_cents():
    assert parse_reply("WON $46.80").cents == 4680 and parse_reply("won 12").cents == 1200


def test_prompt_goes_out_and_yes_approves_through_the_same_gate(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    first = st["pending_case"]
    out = [m for m in client.get("/api/photon").json()["messages"] if m["direction"] == "out"]
    assert out and "Reply YES to approve" in out[0]["text"] and first.split(":")[1] in out[0]["text"]
    assert "Approved" in text(client, "YES")
    wait(client, run, "waiting_approval")           # the agent moved on to the next case
    assert client.get(f"/api/runs/{run}/cases/{first}").json()["status"] == "sent"


def test_unclear_reply_never_approves(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    assert "nothing was sent" in text(client, "yes but change the wording")
    time.sleep(0.2)
    assert client.get(f"/api/runs/{run}").json()["status"] == "waiting_approval"
    assert client.get(f"/api/runs/{run}/cases/{st['pending_case']}").json()["status"] != "sent"


def test_stranger_is_ignored_and_cannot_approve(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    assert client.post("/api/photon/inbound", json={"sender": "+15559999999", "text": "YES"}).json()["reply"] is None
    time.sleep(0.2)
    assert client.get(f"/api/runs/{run}").json()["status"] == "waiting_approval"
    assert client.get(f"/api/runs/{run}/cases/{st['pending_case']}").json()["status"] != "sent"


def test_no_skips_and_edit_faces_the_lint(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    bad = text(client, "EDIT This customer lied and committed fraud on order whatever")
    assert "did not send" in bad
    assert client.get(f"/api/runs/{run}").json()["status"] == "waiting_approval"
    assert "Skipped" in text(client, "NO")
    wait(client, run, "waiting_approval")


def test_web_decision_clears_stale_text_prompt(client):
    run = start(client)
    st = wait(client, run, "waiting_approval")
    first = st["pending_case"]
    client.post(f"/api/runs/{run}/cases/{first}/decision", json={"decision": "skip"})
    wait(client, run, "waiting_approval")           # next case; the bridge now points at it, not at `first`
    assert client.get("/api/photon").json()["pending"][1] != first


def test_outcome_by_text_feeds_memory(client):
    run = start(client)
    wait(client, run, "waiting_approval")
    text(client, "YES")
    before = client.get("/api/memory").json()["outcomes"]
    assert "Recorded" in text(client, "WON 25.00")
    assert client.get("/api/memory").json()["outcomes"] == before + 1
    assert "waiting for an outcome" in text(client, "LOST")


def test_shared_secret_enforced(client, monkeypatch):
    monkeypatch.setenv("PHOTON_INBOUND_SECRET", "s3cret")
    r = client.post("/api/photon/inbound", json={"sender": DEMO_OWNER, "text": "YES"})
    assert r.status_code == 401
    r = client.post("/api/photon/inbound", json={"sender": DEMO_OWNER, "text": "hi"}, headers={"X-Reclaim-Secret": "s3cret"})
    assert r.status_code == 200


def test_memory_counts_resolved_outcomes_only(client):
    run = start(client)
    wait(client, run, "waiting_approval")
    base = client.get("/api/memory").json()
    text(client, "YES")                                  # approving creates a pending row; it is not a result yet
    wait(client, run, "waiting_approval")                # the agent has resumed, filed the packet and moved on
    after_yes = client.get("/api/memory").json()
    assert after_yes["outcomes"] == base["outcomes"] and after_yes["pending"] == base["pending"] + 1
    text(client, "WON 25.00")
    after_won = client.get("/api/memory").json()
    assert after_won["outcomes"] == base["outcomes"] + 1 and after_won["pending"] == base["pending"]
