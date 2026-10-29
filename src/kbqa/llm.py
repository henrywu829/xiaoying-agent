"""模型接入：OpenAI 兼容协议（httpx 直调）+ 离线 MockProvider。"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 原始 JSON 字符串


@dataclass
class LLMReply:
    content: str | None
    tool_calls: list[ToolCall]
    raw_message: dict


class LLMError(Exception):
    pass


class LLMProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply: ...


class OpenAICompatProvider:
    name = "openai_compat"
    is_mock = False

    def __init__(self, settings) -> None:
        self.model = settings.llm_model
        self._url = settings.llm_base_url + "/chat/completions"
        self._key = settings.llm_api_key
        self._timeout = settings.llm_timeout

    def _post(self, body: dict) -> dict:
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        body = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
        }
        try:
            try:
                data = self._post(body)
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                # 传输层重试 1 次：仅对超时和 5xx/429，与业务决策无关
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code not in (429,) and e.response.status_code < 500:
                    raise
                data = self._post(body)
        except httpx.HTTPStatusError as e:
            raise LLMError(f"模型返回 {e.response.status_code}：{e.response.text[:200]}") from e
        except httpx.HTTPError as e:
            raise LLMError(f"模型调用失败：{e}") from e

        msg = data["choices"][0]["message"]
        calls = [
            ToolCall(id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                     name=tc["function"]["name"],
                     arguments=tc["function"].get("arguments") or "{}")
            for tc in (msg.get("tool_calls") or [])
        ]
        raw = {
            "role": "assistant",
            "content": msg.get("content"),
            **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {}),
        }
        return LLMReply(content=msg.get("content"), tool_calls=calls, raw_message=raw)


_QWORD_RE = re.compile(r"[？?]|怎么|如何|什么|多久|多少|呢|咋|了|的|找不着|进公司")


class MockProvider:
    """离线启发式决策：按最近工具观察行动。不识别冲突、不做语义改写、
    不生成 clarify_options，只用于验证流程和离线演示。"""

    name = "mock"
    model = "mock-local"
    is_mock = True

    def __init__(self) -> None:
        self._tool_msgs: list[tuple[str, dict]] = []

    def _call(self, name: str, **args) -> LLMReply:
        tc = {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
              "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}
        raw = {"role": "assistant", "content": None, "tool_calls": [tc]}
        return LLMReply(content=None, tool_calls=[ToolCall(tc["id"], name, tc["function"]["arguments"])],
                        raw_message=raw)

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        self._tool_msgs = []
        question = ""
        for m in messages:
            if m.get("role") == "tool":
                try:
                    self._tool_msgs.append((m.get("name") or _peek_name(messages, m), json.loads(m.get("content") or "{}")))
                except json.JSONDecodeError:
                    pass
            elif m.get("role") == "user":
                question = m.get("content") or question

        recent = self._tool_msgs[-3:]
        fails = sum(1 for _n, o in recent if o.get("ok") is False and o.get("error"))
        submits = [o for _n, o in self._tool_msgs if "accepted" in o]
        searches = [o for n, o in self._tool_msgs if "hits" in o]
        reads = [o for n, o in self._tool_msgs if o.get("ok") and "paragraphs" in o]

        if fails >= 2 and not submits:
            return self._call("submit_answer", status="tool_error", answer="检索工具持续失败，无法完成回答。",
                              gaps=["search_docs 连续失败，未取得任何检索结果"],
                              citations=[], conflicts=[], clarifying_question="", clarify_options=[],
                              reason="工具持续失败如实报告")
        if not searches:
            q = question
            if len(q) < 8:
                for m in reversed(messages):
                    if m.get("role") == "user" and (m.get("content") or "") != question:
                        q = (m["content"] + " " + q).strip()
                        break
            return self._call("search_docs", query=q[:50], top_k=4, reason="先检索相关制度")
        last_search = searches[-1]
        if not last_search.get("hits"):
            if len(searches) < 2:
                q2 = _QWORD_RE.sub(" ", last_search.get("query") or question).strip() or question
                return self._call("search_docs", query=q2[:50], top_k=4, reason="无命中，去疑问词改写重搜")
            return self._call("submit_answer", status="no_evidence",
                              answer="知识库中没有与该问题相关的资料，无法回答。",
                              gaps=["缺少与问题相关的制度或产品文档"],
                              citations=[], conflicts=[], clarifying_question="", clarify_options=[],
                              reason="多次检索无结果")
        hit = last_search["hits"][0]
        if not any(r.get("doc_id") == hit["doc_id"] for r in reads):
            return self._call("read_doc", doc_id=hit["doc_id"], reason="读取命中文档原文")
        doc = next(r for r in reversed(reads) if r.get("doc_id") == hit["doc_id"])
        para = next((p for p in doc["paragraphs"] if p["para_id"] == hit["para_id"]), doc["paragraphs"][0])
        if submits and submits[-1].get("accepted") is False:
            para = doc["paragraphs"][0]
        return self._call("submit_answer", status="answered", answer=para["text"],
                          citations=[{"para_id": para["para_id"], "quote": para["text"]}],
                          conflicts=[], gaps=[], clarifying_question="", clarify_options=[],
                          reason="已获得原文，引用段落全文作答")


def _peek_name(messages: list[dict], tool_msg: dict) -> str:
    """根据 tool_call_id 反查工具名（OpenAI tool 消息不带 name 字段时兜底）。"""
    tid = tool_msg.get("tool_call_id")
    for m in reversed(messages):
        for tc in (m.get("tool_calls") or []):
            if tc.get("id") == tid:
                return tc.get("function", {}).get("name", "")
    return ""


def make_provider(settings, force_mock: bool = False) -> LLMProvider:
    if settings.llm_api_key and not force_mock:
        return OpenAICompatProvider(settings)
    return MockProvider()
