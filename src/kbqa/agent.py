"""ReAct 循环：模型选动作 → ToolBox 执行 → 观察回写 → 模型调整或提交。

代码只做确定性约束：计步、协议纠偏、结果组装、trace；业务判断全在模型。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Iterator

from .llm import LLMError
from .prompts import NUDGE_MESSAGE, build_messages
from .tools import TOOL_SCHEMAS, EvidenceLedger, FaultInjector, ToolBox
from .trace import summarize_observation

STATUS_LABELS = {
    "answered": "已回答",
    "conflict": "资料冲突，待确认",
    "need_clarification": "需要补充信息",
    "no_evidence": "资料不足或超出范围",
    "tool_error": "工具失败",
    "incomplete": "未完成（达到步数上限）",
    "failed": "系统错误",
}


def _provider_info(provider) -> dict:
    return {"name": provider.name, "model": provider.model, "is_mock": provider.is_mock}


def run_agent(req, provider, kb, trace_dir=None) -> Iterator[dict]:
    """同步生成器：产出 run_started / step* / final 事件（final 恰一个且在最后）。"""
    run_id = uuid.uuid4().hex[:6]
    max_steps = req.max_steps or 10
    toolbox = ToolBox(kb, EvidenceLedger(), FaultInjector(req.faults), req.question,
                      [m.model_dump() for m in req.history])
    messages = build_messages(req.question, req.history)
    t0 = time.monotonic()
    trace_events: list[dict] = []
    steps_trace: list[dict] = []

    def emit(ev: dict) -> dict:
        trace_events.append(ev)
        return ev

    started = {
        "type": "run_started", "run_id": run_id,
        "provider": _provider_info(provider),
        "kb": req.kb, "max_steps": max_steps,
    }
    trace_events.append(started)
    yield started

    def make_final(status: str, submission: dict | None, gaps: list[str], steps: int) -> dict:
        sub = submission or {}
        cits = sub.get("citations") or []
        result = {
            "run_id": run_id,
            "question": req.question,
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "answer": sub.get("answer") or "",
            "citations": cits,
            "conflicts": sub.get("conflicts") or [],
            "gaps": (sub.get("gaps") or []) + (gaps if status not in ("answered", "conflict") else []),
            "clarifying_question": sub.get("clarifying_question") or "",
            "clarify_options": sub.get("clarify_options") or [],
            "evidence_read": toolbox.ledger.para_ids(),
            "steps_used": steps,
            "max_steps": max_steps,
            "provider": _provider_info(provider),
            "kb": req.kb,
            "faults": dict(req.faults),
            "trace": steps_trace,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
        return {"type": "final", "result": result}

    def step_event(step: int, name: str, args: dict, reason: str, obs: dict, ms: int) -> dict:
        ok = bool(obs.get("accepted")) if obs.get("accepted") is not None else bool(obs.get("ok", True))
        ev = {
            "type": "step", "step": step, "action": name,
            "args": args, "reason": reason, "ok": ok,
            "observation_summary": summarize_observation(name, obs),
            "observation": json.dumps(obs, ensure_ascii=False)[:600],
            "elapsed_ms": ms,
        }
        steps_trace.append(ev)
        return ev

    steps = 0
    while steps < max_steps:
        try:
            reply = provider.chat(messages, TOOL_SCHEMAS)
        except LLMError as e:
            yield emit(make_final("failed", None, [f"模型调用失败：{e}"], steps))
            return
        messages.append(reply.raw_message)

        if not reply.tool_calls:
            steps += 1
            messages.append({"role": "user", "content": NUDGE_MESSAGE})
            yield emit(step_event(steps, "(no_tool_call)", {}, "模型未调用工具", {"ok": False}, 0))
            continue

        for call in reply.tool_calls:
            if steps >= max_steps:
                break
            steps += 1
            t_step = time.monotonic()
            try:
                args = json.loads(call.arguments) if isinstance(call.arguments, str) else call.arguments
                if not isinstance(args, dict):
                    args = {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            reason = str(args.pop("reason", "") or "")
            obs = toolbox.execute(call.name, call.arguments, remaining=max_steps - steps)
            messages.append({
                "role": "tool", "tool_call_id": call.id, "name": call.name,
                "content": json.dumps(obs, ensure_ascii=False),
            })
            ms = int((time.monotonic() - t_step) * 1000)
            yield emit(step_event(steps, call.name, args, reason, obs, ms))
            if call.name == "submit_answer" and obs.get("accepted"):
                sub = obs["submission"]
                yield emit(make_final(sub.get("status", "answered"), sub, [], steps))
                return

    yield emit(make_final(
        "incomplete", None,
        [f"已达到最大步数 {max_steps}，任务未完成"], steps,
    ))


def run_to_result(req, provider, kb, trace_dir=None) -> dict:
    """消费完整生成器，返回 final.result（供 /api/ask 与评测脚本使用）。"""
    events = list(run_agent(req, provider, kb, trace_dir))
    if trace_dir is not None:
        from .trace import TraceWriter

        TraceWriter(trace_dir).write(events[-1]["result"]["run_id"], events)
    return events[-1]["result"]
