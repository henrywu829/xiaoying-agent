import json

import pytest

from kbqa.guard import extract_numbers, verify_submission
from kbqa.tools import EvidenceLedger, FaultInjector, ToolBox

Q = "工卡丢了怎么补办？"


def _ledger_with(kb, *doc_ids):
    ledger = EvidenceLedger()
    for did in doc_ids:
        doc = kb.get_doc(did)
        for p in doc.paragraphs:
            ledger.add(doc, p)
    return ledger


def _sub(**kw):
    base = {"status": "answered", "answer": "", "citations": [], "conflicts": [],
            "gaps": [], "clarifying_question": "", "clarify_options": []}
    base.update(kw)
    return base


def test_valid_answered(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="工本费 20 元，3 个工作日制卡。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元，行政部在 3 个工作日内完成制卡"}])
    ok, errs, norm = verify_submission(sub, ledger, Q, [])
    assert ok, errs
    assert norm["citations"][0]["title"] == "工卡（门禁卡）管理规定"


def test_quote_tampered(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="工本费 20 元。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 50 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert not ok and any("D06#p2" in e for e in errs)


def test_cite_unread_para(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="报销期限 30 天。", citations=[{"para_id": "D01#p2", "quote": "30 天内提交报销申请"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert not ok and any("read_doc" in e for e in errs)


def test_answered_without_citation(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    ok, errs, _ = verify_submission(_sub(answer="不知道"), ledger, Q, [])
    assert not ok


def test_conflict_needs_two_docs(kb_default):
    ledger = _ledger_with(kb_default, "D01")
    sub = _sub(status="conflict", answer="只有一份文档",
               citations=[{"para_id": "D01#p2", "quote": "报销期限：员工应在费用发生之日起 30 天内"}],
               conflicts=[{"topic": "报销期限", "positions": [{"para_id": "D01#p2", "claim": "30 天"}],
                           "resolution": "unresolved", "basis": "x"}],
               clarifying_question="确认？", clarify_options=["A", "B"])
    ok, errs, _ = verify_submission(sub, ledger, "报销期限是多久？", [])
    assert not ok and any("2 个不同文档" in e for e in errs)


def test_no_evidence_with_citations_rejected(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(status="no_evidence", gaps=["没有资料"],
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert not ok


def test_incomplete_status_rejected(kb_default):
    ok, _, _ = verify_submission(_sub(status="incomplete"), EvidenceLedger(), Q, [])
    assert not ok


def test_quote_extra_whitespace(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="工本费 20 元。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡 收取工本费  20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert ok, errs


def test_quote_too_short(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="工本费 20 元。", citations=[{"para_id": "D06#p2", "quote": "20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert not ok


def test_number_without_source_rejected(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="补办工卡收取工本费 27 元。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert not ok and any("27" in e for e in errs)


def test_number_from_question_ok(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="您提到的 2024 年里，工本费是 20 元。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, "2024 年工卡丢了怎么补办？", [])
    assert ok, errs


def test_number_from_version_date_ok(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="依据 2024 年 2 月 1 日版规定，工本费 20 元。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert ok, errs


def test_docref_not_counted_as_number(kb_default):
    ledger = _ledger_with(kb_default, "D06")
    sub = _sub(answer="工本费 20 元，见 D06#p2。",
               citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}])
    ok, errs, _ = verify_submission(sub, ledger, Q, [])
    assert ok, errs


def test_claim_number_must_match_para(kb_default):
    ledger = _ledger_with(kb_default, "D01", "D02")
    # D02#p1 的 claim 故意写 30 天（原文是 15 天）→ 拒绝
    sub = _sub(status="conflict", answer="30 天与 15 天冲突",
               citations=[{"para_id": "D01#p2", "quote": "费用发生之日起 30 天内提交报销申请"},
                          {"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
               conflicts=[{"topic": "报销期限",
                           "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                         {"para_id": "D02#p1", "claim": "30 天"}],
                           "resolution": "unresolved", "basis": "两份均未声明适用范围"}],
               clarifying_question="确认适用哪份？", clarify_options=["适用 D01", "适用 D02"])
    ok, errs, _ = verify_submission(sub, ledger, "报销期限是多久？", [])
    assert not ok and any("D02#p1" in e for e in errs)


def test_number_rule_skips_no_evidence(kb_default):
    sub = _sub(status="no_evidence", answer="知识库里没有 2030 年的计划", gaps=["缺少股价资料"])
    ok, errs, _ = verify_submission(sub, EvidenceLedger(), Q, [])
    assert ok, errs


def test_resolved_by_doc_requires_basis(kb_default):
    ledger = _ledger_with(kb_default, "D04", "D05")
    base = _sub(answer="每周 2 天。",
                citations=[{"para_id": "D05#p2", "quote": "员工每周最多可申请 2 天远程办公"}],
                conflicts=[{"topic": "远程办公天数",
                            "positions": [{"para_id": "D04#p1", "claim": "1 天"},
                                          {"para_id": "D05#p2", "claim": "2 天"}],
                            "resolution": "resolved_by_doc", "basis": "新版废止旧版"}])
    ok, errs, _ = verify_submission(base, ledger, "每周可以远程办公几天？", [])
    assert not ok and any("basis" in e for e in errs)
    bad = _sub(**{**base, "conflicts": [{**base["conflicts"][0],
                "basis_para_id": "D05#p1", "basis_quote": "编造的依据"}]})
    ok, errs, _ = verify_submission(bad, ledger, "每周可以远程办公几天？", [])
    assert not ok
    good = _sub(**{**base, "conflicts": [{**base["conflicts"][0],
                "basis_para_id": "D05#p1",
                "basis_quote": "原《远程办公管理办法（2023版）》同时废止"}]})
    ok, errs, _ = verify_submission(good, ledger, "每周可以远程办公几天？", [])
    assert ok, errs


def test_resolved_by_user_requires_history(kb_default):
    ledger = _ledger_with(kb_default, "D01", "D02")
    sub = _sub(answer="报销期限 15 天。",
               citations=[{"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
               conflicts=[{"topic": "报销期限",
                           "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                         {"para_id": "D02#p1", "claim": "15 天"}],
                           "resolution": "resolved_by_user", "basis": "用户确认适用通知"}])
    ok, errs, _ = verify_submission(sub, ledger, "我适用《通知》", [])
    assert not ok and any("历史" in e or "对话历史" in e for e in errs)
    ok, errs, _ = verify_submission(
        sub, ledger, "我适用《通知》",
        [{"role": "user", "content": "报销期限是多久？"},
         {"role": "assistant", "content": "有冲突请确认"}])
    assert ok, errs


def test_answered_with_unresolved_rejected(kb_default):
    ledger = _ledger_with(kb_default, "D01", "D02")
    sub = _sub(answer="30 天或 15 天。",
               citations=[{"para_id": "D01#p2", "quote": "费用发生之日起 30 天内提交报销申请"},
                          {"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
               conflicts=[{"topic": "报销期限",
                           "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                         {"para_id": "D02#p1", "claim": "15 天"}],
                           "resolution": "unresolved", "basis": "—"}])
    ok, errs, _ = verify_submission(sub, ledger, "报销期限是多久？", [])
    assert not ok and any("conflict" in e for e in errs)


def _conflict_sub(**kw):
    base = _sub(status="conflict", answer="30 天与 15 天冲突",
                citations=[{"para_id": "D01#p2", "quote": "费用发生之日起 30 天内提交报销申请"},
                           {"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
                conflicts=[{"topic": "报销期限",
                            "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                          {"para_id": "D02#p1", "claim": "15 天"}],
                            "resolution": "unresolved", "basis": "两份均未声明"}],
                clarifying_question="确认适用哪份制度？")
    base.update(kw)
    return base


def test_clarify_options_validation(kb_default):
    ledger = _ledger_with(kb_default, "D01", "D02")
    for opts in ([], ["只一个"], ["a", "b", "c", "d", "e"], ["重复", "重复"], ["x" * 31, "ok"]):
        ok, errs, _ = verify_submission(_conflict_sub(clarify_options=opts), ledger, "报销期限是多久？", [])
        assert not ok, opts
    ok, errs, _ = verify_submission(
        _conflict_sub(clarify_options=["我适用《费用报销管理办法》", "我适用《关于加强报销时效管理的通知》"]),
        ledger, "报销期限是多久？", [])
    assert ok, errs


def test_extract_numbers():
    assert extract_numbers("D01#p2 规定 030 天，约 1.5 周") == {"30", "1.5"}
