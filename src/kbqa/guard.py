"""提交校验：引用逐字校验、数字溯源、裁决依据、各状态必填约束。纯函数。"""
from __future__ import annotations

import re

STATUS_WHITELIST = {"answered", "conflict", "need_clarification", "no_evidence", "tool_error"}

_DOCREF_RE = re.compile(r"D\d+(?:#p\d+)?", re.IGNORECASE)
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")


def _norm(s: str | None) -> str:
    return _WS_RE.sub("", s or "")


def _norm_num(tok: str) -> str:
    if "." in tok:
        i, f = tok.split(".", 1)
        return (i.lstrip("0") or "0") + "." + f
    return tok.lstrip("0") or "0"


def extract_numbers(text: str | None) -> set[str]:
    """提取阿拉伯数字并去前导零。先去掉 D01#p2 这类编号，免得编号被当成数字。

    run_eval.py --perturb 复用本函数，保证两边对"数字"的口径一致。
    """
    cleaned = _DOCREF_RE.sub(" ", text or "")
    return {_norm_num(t) for t in _NUM_RE.findall(cleaned)}


def _get(m, key):
    return m.get(key) if isinstance(m, dict) else getattr(m, key, None)


def verify_submission(sub: dict, ledger, question: str, history) -> tuple[bool, list[str], dict]:
    errors: list[str] = []
    status = sub.get("status")
    if status not in STATUS_WHITELIST:
        return False, [f"status 非法：{status!r}，可选 {sorted(STATUS_WHITELIST)}"], {}

    citations = sub.get("citations") or []
    conflicts = sub.get("conflicts") or []
    gaps = sub.get("gaps") or []
    clarifying = (sub.get("clarifying_question") or "").strip()
    options = [o for o in (sub.get("clarify_options") or []) if isinstance(o, str)]

    def check_quote(para_id, quote, label) -> tuple | None:
        entry = ledger.get(para_id)
        if entry is None:
            errors.append(f"{label} {para_id} 尚未读取，请先 read_doc")
            return None
        doc, para = entry
        if len(_norm(quote)) < 4:
            errors.append(f"{label} {para_id} 的引用少于 4 字")
            return None
        if _norm(quote) not in _norm(para.text):
            errors.append(f"{label} {para_id} 的 quote 与原文不一致")
            return None
        return doc, para

    valid_cits: list[tuple[dict, tuple]] = []
    for c in citations:
        if not isinstance(c, dict):
            errors.append("citations 元素必须是 {para_id, quote} 对象")
            continue
        r = check_quote(c.get("para_id"), c.get("quote"), "引用")
        if r is not None:
            valid_cits.append((c, r))

    unresolved = 0
    for cf in conflicts:
        if not isinstance(cf, dict):
            errors.append("conflicts 元素必须是对象")
            continue
        for pos in cf.get("positions") or []:
            pid = pos.get("para_id") if isinstance(pos, dict) else None
            entry = ledger.get(pid)
            if entry is None:
                errors.append(f"冲突段落 {pid} 尚未读取，请先 read_doc")
                continue
            _, para = entry
            for n in extract_numbers(pos.get("claim")):
                if n not in extract_numbers(para.text):
                    errors.append(f"冲突主张 {pid} 中的数字 {n} 未出现在该段原文中")
        res = cf.get("resolution")
        if res == "unresolved":
            unresolved += 1
        elif res == "resolved_by_doc":
            bp, bq = cf.get("basis_para_id"), cf.get("basis_quote")
            if not bp or not bq:
                errors.append("resolved_by_doc 必须提供 basis_para_id 和 basis_quote")
            else:
                check_quote(bp, bq, "裁决依据")
        elif res == "resolved_by_user":
            if not history:
                errors.append("resolved_by_user 要求对话历史非空")
            if not (cf.get("basis") or "").strip():
                errors.append("resolved_by_user 必须在 basis 写明用户确认的选择")
        else:
            errors.append(f"未知 resolution：{res!r}")

    # 数字溯源：只核对阿拉伯数字，中文数字（"三十天"）不会被检查；
    # shortcut: 提示词要求数字与原文写法一致，若真实 trace 中出现中文数字再加转换。
    if status in ("answered", "conflict"):
        allowed: set[str] = set()
        for c, (doc, _para) in valid_cits:
            allowed |= extract_numbers(c.get("quote"))
            allowed |= extract_numbers(doc.version_date)
        allowed |= extract_numbers(question)
        for m in history or []:
            if _get(m, "role") == "user":
                allowed |= extract_numbers(_get(m, "content"))
        for n in extract_numbers(sub.get("answer")):
            if n not in allowed:
                errors.append(f"回答中的数字 {n} 未出现在引用、问题或文档版本信息中")

    if status == "answered":
        if not valid_cits:
            errors.append("answered 至少需要 1 条有效引用")
        if unresolved:
            errors.append("存在未消解冲突时应提交 conflict")
    elif status == "conflict":
        doc_ids = {doc.doc_id for _, (doc, _) in valid_cits}
        if len(doc_ids) < 2:
            errors.append("conflict 需要引用至少 2 个不同文档")
        if not unresolved:
            errors.append("conflict 需要至少 1 条 resolution=unresolved 的冲突")
        if not clarifying:
            errors.append("conflict 需要 clarifying_question")
        if not 2 <= len(options) <= 4:
            errors.append("conflict 需要 2–4 个 clarify_options")
    elif status == "need_clarification":
        if not clarifying:
            errors.append("need_clarification 需要 clarifying_question")
        if options and not 2 <= len(options) <= 4:
            errors.append("clarify_options 若提供须为 2–4 个")
    else:  # no_evidence / tool_error
        if not gaps:
            errors.append(f"{status} 需要 gaps 说明")
        if status == "no_evidence" and citations:
            errors.append("no_evidence 不得带引用")

    seen: set[str] = set()
    for o in options:
        s = o.strip()
        if not s or len(s) > 30:
            errors.append("clarify_options 每项须非空且 ≤30 字")
            break
        if s in seen:
            errors.append("clarify_options 不得重复")
            break
        seen.add(s)

    if errors:
        return False, errors, {}

    normalized = dict(sub)
    normalized["citations"] = [
        {
            "doc_id": doc.doc_id,
            "para_id": c.get("para_id"),
            "title": doc.title,
            "version_date": doc.version_date,
            "quote": c.get("quote"),
        }
        for c, (doc, _p) in valid_cits
    ]
    return True, [], normalized
