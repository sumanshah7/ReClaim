import os

import pytest
from fastapi.testclient import TestClient

from reclaim import tracing
from reclaim.api.main import Settings, create_app

KEYS = ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_PROJECT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_requested_without_key_is_switched_off_with_a_note(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    note = tracing.ensure_consistent()
    assert note and "LANGSMITH_API_KEY is empty" in note
    assert os.environ["LANGSMITH_TRACING"] == "false" and not tracing.status()["enabled"]


def test_requested_with_key_stays_on(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_not_real")
    monkeypatch.setenv("LANGSMITH_PROJECT", "reclaim")
    monkeypatch.setattr(tracing, "project_url", lambda project: "https://smith.example/reclaim")
    assert tracing.ensure_consistent() is None
    assert tracing.status() == {"enabled": True, "project": "reclaim", "note": None, "url": "https://smith.example/reclaim"}


def test_off_by_default_and_a_key_alone_does_not_enable(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_not_real")
    assert tracing.ensure_consistent() is None and not tracing.status()["enabled"]


def test_run_config_labels_replay_honestly_and_holds_no_customer_data():
    c = tracing.run_config("abc123", "replay", "synthetic-sample")
    assert "replayed-from-cache" in c["tags"] and c["metadata"]["replayed_from_cache"] is True
    assert c["metadata"]["thread_id"] == "abc123" and c["metadata"]["data"] == "synthetic-sample"
    assert "live-model" in tracing.run_config("x", "auto", "upload")["tags"]
    assert set(c["metadata"]) == {"app", "thread_id", "llm_mode", "replayed_from_cache", "data"}


def test_health_reports_tracing_and_misconfig_note(fix, tmp_path, today, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")  # requested, no key
    monkeypatch.setattr("reclaim.api.main.load_env", lambda *a, **k: None)  # don't read the real .env in tests
    c = TestClient(create_app(Settings(fixtures=fix, data=tmp_path / "d", cases=tmp_path / "c", today=today)))
    t = c.get("/api/health").json()["tracing"]
    assert t["enabled"] is False and "switched off" in t["note"]
