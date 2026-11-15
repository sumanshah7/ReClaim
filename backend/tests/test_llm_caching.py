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


def test_cache_writes_are_counted_from_ephemeral_keys():
    start = llm.USAGE["cache_creation"]
    llm.record_usage(AIMessage(content="x", usage_metadata={"input_tokens": 100, "output_tokens": 1, "total_tokens": 101,
        "input_token_details": {"cache_read": 0, "cache_creation": 0, "ephemeral_5m_input_tokens": 90}}))
    assert llm.USAGE["cache_creation"] - start == 90


def _parallel(names):
    calls = [{"name": n, "args": {}, "id": f"id_{i}", "type": "tool_call"} for i, n in enumerate(names)]
    content = [{"type": "text", "text": "ok"}] + [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": {}} for c in calls]
    return AIMessage(content=content, tool_calls=calls)


def test_load_payout_runs_alone_in_its_turn():
    msg = llm.enforce_tool_order(_parallel(["load_payout", "triage_cases"]))
    assert [c["name"] for c in msg.tool_calls] == ["load_payout"]
    assert [b["name"] for b in msg.content if b.get("type") == "tool_use"] == ["load_payout"]      # blocks stay in sync


def test_other_parallel_calls_are_left_alone():
    for names in (["check_ticket_vs_claim", "check_pickup_timestamps"], ["write_todos", "task"], ["triage_cases"]):
        msg = _parallel(names)
        assert llm.enforce_tool_order(msg) is msg


def test_a_cached_parallel_load_response_replays_as_a_single_call(tmp_path):
    import json as _json
    from langchain_core.messages import message_to_dict
    m = llm.CachedChatModel(inner=None, cache_dir=tmp_path, mode="replay")
    msgs = [SystemMessage("s"), HumanMessage("go")]
    (tmp_path / f"{m._key(msgs, None)}.json").write_text(_json.dumps(message_to_dict(_parallel(["load_payout", "triage_cases"]))))
    out = m.invoke(msgs)
    assert [c["name"] for c in out.tool_calls] == ["load_payout"]
