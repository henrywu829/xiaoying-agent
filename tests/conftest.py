import json
import uuid

import pytest

from kbqa.kb import load_kb
from kbqa.llm import LLMReply, ToolCall


@pytest.fixture(scope="session")
def kb_default():
    return load_kb("default")


@pytest.fixture(scope="session")
def kb_no_conflict():
    return load_kb("no_conflict")


@pytest.fixture(scope="session")
def kb_no_supersede():
    return load_kb("no_supersede")


def make_reply(tool_name: str, **args) -> LLMReply:
    tc = {"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
          "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)}}
    raw = {"role": "assistant", "content": None, "tool_calls": [tc]}
    return LLMReply(content=None, tool_calls=[ToolCall(tc["id"], tool_name, tc["function"]["arguments"])],
                    raw_message=raw)


def text_reply(content: str) -> LLMReply:
    return LLMReply(content=content, tool_calls=[], raw_message={"role": "assistant", "content": content})


def multi_reply(*tool_calls) -> LLMReply:
    """一次返回多个工具调用。"""
    tcs = []
    for name, args in tool_calls:
        tcs.append({"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    raw = {"role": "assistant", "content": None, "tool_calls": tcs}
    return LLMReply(content=None,
                    tool_calls=[ToolCall(t["id"], t["function"]["name"], t["function"]["arguments"]) for t in tcs],
                    raw_message=raw)


class ScriptedProvider:
    """script: (messages) -> LLMReply，可读取最近的工具观察作出反应。"""

    name = "scripted"
    model = "scripted-local"
    is_mock = True

    def __init__(self, script):
        self.script = script

    def chat(self, messages, tools):
        return self.script(messages)


def last_tool_obs(messages) -> dict:
    for m in reversed(messages):
        if m.get("role") == "tool":
            return json.loads(m.get("content") or "{}")
    return {}


def make_req(question: str, **kw):
    from kbqa.schemas import AskRequest

    body = {"question": question, "kb": kw.pop("kb", "default")}
    body.update(kw)
    return AskRequest(**body)
