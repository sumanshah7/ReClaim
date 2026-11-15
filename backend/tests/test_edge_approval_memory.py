"""Areas 5-6: approval-flow races and memory/database edge cases."""
import multiprocessing as mp
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from langchain_core.messages import AIMessage, ToolMessage

from reclaim.agent.session import Session
from reclaim.api.main import Settings, _memory_view, create_app
from reclaim.schemas import ClaimReason, Outcome, OutcomeResult
from reclaim.triage.memory import Memory
from tests.edge_helpers import ded
from tests.policy_model import PolicyChatModel

TODAY = date(2026, 11, 14)
TICKETS = Path(__file__).resolve().parents[2] / "fixtures" / "tickets.json"
OWNER = "+15550100"


@pytest.fixture
def client(tmp_path, fix):
    cfg = Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                   model_factory=lambda: PolicyChatModel())
    return TestClient(create_app(cfg))


def wait(c, run, status, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/runs/{run}").json()
        if st["status"] == status:
            return st
        time.sleep(0.03)
    raise AssertionError(f"never reached {status}: {c.get(f'/api/runs/{run}').json()}")


def pending(client):
    run = client.post("/api/runs", json={"fixture": "doordash_payout.csv"}).json()["run_id"]
    return run, wait(client, run, "waiting_approval")["pending_case"]


def decide(c, run, case, d, **kw):
    return c.post(f"/api/runs/{run}/cases/{case}/decision", json={"decision": d, **kw})


def case_status(c, run, case):
    return c.get(f"/api/runs/{run}/cases/{case}").json()["status"]


# ================= Area 5: approval flow ======================================================================
def test_approving_the_same_case_twice_is_refused(client):
    run, case = pending(client)
    assert decide(client, run, case, "approve").status_code == 202
    again = decide(client, run, case, "approve")
    assert again.status_code == 409
    wait(client, run, "waiting_approval")
    assert case_status(client, run, case) == "sent"


def test_skipping_after_approving_is_refused_and_the_dispute_stays_sent(client):
    run, case = pending(client)
    assert decide(client, run, case, "approve").status_code == 202
    assert decide(client, run, case, "skip").status_code == 409
    wait(client, run, "waiting_approval")
    assert case_status(client, run, case) == "sent"


def test_approving_after_skipping_is_refused_and_nothing_is_sent(client):
    run, case = pending(client)
    assert decide(client, run, case, "skip").status_code == 202
    assert decide(client, run, case, "approve").status_code == 409
    wait(client, run, "waiting_approval")
    assert case_status(client, run, case) == "skipped"


def test_simultaneous_approvals_send_exactly_one_dispute(client):
    run, case = pending(client)
    barrier = threading.Barrier(8)

    def go(_):
        barrier.wait()
        return decide(client, run, case, "approve").status_code

    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(go, range(8)))
    assert sorted(codes) == [202] + [409] * 7, codes
    wait(client, run, "waiting_approval")
    sent_calls = [e for e in client.get(f"/api/runs/{run}/events.json").json()
                  if e["type"] == "tool_call" and e["payload"].get("tool") == "send_dispute"
                  and e["payload"].get("args", {}).get("case_id") == case]
    assert len(sent_calls) == 1
    assert case_status(client, run, case) == "sent"


@pytest.mark.parametrize("trial", range(3))
def test_simultaneous_approve_and_skip_have_one_winner_and_a_consistent_result(client, trial):
    run, case = pending(client)
    barrier = threading.Barrier(2)
    out = {}

    def go(kind):
        barrier.wait()
        out[kind] = decide(client, run, case, kind).status_code

    ts = [threading.Thread(target=go, args=(k,)) for k in ("approve", "skip")]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out.values()) == [202, 409], out
    winner = next(k for k, v in out.items() if v == 202)
    wait(client, run, "waiting_approval")
    assert case_status(client, run, case) == ("sent" if winner == "approve" else "skipped")


def test_a_decision_when_nothing_is_pending_is_refused(client):
    run, case = pending(client)
    for _ in range(3):
        st = wait(client, run, "waiting_approval")
        decide(client, run, st["pending_case"], "skip")
        time.sleep(0.05)
        wait(client, run, "waiting_approval" if client.get(f"/api/runs/{run}").json()["status"] != "done" else "done")
        if client.get(f"/api/runs/{run}").json()["status"] == "done":
            break
    wait(client, run, "done")
    assert decide(client, run, case, "approve").status_code == 409
    assert decide(client, run, "doordash:NOPE", "approve").status_code == 409


def test_decisions_for_an_unknown_run_or_the_wrong_case_are_refused(client):
    assert decide(client, "doesnotexist", "doordash:X", "approve").status_code == 404
    run, case = pending(client)
    other = next(c["case_id"] for c in client.get(f"/api/runs/{run}/cases").json()["cases"] if c["case_id"] != case)
    assert decide(client, run, other, "approve").status_code == 409
    assert case_status(client, run, other) != "sent"


def test_an_edit_without_text_is_refused_and_leaves_the_case_pending(client):
    run, case = pending(client)
    assert decide(client, run, case, "edit").status_code == 422
    assert client.get(f"/api/runs/{run}").json()["status"] == "waiting_approval"
    assert decide(client, run, case, "approve").status_code == 202       # still decidable afterwards


def test_a_text_yes_with_nothing_pending_does_nothing(client):
    r = client.post("/api/photon/inbound", json={"sender": OWNER, "text": "YES"}).json()
    assert "Nothing is waiting" in str(r)


def test_a_text_yes_and_a_web_approval_at_once_send_one_dispute(client):
    run, case = pending(client)
    barrier = threading.Barrier(2)
    res = {}

    def web():
        barrier.wait(); res["web"] = decide(client, run, case, "approve").status_code

    def text():
        barrier.wait(); res["text"] = client.post("/api/photon/inbound", json={"sender": OWNER, "text": "YES"}).status_code

    ts = [threading.Thread(target=web), threading.Thread(target=text)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    wait(client, run, "waiting_approval")
    assert case_status(client, run, case) == "sent"
    sent = [e for e in client.get(f"/api/runs/{run}/events.json").json()
            if e["type"] == "tool_call" and e["payload"].get("tool") == "send_dispute"
            and e["payload"].get("args", {}).get("case_id") == case]
    assert len(sent) == 1


# ================= Area 6: memory and database ================================================================
def test_a_fresh_install_has_no_history_and_the_app_still_works(tmp_path, fix):
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "brand_new", cases=tmp_path / "cases", today=TODAY,
                                       model_factory=lambda: PolicyChatModel())))
    m = c.get("/api/memory").json()
    assert m["outcomes"] == 0 and m["pending"] == 0 and m["lessons"] in ([], "")
    run, case = pending(c)
    assert c.get(f"/api/runs/{run}/cases/{case}").json()["memory"] is None


def test_memory_with_no_rows_reports_zero_and_uses_the_broad_scope():
    mem = Memory(":memory:")
    assert mem.stats("doordash:missing_item") == (0, 0)
    assert mem.best_stats("doordash:missing_item", "pickup_handoff+1") == ((0, 0), "same claim type")
    assert mem.similar("doordash:missing_item", "x") == [] and mem.count() == mem.resolved_count() == 0


def test_equal_wins_and_losses_pull_the_estimate_toward_fifty_percent(tmp_path):
    s = Session(tmp_path / "cases", TICKETS, TODAY, memory_dir=tmp_path / "mem")
    s.ingest([ded()])
    for i, res in enumerate(["won", "lost", "won", "lost"]):
        s.record_outcome(Outcome(case_id=f"h{i}", result=OutcomeResult(res), reason_pattern="doordash:missing_item",
                                 signature="", claimed_item="x"))
    m = _memory_view(s, s.get(ded().id))
    assert (m["won"], m["total"]) == (2, 4)
    assert 50 <= m["adjusted_pct"] < m["base_pct"] == 55        # 2/4 is below the 55% base: lowered, never zero or 100


def test_all_losses_never_drive_the_estimate_to_zero(tmp_path):
    s = Session(tmp_path / "cases", TICKETS, TODAY, memory_dir=tmp_path / "mem")
    s.ingest([ded()])
    for i in range(30):
        s.record_outcome(Outcome(case_id=f"l{i}", result=OutcomeResult.LOST, reason_pattern="doordash:missing_item"))
    c = s.get(ded().id)
    s2 = Session(tmp_path / "c2", TICKETS, TODAY, memory=s.memory, memory_dir=tmp_path / "mem2")
    s2.ingest([ded()])
    assert s2.get(ded().id).p_win_bp >= 500


def test_recording_the_same_case_twice_keeps_one_row():
    mem = Memory(":memory:")
    for res in ("pending", "won"):
        mem.record(Outcome(case_id="c1", result=OutcomeResult(res), reason_pattern="doordash:missing_item"))
    assert mem.count() == 1 and mem.resolved_count() == 1


def _writer(db_path: str, worker: int, n: int, q) -> None:
    try:
        m = Memory(db_path)
        for i in range(n):
            m.record(Outcome(case_id=f"w{worker}-{i}", result=OutcomeResult.WON, recovered_cents=100,
                             reason_pattern="doordash:missing_item"))
            m.record(Outcome(case_id="shared", result=OutcomeResult.LOST, reason_pattern="doordash:missing_item"))
        q.put(("ok", worker))
    except Exception as e:  # noqa: BLE001
        q.put(("error", f"{type(e).__name__}: {e}"))


def test_two_processes_writing_outcomes_at_once_lose_nothing(tmp_path):
    db = str(tmp_path / "shared.db")
    Memory(db)                                   # create the schema once, as a running app would have
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_writer, args=(db, w, 60, q)) for w in range(4)]
    [p.start() for p in procs]
    [p.join(60) for p in procs]
    results = [q.get(timeout=5) for _ in procs]
    assert all(r[0] == "ok" for r in results), results
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 4 * 60 + 1
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


# ---- the model asks to send several disputes in one turn (parallel tool calls) ---------------------------
class ParallelSendModel(PolicyChatModel):
    """Like the scripted model, but its first send turn asks to send two disputes at once, as the real model did."""

    def _orchestrator(self, messages):
        first = super()._orchestrator(messages)
        sent = [m for m in messages if isinstance(m, ToolMessage) and m.name == "send_dispute"]
        if sent or not (first.tool_calls and first.tool_calls[0]["name"] == "send_dispute"):
            return first
        second = super()._orchestrator(messages + [ToolMessage(content="{}", name="send_dispute", tool_call_id="fake")])
        calls = first.tool_calls + ([second.tool_calls[0]] if second.tool_calls and second.tool_calls[0]["name"] == "send_dispute" else [])
        return AIMessage(content="", tool_calls=calls)


@pytest.fixture
def pclient(tmp_path, fix):
    return TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "data", cases=tmp_path / "cases", today=TODAY,
                                          model_factory=lambda: ParallelSendModel())))


def sends(c, run):
    return [e["payload"]["args"]["case_id"] for e in c.get(f"/api/runs/{run}/events.json").json()
            if e["type"] == "tool_call" and e["payload"].get("tool") == "send_dispute"]


def test_parallel_send_requests_are_decided_one_at_a_time_and_nothing_is_sent_early(pclient):
    c = pclient
    run, a = pending(c)
    assert decide(c, run, a, "approve").status_code == 202
    b = wait_for_other(c, run, a)                       # the gate moved on to the second request, still waiting
    assert b != a and c.get(f"/api/runs/{run}").json()["status"] == "waiting_approval"
    assert sends(c, run) == [] and case_status(c, run, a) != "sent"      # approved, but nothing is sent until all are decided
    assert decide(c, run, a, "approve").status_code == 409               # A is already decided
    assert decide(c, run, b, "approve").status_code == 202
    wait(c, run, "done")                                # now the graph ran: both were sent and the run finished
    assert case_status(c, run, a) == "sent" and case_status(c, run, b) == "sent"
    assert sorted(sends(c, run)) == sorted([a, b])


def test_parallel_requests_can_be_mixed_skip_then_approve(pclient):
    c = pclient
    run, a = pending(c)
    assert decide(c, run, a, "skip").status_code == 202
    b = wait_for_other(c, run, a)
    assert decide(c, run, b, "approve").status_code == 202
    wait(c, run, "done")
    assert case_status(c, run, a) == "skipped" and case_status(c, run, b) == "sent"
    assert a not in sends(c, run) and b in sends(c, run)


def test_parallel_requests_cannot_be_decided_out_of_order(pclient):
    c = pclient
    run, a = pending(c)
    decide(c, run, a, "approve")
    b = wait_for_other(c, run, a)
    other = next(x["case_id"] for x in c.get(f"/api/runs/{run}/cases").json()["cases"] if x["case_id"] not in (a, b))
    assert decide(c, run, other, "approve").status_code == 409


def test_text_replies_walk_through_parallel_requests(pclient):
    c = pclient
    run, a = pending(c)
    assert "Approved" in str(c.post("/api/photon/inbound", json={"sender": OWNER, "text": "YES"}).json())
    b = wait_for_other(c, run, a)
    assert "Approved" in str(c.post("/api/photon/inbound", json={"sender": OWNER, "text": "YES"}).json())
    wait(c, run, "done")
    assert case_status(c, run, a) == "sent" and case_status(c, run, b) == "sent"


def wait_for_other(c, run, previous, timeout=15):
    """Wait until the run is waiting for a decision on a different case than `previous`."""
    end = time.time() + timeout
    while time.time() < end:
        st = c.get(f"/api/runs/{run}").json()
        if st["status"] == "waiting_approval" and st["pending_case"] not in (None, previous):
            return st["pending_case"]
        time.sleep(0.03)
    raise AssertionError(f"never moved past {previous}: {c.get(f'/api/runs/{run}').json()}")
