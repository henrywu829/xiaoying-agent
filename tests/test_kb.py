import os
import time

import pytest

import kbqa.kb as kb_mod
from kbqa.kb import load_kb, parse_doc, reset_cache
from kbqa.config import REPO_ROOT


def test_parse_d01():
    doc = parse_doc(REPO_ROOT / "data/kb/docs/D01.md")
    assert doc.doc_id == "D01"
    assert doc.title == "费用报销管理办法"
    assert doc.version_date == "2023-01-01"
    assert doc.scope == "全体员工"
    assert [p.para_id for p in doc.paragraphs] == ["D01#p1", "D01#p2", "D01#p3"]


def test_no_conflict_variant(kb_no_conflict):
    assert "D02" not in kb_no_conflict.docs
    assert "D01" in kb_no_conflict.docs


def test_scoped_d02_variant():
    kb = load_kb("scoped_d02")
    d02 = kb.docs["D02"]
    assert d02.scope == "差旅费用"
    assert "差旅" in d02.paragraphs[0].text


def test_no_supersede_variant(kb_no_supersede):
    d05 = kb_no_supersede.docs["D05"]
    assert d05.supersedes == ""
    assert len(d05.paragraphs) == 1
    assert "废止" not in d05.paragraphs[0].text


def test_with_text(kb_default):
    kb2 = kb_default.with_text("D06#p2", "补办工卡收取工本费 27 元。")
    assert kb2.get_para("D06#p2").text == "补办工卡收取工本费 27 元。"
    assert kb_default.get_para("D06#p2").text != "补办工卡收取工本费 27 元。"
    hits = kb2.index.search("工本费 27 元", top_k=3)
    assert any(h.para_id == "D06#p2" for h in hits)
    with pytest.raises(KeyError):
        kb_default.with_text("D99#p1", "x")


def test_unknown_variant_keyerror():
    with pytest.raises(KeyError):
        load_kb("../etc")
    with pytest.raises(KeyError):
        load_kb("nonexistent")


def test_hot_reload(tmp_path, monkeypatch):
    kb_root = tmp_path / "kb"
    (kb_root / "docs").mkdir(parents=True)
    (kb_root / "extra").mkdir()
    (kb_root / "variants.json").write_text(
        '{"default": {"description": "t", "exclude": [], "extra": []}}', encoding="utf-8")
    doc = kb_root / "docs" / "D01.md"
    doc.write_text("---\ndoc_id: D01\ntitle: 测试\nversion_date: 2024-01-01\nscope: 全部\n"
                   "supersedes:\ncategory: 制度\n---\n旧文本。\n", encoding="utf-8")
    monkeypatch.setattr(kb_mod, "KB_ROOT", kb_root)
    reset_cache()
    kb1 = load_kb("default", kb_root)
    assert kb1.get_para("D01#p1").text == "旧文本。"
    time.sleep(0.02)
    doc.write_text("---\ndoc_id: D01\ntitle: 测试\nversion_date: 2024-01-01\nscope: 全部\n"
                   "supersedes:\ncategory: 制度\n---\n新文本。\n", encoding="utf-8")
    os.utime(doc, None)
    kb2 = load_kb("default", kb_root)
    assert kb2.get_para("D01#p1").text == "新文本。"
    reset_cache()
