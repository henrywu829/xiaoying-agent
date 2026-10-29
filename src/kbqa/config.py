"""配置加载：环境变量 + .env（LLM_API_KEY 留空即 Mock）。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
KB_ROOT = REPO_ROOT / "data" / "kb"
WEB_DIR = REPO_ROOT / "web"
CASES_PATH = REPO_ROOT / "data" / "eval_cases.json"


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout: float
    agent_max_steps: int
    trace_dir: Path


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    return Settings(
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
        llm_model=os.getenv("LLM_MODEL", "deepseek-flash"),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        agent_max_steps=int(os.getenv("AGENT_MAX_STEPS", "10")),
        trace_dir=REPO_ROOT / os.getenv("TRACE_DIR", "runs"),
    )
