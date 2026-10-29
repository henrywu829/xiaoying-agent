"""Trace：观察摘要 + 运行事件落盘（runs/*.jsonl）。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _s(v) -> str:
    return "" if v is None else str(v)


def summarize_observation(action: str, obs: dict) -> str:
    if not isinstance(obs, dict):
        return _s(obs)[:120]
    if obs.get("ok") is False:
        err = obs.get("error") or {}
        return f"失败：{err.get('type', 'error')}（{err.get('message', '')}）"[:150]
    if action == "search_docs":
        hits = obs.get("hits") or []
        if not hits:
            terms = "、".join(obs.get("query_terms") or [])
            return f"无命中（词项：{terms}）"
        parts = "、".join(f"{h['para_id']}[{','.join(h.get('matched_terms') or [])}]" for h in hits)
        return f"命中 {len(hits)} 条：{parts}"
    if action == "read_doc":
        scope = obs.get("scope") or "未注明"
        return (f"读取 {obs.get('doc_id')}《{obs.get('title')}》{len(obs.get('paragraphs') or [])} 段，"
                f"版本 {obs.get('version_date')}，适用：{scope}")
    if action == "submit_answer":
        if obs.get("accepted"):
            sub = obs.get("submission") or {}
            n_opts = len(sub.get("clarify_options") or [])
            extra = f"（{n_opts} 个澄清选项）" if n_opts else ""
            return f"已接受：{sub.get('status')}{extra}"
        errs = "；".join(obs.get("errors") or [])
        return f"被拒绝：{errs}"[:200]
    return json.dumps(obs, ensure_ascii=False)[:150]


class TraceWriter:
    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def write(self, run_id: str, events: list[dict]) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.dir / f"{ts}_{run_id}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return path
