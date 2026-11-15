"""DEV/TEST ONLY. Deterministic stand-in for the LLM, used to test the agent wiring and develop the UI (graph, subagents, interrupt,
resume, memory in the prompt). It never produces anything that ships; the real model is recorded separately."""
from __future__ import annotations

import json
import re
import uuid
from typing import ClassVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

CASE_RE = re.compile(r"(?:doordash|ubereats):[A-Za-z0-9-]+")


def _call(name, args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}])


class PolicyChatModel(BaseChatModel):
    system_prompts: ClassVar[list[str]] = []
    max_targets: int = 3

    @property
    def _llm_type(self) -> str:
        return "policy"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kw):
        system = next((m.content for m in messages if isinstance(m, SystemMessage)), "")
        system = system if isinstance(system, str) else json.dumps(system)
        PolicyChatModel.system_prompts.append(system)
        if "EVIDENCE subagent" in system:
            msg = self._evidence(messages)
        elif "DISPUTE-WRITER subagent" in system:
            msg = self._writer(messages)
        else:
            msg = self._orchestrator(messages)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    # ---- subagents ---------------------------------------------------------------------------
    def _evidence(self, messages):
        task = next(m.content for m in messages if isinstance(m, HumanMessage))
        cid = CASE_RE.search(task).group(0)
        done = [m for m in messages if isinstance(m, ToolMessage)]
        seq = [("get_case", {"case_id": cid}), ("read_ticket_image", {"order_id": cid.split(":")[1]}),
               ("check_ticket_vs_claim", {"case_id": cid}), ("check_pickup_timestamps", {"case_id": cid}),
               ("check_repeat_claimant", {"case_id": cid})]
        if len(done) < len(seq):
            return _call(*seq[len(done)])
        ticket = json.loads(next(m.content for m in done if m.name == "check_ticket_vs_claim"))
        weak = ticket.get("weak", False)
        return AIMessage(content=f"VERDICT: {'weak' if weak else 'strong'}\n{cid}: evidence "
                                 f"{ticket['evidence']['id'] if ticket.get('evidence') else 'none'}.")

    def _writer(self, messages):
        task = next(m.content for m in messages if isinstance(m, HumanMessage))
        cid = CASE_RE.search(task).group(0)
        done = [m for m in messages if isinstance(m, ToolMessage)]
        if not done:
            return _call("get_case", {"case_id": cid})
        if len(done) == 1:
            case = json.loads(done[0].content)
            good = [e for e in case["evidence"] if e["supports"] >= 1]
            body = (f"We are asking for review of order {case['order_id']}, where {case['amount']} was deducted. "
                    + " ".join(f"{e['summary']} [{e['id']}]" for e in good)
                    + " We would appreciate a review and reversal of this deduction.")
            return _call("submit_dispute", {"case_id": cid, "body": body, "cited_evidence_ids": [e["id"] for e in good]})
        return AIMessage(content="Submitted for owner approval.")

    # ---- orchestrator ------------------------------------------------------------------------
    def _orchestrator(self, messages):
        human = next(m.content for m in messages if isinstance(m, HumanMessage))
        path = re.search(r"file at (\S+?)\.?$", human.strip()).group(1)
        tm = [m for m in messages if isinstance(m, ToolMessage)]
        names = [m.name for m in tm]
        if "load_payout" not in names:
            return _call("load_payout", {"path": path})
        if "triage_cases" not in names:
            return _call("triage_cases", {})
        queue = json.loads(next(m.content for m in tm if m.name == "triage_cases"))["queue"]
        targets = [q["case_id"] for q in queue if not q["recommend_skip"]][: self.max_targets]
        if "write_todos" not in names:
            return _call("write_todos", {"todos": [{"content": f"Investigate {c}", "status": "pending"} for c in targets]})
        tasks = [m for m in tm if m.name == "task"]
        n = len(targets)
        if len(tasks) < n:
            return _call("task", {"description": f"Gather and weigh evidence for case_id {targets[len(tasks)]}",
                                  "subagent_type": "evidence"})
        survivors = [c for c, t in zip(targets, tasks[:n]) if "VERDICT: weak" not in str(t.content)]
        if len(survivors) < n and names.count("write_todos") < 2:
            weak = [c for c in targets if c not in survivors]
            return _call("write_todos", {"todos": [{"content": f"Request ticket photo for {w}", "status": "pending"} for w in weak]
                                         + [{"content": f"Draft dispute for {c}", "status": "pending"} for c in survivors]})
        if len(tasks) < n + len(survivors):
            return _call("task", {"description": f"Draft the dispute for case_id {survivors[len(tasks) - n]}",
                                  "subagent_type": "dispute-writer"})
        sent = [m for m in tm if m.name == "send_dispute"]
        if len(sent) < len(survivors):
            return _call("send_dispute", {"case_id": survivors[len(sent)]})
        return AIMessage(content="Done. Drafts were handled as the owner decided.")
