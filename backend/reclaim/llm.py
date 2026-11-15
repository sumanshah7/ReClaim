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
from pathlib import Path
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

DEFAULT_MODEL = "claude-sonnet-5-5"


class CacheMiss(RuntimeError):
    pass


def _canon(messages: list[BaseMessage]) -> list[dict]:
    out = []
    for m in messages:
        d = message_to_dict(m)["data"]
        d.pop("id", None)
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
            msg = messages_from_dict([json.loads(path.read_text())])[0]
            return ChatResult(generations=[ChatGeneration(message=msg)])
        if self.mode == "replay" or self.inner is None:
            raise CacheMiss(f"no cached LLM response for request {path.stem[:12]} (mode={self.mode}); "
                            "re-record with scripts/record_cache.py")
        out = self.inner.invoke(messages, stop=stop)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(message_to_dict(out), default=str))
        return ChatResult(generations=[ChatGeneration(message=out)])


def make_model(cache_dir: Path, mode: str | None = None, model_name: str | None = None):
    name = model_name or os.getenv("RECLAIM_MODEL", DEFAULT_MODEL)
    mode = mode or os.getenv("RECLAIM_LLM_MODE") or ("auto" if os.getenv("ANTHROPIC_API_KEY") else "replay")
    if mode == "scripted":  # dev/test only: never a substitute for recorded model output
        from .devtools.policy_model import PolicyChatModel
        return PolicyChatModel()
    inner = None
    if mode != "replay":
        from langchain_anthropic import ChatAnthropic
        inner = ChatAnthropic(model=name, max_tokens=2048)
    return CachedChatModel(inner=inner, cache_dir=Path(cache_dir), mode=mode, model_name=name)
