"""LangSmith tracing glue (rule 8). Tracing is a side channel: it never changes what the agent sees or does.

LangChain/LangGraph trace automatically when LANGSMITH_TRACING=true and LANGSMITH_API_KEY is set. This module
only (1) switches tracing off, with a clear note, if it was requested without a key (otherwise every call logs
auth errors), (2) reports status to the UI, and (3) labels each run so traces are easy to find and honest about
what they are (replayed from cache vs live model, synthetic vs uploaded data).
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}


def _requested() -> bool:
    return any(os.getenv(k, "").strip().lower() in _TRUE for k in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"))


def _has_key() -> bool:
    return bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))


def ensure_consistent() -> str | None:
    """Tracing asked for but no key: turn it off and say why. Returns the note, or None if nothing changed."""
    if _requested() and not _has_key():
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        return "LANGSMITH_TRACING was on but LANGSMITH_API_KEY is empty, so tracing was switched off."
    return None


def status(note: str | None = None) -> dict:
    return {
        "enabled": _requested() and _has_key(),
        "project": os.getenv("LANGSMITH_PROJECT") or os.getenv("LANGCHAIN_PROJECT") or "default",
        "note": note,
    }


def run_config(run_id: str, llm_mode: str, source: str) -> dict:
    """Extra RunnableConfig fields: tags and metadata that appear on every trace of this run.
    thread_id groups the initial run and each post-approval resume into one conversation in LangSmith.
    No customer data goes in here."""
    return {
        "run_name": "reclaim-run",
        "tags": ["reclaim", f"llm:{llm_mode}", "replayed-from-cache" if llm_mode == "replay" else "live-model"],
        "metadata": {"app": "reclaim", "thread_id": run_id, "llm_mode": llm_mode,
                     "replayed_from_cache": llm_mode == "replay", "data": source},
    }
