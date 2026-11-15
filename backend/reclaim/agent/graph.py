from __future__ import annotations

import sqlite3
from pathlib import Path

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from langchain.agents.middleware import TodoListMiddleware
from langgraph.checkpoint.sqlite import SqliteSaver

from .session import Session
from .subagents import build_subagents, prompt
from .tools import build_tools

ORCH_TOOLS = ("load_payout", "triage_cases", "read_memory", "recall_similar_cases", "get_case", "send_dispute",
              "record_outcome")


def build_agent(session: Session, model, checkpoint_path: str | Path = ":memory:"):
    """One orchestrating deep agent, two subagents, and an approval interrupt on send_dispute (rule 1)."""
    tools = build_tools(session)
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    return create_deep_agent(
        model=model,
        tools=[tools[n] for n in ORCH_TOOLS],
        system_prompt=prompt("orchestrator"),
        subagents=build_subagents(tools),
        # deepagents 0.7 does not add a planning tool by itself; this supplies write_todos.
        middleware=[TodoListMiddleware()],
        # First matching rule wins. The agent may keep scratch notes; everything else is read-only so it cannot delete
        # or rewrite audit files (case.json, evidence, drafts, packets, decisions, traces) or the lessons memory.
        # Those are written only by our tools, which enforce the rules (approval gate, evidence ids, lint).
        permissions=[
            FilesystemPermission(operations=["write"], paths=["/plan.md", "/notes/**"], mode="allow"),
            FilesystemPermission(operations=["write"], paths=["/**"], mode="deny"),
        ],
        # Case notes go to cases/; /memory/ is persistent on disk and its AGENTS.md is loaded into every prompt.
        backend=CompositeBackend(
            default=FilesystemBackend(root_dir=session.cases_dir, virtual_mode=True),
            routes={"/memory/": FilesystemBackend(root_dir=session.memory_dir, virtual_mode=True)},
        ),
        memory=["/memory/AGENTS.md"],
        interrupt_on={"send_dispute": {"allowed_decisions": ["approve", "reject"],
                                       "description": "The owner must approve before anything is sent."}},
        checkpointer=SqliteSaver(conn),
        name="reclaim-orchestrator",
    )
