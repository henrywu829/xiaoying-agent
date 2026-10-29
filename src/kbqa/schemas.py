"""API 契约（§6.2 的唯一来源）。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

FAULT_TOOLS = {"search_docs", "read_doc"}
FAULT_MODES = {"fail_once", "fail_always"}


class HistoryMsg(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[HistoryMsg] = Field(default_factory=list, max_length=12)
    kb: str = "default"
    max_steps: int | None = Field(default=None, ge=1, le=12)
    faults: dict[str, str] = Field(default_factory=dict)
    mock: bool = False

    @field_validator("kb")
    @classmethod
    def kb_known(cls, v: str) -> str:
        from .kb import list_variants

        if v not in list_variants():
            raise ValueError(f"未知知识库变体：{v}")
        return v

    @field_validator("faults")
    @classmethod
    def faults_known(cls, v: dict[str, str]) -> dict[str, str]:
        for tool, mode in v.items():
            if tool not in FAULT_TOOLS:
                raise ValueError(f"未知故障工具：{tool}")
            if mode not in FAULT_MODES:
                raise ValueError(f"未知故障模式：{mode}")
        return v


class Citation(BaseModel):
    doc_id: str
    para_id: str
    title: str
    version_date: str
    quote: str


class ConflictPosition(BaseModel):
    para_id: str
    claim: str


class Conflict(BaseModel):
    topic: str
    positions: list[ConflictPosition] = Field(default_factory=list)
    resolution: Literal["unresolved", "resolved_by_doc", "resolved_by_user"] | str
    basis: str = ""
    basis_para_id: str | None = None
    basis_quote: str | None = None


class StepEvent(BaseModel):
    type: str = "step"
    step: int
    action: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    ok: bool
    observation_summary: str = ""
    observation: str = ""
    elapsed_ms: int = 0


class ProviderInfo(BaseModel):
    name: str
    model: str
    is_mock: bool


class AskResponse(BaseModel):
    run_id: str
    question: str
    status: str
    status_label: str
    answer: str = ""
    citations: list[Citation] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    clarifying_question: str = ""
    clarify_options: list[str] = Field(default_factory=list)
    evidence_read: list[str] = Field(default_factory=list)
    steps_used: int
    max_steps: int
    provider: ProviderInfo
    kb: str
    faults: dict[str, str] = Field(default_factory=dict)
    trace: list[StepEvent] = Field(default_factory=list)
    elapsed_ms: int = 0
