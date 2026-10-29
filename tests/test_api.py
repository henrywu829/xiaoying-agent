import json

import pytest
from fastapi.testclient import TestClient

import kbqa.api as api_mod
from kbqa.config import Settings, REPO_ROOT


@pytest.fixture
def client():
    return TestClient(api_mod.app)


def test_health_no_key_leak(client, monkeypatch):
    fake = Settings(llm_base_url="https://x", llm_api_key="SECRET-KEY-123", llm_model="m",
                    llm_timeout=1, agent_max_steps=10, trace_dir=REPO_ROOT / "runs")
    monkeypatch.setattr(api_mod, "_settings", fake)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["is_mock"] is False  # 有 key 时会用真实 provider
    assert "kb_variants" in body
    assert "SECRET-KEY-123" not in r.text


def test_health_mock_mode(client, monkeypatch):
    fake = Settings(llm_base_url="https://x", llm_api_key="", llm_model="m",
                    llm_timeout=1, agent_max_steps=10, trace_dir=REPO_ROOT / "runs")
    monkeypatch.setattr(api_mod, "_settings", fake)
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["is_mock"] is True


def test_ask_mock_c01(client):
    r = client.post("/api/ask", json={"question": "工卡丢了怎么补办？", "mock": True})
    assert r.status_code == 200
    res = r.json()
    assert res["status"] in {"answered", "conflict", "need_clarification",
                             "no_evidence", "tool_error", "incomplete", "failed"}
    assert res["status"] == "answered"
    assert res["clarify_options"] == []
    assert res["trace"]


def test_ask_stream_ndjson(client):
    r = client.post("/api/ask/stream",
                    json={"question": "工卡丢了怎么补办？", "mock": True})
    assert r.status_code == 200
    lines = [json.loads(l) for l in r.text.strip().split("\n") if l.strip()]
    assert lines[0]["type"] == "run_started"
    assert lines[-1]["type"] == "final"
    assert sum(1 for l in lines if l["type"] == "final") == 1


def test_ask_validation_422(client):
    assert client.post("/api/ask", json={"question": "x", "kb": "nope", "mock": True}).status_code == 422
    assert client.post("/api/ask", json={"question": "x", "max_steps": 0, "mock": True}).status_code == 422
    assert client.post("/api/ask", json={"question": "", "mock": True}).status_code == 422


def test_kb_docs(client):
    r = client.get("/api/kb/default/docs/D01")
    assert r.status_code == 200 and len(r.json()["paragraphs"]) == 3
    assert client.get("/api/kb/default/docs/D99").status_code == 404


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()


def test_cases(client):
    r = client.get("/api/cases")
    assert r.status_code == 200 and len(r.json()) >= 14
