import json

import pytest

from kbqa.kb import load_kb
from kbqa.tools import EvidenceLedger, FaultInjector, ToolBox


@pytest.fixture
def box(kb_default):
    return ToolBox(kb_default, EvidenceLedger(), FaultInjector({}), "测试问题", [])


def test_read_doc_registers_ledger(box):
    obs = box.execute("read_doc", json.dumps({"doc_id": "D01", "reason": "读报销办法"}), 9)
    assert obs["ok"] is True
    assert len(obs["paragraphs"]) == 3
    assert box.ledger.para_ids() == ["D01#p1", "D01#p2", "D01#p3"]


def test_read_doc_not_found(box):
    obs = box.execute("read_doc", json.dumps({"doc_id": "D99", "reason": "x"}), 9)
    assert obs["ok"] is False and obs["error"]["type"] == "not_found"
    assert box.ledger.para_ids() == []


def test_search_preview_and_matched_terms(box):
    obs = box.execute("search_docs", json.dumps({"query": "报销期限是多久？", "reason": "x"}), 8)
    assert obs["ok"] is True and obs["hits"]
    assert obs["query_terms"]
    for h in obs["hits"]:
        assert len(h["preview"]) <= 40
        assert h["matched_terms"]
    assert box.ledger.para_ids() == []  # 预览不可引用


def test_search_no_match(box):
    obs = box.execute("search_docs", json.dumps({"query": "公司明年的股价目标是多少", "reason": "x"}), 8)
    assert obs["ok"] is True and obs["hits"] == []
    assert obs["note"].startswith("no_match") and obs["query_terms"]


def test_fail_once(kb_default):
    box = ToolBox(kb_default, EvidenceLedger(), FaultInjector({"search_docs": "fail_once"}), "q", [])
    a = box.execute("search_docs", json.dumps({"query": "工卡", "reason": "x"}), 9)
    assert a["ok"] is False and a["error"]["retryable"] is True
    b = box.execute("search_docs", json.dumps({"query": "工卡", "reason": "x"}), 8)
    assert b["ok"] is True


def test_fail_always(kb_default):
    box = ToolBox(kb_default, EvidenceLedger(), FaultInjector({"read_doc": "fail_always"}), "q", [])
    for _ in range(3):
        assert box.execute("read_doc", json.dumps({"doc_id": "D01", "reason": "x"}), 9)["ok"] is False


def test_bad_arguments(box):
    obs = box.execute("search_docs", "{not json", 9)
    assert obs["ok"] is False and obs["error"]["type"] == "bad_arguments"


def test_unknown_tool(box):
    obs = box.execute("delete_all", "{}", 9)
    assert obs["ok"] is False and obs["error"]["type"] == "unknown_tool"


def test_remaining_steps_passthrough(box):
    obs = box.execute("search_docs", json.dumps({"query": "工卡", "reason": "x"}), 3)
    assert obs["remaining_steps"] == 3
