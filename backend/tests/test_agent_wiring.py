import json
from pathlib import Path

import pytest
from langgraph.types import Command

from reclaim.agent.graph import build_agent
from reclaim.agent.session import Session
from reclaim.schemas import CaseStatus
from tests.policy_model import PolicyChatModel


@pytest.fixture
def run(tmp_path, fix, today):
    PolicyChatModel.system_prompts.clear()
    s = Session(tmp_path / "cases", fix / "tickets.json", today, memory_dir=tmp_path / "memory")
    s.lessons_path.write_text("# Reclaim memory: lessons from past disputes\n\n- doordash:missing_item [x] won. Ticket plus handoff worked.\n")
    agent = build_agent(s, PolicyChatModel(), tmp_path / "ckpt.db")
    cfg = {"configurable": {"thread_id": "t1"}, "recursion_limit": 80}
    first = agent.invoke({"messages": [("user", f"Process the payout file at {fix / 'doordash_payout.csv'}.")]}, cfg)
    return s, agent, cfg, first


def interrupt_case(result):
    intr = result["__interrupt__"][0].value
    return intr["action_requests"][0]["args"]["case_id"]


def test_pauses_for_approval_and_sends_nothing(run):
    s, _, _, first = run
    assert "__interrupt__" in first
    assert first["__interrupt__"][0].value["action_requests"][0]["name"] == "send_dispute"
    assert not any(c.status == CaseStatus.SENT for c in s.cases.values())
    assert not list(s.cases_dir.glob("*/packet.md"))


def test_replans_and_demotes_weak_case(run):
    s, _, _, first = run
    assert any(e.type.value == "replan" and e.payload["case_id"] == "doordash:DD-48211" for e in s.events)
    assert s.get("doordash:DD-48211").weak
    assert interrupt_case(first) != "doordash:DD-48211"  # weak case is never offered for sending
    assert s.get("doordash:DD-48211").status != CaseStatus.AWAITING_APPROVAL


def test_approve_then_reject(run):
    s, agent, cfg, first = run
    c1 = interrupt_case(first)
    s.approve(c1)
    second = agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    assert s.get(c1).status == CaseStatus.SENT and (s.case_dir(c1) / "packet.md").exists()
    c2 = interrupt_case(second)
    assert c2 != c1
    s.skip(c2)
    last = agent.invoke(Command(resume={"decisions": [{"type": "reject", "message": "owner skipped"}]}), cfg)
    assert "__interrupt__" not in last
    assert s.get(c2).status == CaseStatus.SKIPPED and not (s.case_dir(c2) / "packet.md").exists()


def test_rejected_without_session_approval_still_cannot_send(run):
    """Defence in depth: even if the graph approved, the tool refuses without the owner-approval record."""
    s, agent, cfg, first = run
    c1 = interrupt_case(first)
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)  # graph approves, session does not
    assert s.get(c1).status == CaseStatus.AWAITING_APPROVAL and not (s.case_dir(c1) / "packet.md").exists()


def test_persistent_memory_reaches_the_prompt(run):
    assert any("Ticket plus handoff worked" in p for p in PolicyChatModel.system_prompts)


def test_case_folder_audit_trail(run):
    s, agent, cfg, first = run
    c1 = interrupt_case(first)
    s.approve(c1)
    agent.invoke(Command(resume={"decisions": [{"type": "approve"}]}), cfg)
    d = s.case_dir(c1)
    for f in ("case.json", "evidence.json", "draft.md", "trace.jsonl", "decision.json", "packet.md", "sent.json"):
        assert (d / f).exists(), f
    assert json.loads((d / "decision.json").read_text())["decision"] == "approved"
