"""Prompt-caching wiring: the request sent to Anthropic carries cache_control, and the replay-cache key does not change."""
from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from reclaim import llm


class FakeInner:
    def __init__(self):
        self.calls = []

    def invoke(self, messages, stop=None, **kw):
        self.calls.append((messages, kw))
        return AIMessage(content="ok", usage_metadata={"input_tokens": 3000, "output_tokens": 5, "total_tokens": 3005,
                                                       "input_token_details": {"cache_read": 2500, "cache_creation": 0}})


def _model(tmp_path, inner):
    return llm.CachedChatModel(inner=inner, cache_dir=tmp_path, mode="record")


def test_request_has_top_level_and_system_cache_control(tmp_path):
    inner = FakeInner()
    _model(tmp_path, inner).invoke([SystemMessage("rules"), HumanMessage("go")])
    sent, kw = inner.calls[0]
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert sent[0].content[-1]["cache_control"] == {"type": "ephemeral"}


def test_cache_control_does_not_change_the_replay_key(tmp_path):
    m = _model(tmp_path, FakeInner())
    msgs = [SystemMessage("rules"), HumanMessage("go")]
    before = m._key(msgs, None)
    m.invoke(msgs)
    assert m._key(msgs, None) == before            # key computed from the untagged messages
    assert Path(tmp_path, f"{before}.json").exists()


def test_usage_is_recorded_from_the_api_response(tmp_path):
    start = dict(llm.USAGE)
    _model(tmp_path, FakeInner()).invoke([SystemMessage("rules"), HumanMessage("go")])
    assert llm.USAGE["cache_read"] - start["cache_read"] == 2500
    assert llm.USAGE["calls"] - start["calls"] == 1


def test_max_tokens_is_capped(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert llm.make_model(tmp_path, mode="record").inner.max_tokens == llm.DEFAULT_MAX_TOKENS < 2048
