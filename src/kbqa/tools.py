"""工具契约与执行：search_docs / read_doc / submit_answer、证据账本、故障注入。"""
from __future__ import annotations

import json

from .guard import verify_submission
from .retrieval import tokenize

_REASON = {"type": "string", "description": "本步决策依据，≤30 字", "maxLength": 30}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_docs",
            "description": "检索知识库段落。只返回预览（不能作为引用）与每条结果命中的查询词项 matched_terms；引用前必须 read_doc。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，用制度/产品术语"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 5, "default": 4},
                    "reason": _REASON,
                },
                "required": ["query", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": "读取一篇文档的原文段落与元数据（version_date/scope/supersedes），读到的段落才可被引用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "文档编号，如 D01"},
                    "reason": _REASON,
                },
                "required": ["doc_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "提交最终结果，唯一的结束动作。引用必须逐字摘自已读段落，回答中的每个数字都要有出处。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["answered", "conflict", "need_clarification", "no_evidence", "tool_error"],
                    },
                    "answer": {"type": "string", "description": "回答正文（简体中文，数字与原文一致）"},
                    "citations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"para_id": {"type": "string"}, "quote": {"type": "string"}},
                            "required": ["para_id", "quote"],
                        },
                    },
                    "conflicts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "topic": {"type": "string"},
                                "positions": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {"para_id": {"type": "string"}, "claim": {"type": "string"}},
                                        "required": ["para_id", "claim"],
                                    },
                                },
                                "resolution": {
                                    "type": "string",
                                    "enum": ["unresolved", "resolved_by_doc", "resolved_by_user"],
                                },
                                "basis": {"type": "string", "description": "消解说明；resolved_by_user 时必填"},
                                "basis_para_id": {"type": "string"},
                                "basis_quote": {"type": "string"},
                            },
                            "required": ["topic", "positions", "resolution"],
                        },
                    },
                    "gaps": {"type": "array", "items": {"type": "string"}},
                    "clarifying_question": {"type": "string"},
                    "clarify_options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "2–4 个用户可直接发送的确认语，每个 ≤30 字",
                    },
                    "reason": _REASON,
                },
                "required": ["status", "reason"],
            },
        },
    },
]


class EvidenceLedger:
    """只有 read_doc 成功的段落才进入账本；检索预览不可引用。"""

    def __init__(self) -> None:
        self._paras: dict[str, tuple] = {}  # para_id -> (Document, Paragraph)

    def add(self, doc, para) -> None:
        self._paras[para.para_id] = (doc, para)

    def get(self, para_id: str) -> tuple | None:
        return self._paras.get(para_id)

    def para_ids(self) -> list[str]:
        return list(self._paras)


class FaultInjector:
    """故障注入：fail_once 第一次失败，fail_always 一直失败。优先于正常执行。"""

    _MSG = {"search_docs": "检索服务超时", "read_doc": "文档服务超时"}

    def __init__(self, faults: dict | None) -> None:
        self._faults = dict(faults or {})
        self._fired: set[str] = set()

    def check(self, tool: str) -> dict | None:
        mode = self._faults.get(tool)
        if mode == "fail_always" or (mode == "fail_once" and tool not in self._fired):
            self._fired.add(tool)
            return {"type": "timeout", "message": self._MSG.get(tool, "服务超时"), "retryable": True}
        return None


class ToolBox:
    def __init__(self, kb, ledger: EvidenceLedger, faults: FaultInjector, question: str, history) -> None:
        self.kb = kb
        self.ledger = ledger
        self.faults = faults
        self.question = question
        self.history = history

    def execute(self, name: str, raw_args: str, remaining: int) -> dict:
        if name not in {"search_docs", "read_doc", "submit_answer"}:
            return {"ok": False, "error": {"type": "unknown_tool", "message": f"未知工具 {name}", "retryable": False},
                    "remaining_steps": remaining}
        if err := self.faults.check(name):
            return {"ok": False, "error": err, "remaining_steps": remaining}
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            return {"ok": False, "error": {"type": "bad_arguments", "message": f"参数 JSON 非法：{e}", "retryable": False},
                    "remaining_steps": remaining}
        if name == "search_docs":
            return self._search(args, remaining)
        if name == "read_doc":
            return self._read(args, remaining)
        return self._submit(args, remaining)

    def _search(self, args: dict, remaining: int) -> dict:
        query = str(args.get("query") or "").strip()
        try:
            top_k = int(args.get("top_k") or 4)
        except (TypeError, ValueError):
            top_k = 4
        top_k = max(1, min(5, top_k))
        q_terms = tokenize(query)
        hits = self.kb.index.search(query, top_k) if query else []
        obs = {
            "ok": True,
            "query": query,
            "query_terms": q_terms,
            "hits": [
                {
                    "doc_id": h.doc_id,
                    "para_id": h.para_id,
                    "title": h.title,
                    "version_date": h.version_date,
                    "score": h.score,
                    "matched_terms": h.matched_terms,
                    "preview": h.preview,
                }
                for h in hits
            ],
            "remaining_steps": remaining,
        }
        if not hits:
            obs["note"] = "no_match：没有段落命中足够的查询词项；预览不可引用，请换用制度/产品术语改写或提交 no_evidence"
        return obs

    def _read(self, args: dict, remaining: int) -> dict:
        doc_id = str(args.get("doc_id") or "").strip()
        doc = self.kb.get_doc(doc_id)
        if doc is None:
            return {"ok": False, "error": {"type": "not_found", "message": f"文档 {doc_id} 不存在", "retryable": False},
                    "remaining_steps": remaining}
        for p in doc.paragraphs:
            self.ledger.add(doc, p)
        return {
            "ok": True,
            "doc_id": doc.doc_id,
            "title": doc.title,
            "version_date": doc.version_date,
            "scope": doc.scope,
            "supersedes": doc.supersedes,
            "paragraphs": [{"para_id": p.para_id, "text": p.text} for p in doc.paragraphs],
            "remaining_steps": remaining,
        }

    def _submit(self, args: dict, remaining: int) -> dict:
        sub = {k: args.get(k) for k in (
            "status", "answer", "citations", "conflicts", "gaps",
            "clarifying_question", "clarify_options",
        )}
        accepted, errors, normalized = verify_submission(sub, self.ledger, self.question, self.history)
        if accepted:
            return {"accepted": True, "submission": normalized, "remaining_steps": remaining}
        return {"accepted": False, "errors": errors, "remaining_steps": remaining}
