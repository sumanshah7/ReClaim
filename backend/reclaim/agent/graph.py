from __future__ import annotations

import sqlite3
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
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
