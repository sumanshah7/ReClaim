"""Record/replay chat model so the demo runs offline from cached data (rule 9).

Wraps any chat model. Responses are stored per request hash. Modes:
  replay: cache only. A miss raises CacheMiss.
  record: always call the real model and store.
  auto:   use the cache on a hit, otherwise call the real model and store.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

DEFAULT_MODEL = "claude-sonnet-5-5"
# The largest response in 266 recorded calls was 889 output tokens, so 1200 leaves headroom without leaving the
# default (2048) as an open-ended ceiling. Override with RECLAIM_MAX_TOKENS.
DEFAULT_MAX_TOKENS = 1200
CACHE_CONTROL = {"type": "ephemeral"}

# Running totals from the API's own usage report, so caching is confirmed from cache_read_input_tokens
# (langchain exposes it as input_token_details.cache_read) rather than assumed.
USAGE: dict[str, int] = {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}


# Usage for the segment currently running in this context (set by the API for each agent segment). The global USAGE
# above counts the whole process, so two overlapping runs would each see the other's calls; this one is per run.
RUN_USAGE: ContextVar[dict | None] = ContextVar("reclaim_run_usage", default=None)
_USAGE_LOCK = threading.Lock()


def new_usage() -> dict[str, int]:
    return {"calls": 0, "input": 0, "cache_read": 0, "cache_creation": 0, "output": 0}


def record_usage(msg: BaseMessage) -> None:
    u = getattr(msg, "usage_metadata", None) or {}
    d = u.get("input_token_details") or {}
    one = {"calls": 1, "input": u.get("input_tokens", 0),   # langchain's input_tokens already includes cached tokens
           "cache_read": d.get("cache_read", 0) or 0,
           # Writes show up as cache_creation or, with ttl-aware responses, split into the ephemeral_* keys.
           "cache_creation": (d.get("cache_creation") or 0) + (d.get("ephemeral_5m_input_tokens") or 0)
           + (d.get("ephemeral_1h_input_tokens") or 0),
           "output": u.get("output_tokens", 0)}
    run = RUN_USAGE.get()
    with _USAGE_LOCK:
        for k, v in one.items():
            USAGE[k] += v
            if run is not None:
                run[k] += v


def _tag_system(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Put an ephemeral cache breakpoint on the last block of the system prompt. Tools come before the system prompt
    in Anthropic's prefix order, so this one breakpoint caches the tool definitions and all fixed instructions
    (orchestrator rules, memory lessons). Applied only to the copy sent to the API, never to the replay-cache key."""
    out = list(messages)
    for i, m in enumerate(out):
        if m.type != "system":
            continue
        blocks = [{"type": "text", "text": m.content}] if isinstance(m.content, str) else list(m.content)
        if blocks and isinstance(blocks[-1], dict) and "cache_control" not in blocks[-1]:
            blocks[-1] = {**blocks[-1], "cache_control": CACHE_CONTROL}
            out[i] = m.model_copy(update={"content": blocks})
        break
    return out


class CacheMiss(RuntimeError):
    pass


class MissingApiKey(RuntimeError):
    pass


REQUEST_TIMEOUT_S = 60      # one model call; without this a stalled connection can hang a run for the SDK default (10 min)
MAX_RETRIES = 2


def require_api_key(mode: str) -> None:
    """Fail fast and plainly. A live or record mode with no key would otherwise hang or die later with an opaque error."""
    if mode in ("record", "auto") and not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        raise MissingApiKey(
            f"RECLAIM_LLM_MODE={mode} needs an Anthropic API key, but ANTHROPIC_API_KEY is empty or not set. "
            "Add it to .env, or run in offline replay mode (RECLAIM_LLM_MODE=replay) which needs no key.")


def resolved_mode(mode: str | None = None) -> str:
    return mode or os.getenv("RECLAIM_LLM_MODE") or ("auto" if (os.getenv("ANTHROPIC_API_KEY") or "").strip() else "replay")


# Tools that must finish before any other tool runs in the same turn, because the others read what they produce
# (triage_cases needs the payout that load_payout ingests). A model may still ask for both at once; tools of one turn run
# on parallel threads, so the result would depend on thread timing and replays would be flaky. We keep the solo tool
# and drop the rest; the model simply asks for them again next turn. Applied identically when recording and replaying.
SOLO_TOOLS = {"load_payout"}


def enforce_tool_order(msg: BaseMessage) -> BaseMessage:
    calls = getattr(msg, "tool_calls", None) or []
    if len(calls) < 2:
        return msg
    solo = next((c for c in calls if c["name"] in SOLO_TOOLS), None)
    if solo is None:
        return msg
    content = msg.content
    if isinstance(content, list):
        content = [b for b in content if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") != solo["id"])]
    return msg.model_copy(update={"tool_calls": [solo], "content": content})


def _canon(messages: list[BaseMessage]) -> list[dict]:
    out = []
    for m in messages:
        d = message_to_dict(m)["data"]
        d.pop("id", None)
        d.pop("artifact", None)  # task results carry a per-run random checkpoint uuid; it never reaches the model
        d.pop("response_metadata", None)
        d.pop("usage_metadata", None)
        out.append({"type": m.type, **d})
    return out


class CachedChatModel(BaseChatModel):
    inner: Any = None
    cache_dir: Path
    mode: Literal["replay", "record", "auto"] = "replay"
    model_name: str = DEFAULT_MODEL
    sig: str = ""

    @property
    def _llm_type(self) -> str:
        return "reclaim-cached"

    def bind_tools(self, tools, **kwargs):
        specs = json.dumps([convert_to_openai_tool(t) for t in tools], sort_keys=True, default=str)
        sig = hashlib.sha256((specs + json.dumps(kwargs, sort_keys=True, default=str)).encode()).hexdigest()
        bound = self.inner.bind_tools(tools, **kwargs) if self.inner is not None else None
        return self.model_copy(update={"inner": bound, "sig": sig})

    def _key(self, messages, stop) -> str:
        blob = json.dumps({"m": self.model_name, "sig": self.sig, "stop": stop, "msgs": _canon(messages)},
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        path = Path(self.cache_dir) / f"{self._key(messages, stop)}.json"
        if self.mode != "record" and path.exists():
            msg = enforce_tool_order(messages_from_dict([json.loads(path.read_text())])[0])
            return ChatResult(generations=[ChatGeneration(message=msg)])
        if self.mode == "replay" or self.inner is None:
            dump = Path(self.cache_dir).parent / "cache_misses"
            dump.mkdir(parents=True, exist_ok=True)  # the exact request that missed, for diffing against a recording
            (dump / f"{path.stem[:12]}.json").write_text(json.dumps(_canon(messages), indent=1, default=str))
            raise CacheMiss(f"no cached LLM response for request {path.stem[:12]} (mode={self.mode}); "
                            "re-record with scripts/record_cache.py")
        # Two breakpoints: the system prompt (fixed per agent) and a top-level one that Anthropic moves to the end of
        # the conversation each call, so the growing history is read from cache instead of re-billed in full.
        out = self.inner.invoke(_tag_system(messages), stop=stop, cache_control=CACHE_CONTROL)
        record_usage(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(message_to_dict(out), default=str))      # the raw model output is what is stored
        return ChatResult(generations=[ChatGeneration(message=enforce_tool_order(out))])


def make_model(cache_dir: Path, mode: str | None = None, model_name: str | None = None):
    name = model_name or os.getenv("RECLAIM_MODEL", DEFAULT_MODEL)
    mode = resolved_mode(mode)
    if mode == "scripted":  # dev/test only: never a substitute for recorded model output
        from .devtools.policy_model import PolicyChatModel
        return PolicyChatModel()
    inner = None
    if mode != "replay":
        require_api_key(mode)
        from langchain_anthropic import ChatAnthropic
        inner = ChatAnthropic(model=name, max_tokens=int(os.getenv("RECLAIM_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
                              timeout=REQUEST_TIMEOUT_S, max_retries=MAX_RETRIES)
    return CachedChatModel(inner=inner, cache_dir=Path(cache_dir), mode=mode, model_name=name)
