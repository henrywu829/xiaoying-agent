import json

import pytest

from kbqa.agent import run_agent
from kbqa.llm import LLMError, LLMReply, ToolCall
from conftest import ScriptedProvider, last_tool_obs, make_reply, make_req, multi_reply, text_reply


def collect(provider, req):
    from kbqa.kb import load_kb
    return list(run_agent(req, provider, load_kb(req.kb)))


def test_normal_path(kb_default):
    calls = iter([
        make_reply("search_docs", query="工卡 补办", top_k=4, reason="检索工卡相关"),
        make_reply("read_doc", doc_id="D06", reason="读取工卡规定"),
        make_reply("submit_answer", status="answered",
                   answer="工本费 20 元，3 个工作日制卡，OA 系统申请。",
                   citations=[{"para_id": "D06#p1", "quote": "OA 系统「行政服务-工卡补办」提交申请"},
                              {"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元，行政部在 3 个工作日内完成制卡"}],
                   conflicts=[], gaps=[], clarifying_question="", clarify_options=[],
                   reason="已获得原文"),
    ])
    req = make_req("工卡丢了怎么补办？")
    events = collect(ScriptedProvider(lambda m: next(calls)), req)
    final = events[-1]
    assert final["type"] == "final" and final["result"]["status"] == "answered"
    assert final["result"]["citations"][0]["title"] == "工卡（门禁卡）管理规定"
    steps = [e for e in events if e["type"] == "step"]
    assert len(steps) == 3 and all(s["reason"] for s in steps)


def test_observation_drives_branch(kb_default):
    """脚本读取上一条 search 观察：无命中就改写再搜，否则 read。"""
    def script(messages):
        obs = last_tool_obs(messages)
        if "hits" in obs and not obs["hits"]:
            return make_reply("search_docs", query="门禁卡 补办", reason="无命中改写", top_k=4)
        if "hits" in obs:
            return make_reply("read_doc", doc_id=obs["hits"][0]["doc_id"], reason="读命中")
        if "paragraphs" in obs:
            p = obs["paragraphs"][0]
            return make_reply("submit_answer", status="answered", answer=p["text"],
                              citations=[{"para_id": p["para_id"], "quote": p["text"]}],
                              conflicts=[], gaps=[], clarifying_question="", clarify_options=[],
                              reason="作答")
        return make_reply("search_docs", query=_next_q.pop(0), reason="先检索", top_k=4)

    # 路径 A：第一次检索无命中（资料外查询）
    _next_q = ["公司明年的股价目标是多少", "门禁卡 补办"]
    req = make_req("公司明年的股价目标是多少？")
    events_a = collect(ScriptedProvider(script), req)
    acts_a = [e["action"] for e in events_a if e["type"] == "step"]

    # 路径 B：第一次就命中
    _next_q = ["工卡丢了怎么补办", "x"]
    req2 = make_req("工卡丢了怎么补办？")
    events_b = collect(ScriptedProvider(script), req2)
    acts_b = [e["action"] for e in events_b if e["type"] == "step"]

    assert acts_a[:2] == ["search_docs", "search_docs"]
    assert acts_b[:2] == ["search_docs", "read_doc"]


def test_rejected_submit_then_fix(kb_default):
    """第一次提交带无出处数字 → 被拒；脚本读到 errors 后修正。"""
    def script(messages):
        obs = last_tool_obs(messages)
        if obs.get("accepted") is False:
            return make_reply("submit_answer", status="answered",
                              answer="工本费 20 元。",
                              citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}],
                              conflicts=[], gaps=[], clarifying_question="", clarify_options=[],
                              reason="修正数字")
        if "paragraphs" in obs:
            return make_reply("submit_answer", status="answered",
                              answer="工本费 27 元。",
                              citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}],
                              conflicts=[], gaps=[], clarifying_question="", clarify_options=[],
                              reason="作答")
        return make_reply("read_doc", doc_id="D06", reason="读原文")

    req = make_req("工卡丢了怎么补办？")
    events = collect(ScriptedProvider(script), req)
    steps = [e for e in events if e["type"] == "step"]
    assert steps[0]["ok"] is False and "数字" in steps[0]["observation_summary"] or \
           steps[1]["ok"] is False and "数字" in steps[1]["observation_summary"]
    assert events[-1]["result"]["status"] == "answered"


def test_resolved_by_user_followup(kb_default):
    def script(messages):
        obs = last_tool_obs(messages)
        if "paragraphs" in obs:
            return make_reply("submit_answer", status="answered",
                              answer="报销期限为费用发生后 15 天内。",
                              citations=[{"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
                              conflicts=[{"topic": "报销期限",
                                          "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                                        {"para_id": "D02#p1", "claim": "15 天"}],
                                          "resolution": "resolved_by_user",
                                          "basis": "用户确认适用《关于加强报销时效管理的通知》"}],
                              gaps=[], clarifying_question="", clarify_options=[], reason="按确认作答")
        return make_reply("read_doc", doc_id="D02", reason="读用户确认的制度")

    req = make_req("我适用《关于加强报销时效管理的通知》",
                   history=[{"role": "user", "content": "报销期限是多久？"},
                            {"role": "assistant", "content": "两份制度不一致，请确认适用哪份？"}])
    # resolved_by_user 的 positions 也需已读：脚本只读了 D02，D01 未读会失败——补读
    def script2(messages):
        obs = last_tool_obs(messages)
        if obs.get("accepted") is False:
            # 被"未读 D01"拒绝后补读
            return make_reply("read_doc", doc_id="D01", reason="补读 D01")
        if "paragraphs" in obs and any(m.get("role") == "tool" and "D01#p2" in str(m.get("content", "")) for m in messages[-3:]):
            return make_reply("submit_answer", status="answered",
                              answer="报销期限为费用发生后 15 天内。",
                              citations=[{"para_id": "D02#p1", "quote": "费用发生后 15 天内完成报销提交"}],
                              conflicts=[{"topic": "报销期限",
                                          "positions": [{"para_id": "D01#p2", "claim": "30 天"},
                                                        {"para_id": "D02#p1", "claim": "15 天"}],
                                          "resolution": "resolved_by_user",
                                          "basis": "用户确认适用《关于加强报销时效管理的通知》"}],
                              gaps=[], clarifying_question="", clarify_options=[], reason="按确认作答")
        if "paragraphs" in obs:
            return make_reply("read_doc", doc_id="D01", reason="补读另一份")
        return make_reply("read_doc", doc_id="D02", reason="读确认的制度")

    events = collect(ScriptedProvider(script2), req)
    res = events[-1]["result"]
    assert res["status"] == "answered"
    assert res["conflicts"][0]["resolution"] == "resolved_by_user"


def test_tool_fail_not_auto_retried(kb_default):
    req = make_req("工卡丢了怎么补办？", faults={"search_docs": "fail_once"})
    calls = {"search": 0}

    def script(messages):
        obs = last_tool_obs(messages)
        if obs.get("ok") is False:
            return make_reply("submit_answer", status="tool_error", answer="检索失败",
                              gaps=["search_docs 超时"], citations=[], conflicts=[],
                              clarifying_question="", clarify_options=[], reason="如实报告")
        calls["search"] += 1
        return make_reply("search_docs", query="工卡", reason="检索")

    events = collect(ScriptedProvider(script), req)
    res = events[-1]["result"]
    assert res["status"] == "tool_error"
    assert calls["search"] == 1  # 代码没有自动重试


def test_step_limit(kb_default):
    req = make_req("报销期限是多久？", max_steps=3)
    provider = ScriptedProvider(lambda m: make_reply("search_docs", query="报销期限", reason="x"))
    events = collect(provider, req)
    res = events[-1]["result"]
    assert res["status"] == "incomplete" and res["steps_used"] == 3
    assert any("最大步数" in g for g in res["gaps"])


def test_no_tool_call_nudge(kb_default):
    calls = iter([
        text_reply("让我想想……"),
        make_reply("search_docs", query="工卡", reason="检索"),
        make_reply("read_doc", doc_id="D06", reason="读"),
        make_reply("submit_answer", status="answered", answer="工本费 20 元。",
                   citations=[{"para_id": "D06#p2", "quote": "补办工卡收取工本费 20 元"}],
                   conflicts=[], gaps=[], clarifying_question="", clarify_options=[], reason="作答"),
    ])
    req = make_req("工卡丢了怎么补办？")
    events = collect(ScriptedProvider(lambda m: next(calls)), req)
    acts = [e["action"] for e in events if e["type"] == "step"]
    assert "(no_tool_call)" in acts
    assert events[-1]["result"]["status"] == "answered"


def test_multiple_tool_calls_same_turn(kb_default):
    reply = multi_reply(("read_doc", {"doc_id": "D04", "reason": "读旧版"}),
                        ("read_doc", {"doc_id": "D05", "reason": "读新版"}))
    provider = ScriptedProvider(lambda m: reply if not any(
        x.get("role") == "tool" for x in m) else make_reply(
        "submit_answer", status="answered", answer="每周 2 天。",
        citations=[{"para_id": "D05#p2", "quote": "员工每周最多可申请 2 天远程办公"}],
        conflicts=[], gaps=[], clarifying_question="", clarify_options=[], reason="作答"))
    req = make_req("每周可以远程办公几天？")
    events = collect(provider, req)
    reads = [e for e in events if e.get("action") == "read_doc"]
    assert len(reads) == 2 and reads[0]["step"] != reads[1]["step"]


def test_llm_error(kb_default):
    class Boom:
        name = "boom"; model = "x"; is_mock = True
        def chat(self, m, t): raise LLMError("连接超时")

    req = make_req("工卡丢了怎么补办？")
    events = collect(Boom(), req)
    assert events[-1]["type"] == "final" and events[-1]["result"]["status"] == "failed"
