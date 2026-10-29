"""FastAPI 入口：/api/* 路由 + web/ 静态托管。同步生成器经线程池迭代，无需 async。"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .agent import run_agent, run_to_result
from .config import CASES_PATH, WEB_DIR, load_settings
from .kb import list_variants, load_kb
from .llm import make_provider
from .schemas import AskRequest

app = FastAPI(title="溯源问答 Agent")
_settings = load_settings()


def _resolve(req: AskRequest) -> tuple[AskRequest, object, object]:
    if req.max_steps is None:
        req = req.model_copy(update={"max_steps": _settings.agent_max_steps})
    provider = make_provider(_settings, force_mock=req.mock)
    kb = load_kb(req.kb)
    return req, provider, kb


@app.get("/api/health")
def health() -> dict:
    probe = make_provider(_settings)
    return {
        "provider": {"name": probe.name, "model": probe.model, "is_mock": probe.is_mock},
        "model": probe.model,
        "is_mock": probe.is_mock,
        "kb_variants": [{"name": k, "description": v.get("description", "")}
                        for k, v in list_variants().items()],
        "default_max_steps": _settings.agent_max_steps,
        "max_steps_limit": 12,
    }


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    req, provider, kb = _resolve(req)
    return run_to_result(req, provider, kb, trace_dir=_settings.trace_dir)


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    req, provider, kb = _resolve(req)
    events = list(run_agent(req, provider, kb))
    if events:
        from .trace import TraceWriter

        TraceWriter(_settings.trace_dir).write(events[0].get("run_id", "run"), events)

    def gen():
        for ev in events:
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/cases")
def cases() -> list:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


@app.get("/api/kb/{variant}/docs")
def list_docs(variant: str) -> list:
    kb = load_kb(variant)
    return [
        {
            "doc_id": d.doc_id, "title": d.title, "version_date": d.version_date,
            "scope": d.scope, "supersedes": d.supersedes, "category": d.category,
            "n_paragraphs": len(d.paragraphs),
        }
        for d in kb.docs.values()
    ]


@app.get("/api/kb/{variant}/docs/{doc_id}")
def get_doc(variant: str, doc_id: str) -> dict:
    doc = load_kb(variant).get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    return {
        "doc_id": doc.doc_id, "title": doc.title, "version_date": doc.version_date,
        "scope": doc.scope, "supersedes": doc.supersedes, "category": doc.category,
        "paragraphs": [{"para_id": p.para_id, "text": p.text} for p in doc.paragraphs],
    }


# 静态托管必须注册在所有 /api 路由之后
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
