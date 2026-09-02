"""P5 测试子代理补充用例（run CLI / OpenAI provider 边缘）：验收 8/10/11 的未覆盖分支。

- run CLI 审计摘要：denied/approved 计数（_print_audit_summary）；
- resume 分支② history 字段形状（{"role","content"} 列表，spec ⑤）；
- OpenAI SSE：空行 / 空 data 行 / keepalive 跳过；tool 参数非对象 → protocol；HTTP 非 200 非 JSON 文本归一。

全部离线（respx + 注入 stub provider）；不改动既有测试与 src/。
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path

import pytest
import respx
from httpx import Response

from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime.loop import ToolExecutor
from reqmesh_harness.runtime.memory import RunRecorder
from reqmesh_harness.runtime.openai_provider import OpenAIProvider
from reqmesh_harness.runtime.provider import AgentRequest, ProjectContext, ToolResult
from reqmesh_harness.runtime.run_cli import run_main
from reqmesh_harness.tools import build_registry

from tests.test_run_cli import StubProvider, _cli_env, _factory

OPENAI = "http://openai.test"
CTX = ProjectContext(project_id="cessna-172", base_url="http://reqmesh.test", created_at="2026-01-01T00:00:00Z")


def _settings(**overrides) -> Settings:
    kw = dict(openai_base_url=OPENAI, openai_api_key="sk-test", openai_model="deepseek-chat")
    kw.update(overrides)
    return Settings(**kw)


def _orequest(**overrides) -> AgentRequest:
    kw = dict(task="查一下当前用户", project_context=CTX, history=[], tools=[], max_rounds=3)
    kw.update(overrides)
    return AgentRequest(**kw)


class _Sink:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_text(self, text: str) -> None:
        self.events.append(("text", text))

    def on_tool_call(self, name: str, args: dict) -> None:
        self.events.append(("tool_call", name))

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.events.append(("tool_result", name, ok))

    def on_question(self, q) -> None:
        self.events.append(("question", q))

    def on_turn_end(self, reason: str) -> None:
        self.events.append(("turn_end", reason))


# ------------------------------------------------------------------ run CLI 审计摘要计数
def test_run_cli_audit_summary_counts_denied_approved(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    audit_file = tmp_path / "audit.jsonl"
    rows = [
        {"decision": "denied", "tool": "review_item", "level": "DRAFT", "version": 1},
        {"decision": "denied", "tool": "draft_requirement", "level": "DRAFT", "version": 1},
        {"decision": "approved", "tool": "review_item", "level": "DRAFT", "version": 1},
    ]
    audit_file.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects").mock(return_value=Response(200, json=[]))
        code = run_main(["只读任务"], provider_factory=_factory(stub), steer_input=io.StringIO())
    assert code == 0
    out = capsys.readouterr().out
    assert "共 3 行" in out
    assert "denied 2" in out
    assert "approved 1" in out
    assert "review_item" in out and "draft_requirement" in out


# ------------------------------------------------------------------ resume 分支② history 形状
def test_run_resume_branch2_history_field_shape(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    root = Path(tmp_path) / "runs"
    old = RunRecorder.create(root)
    old.init_context(task="原任务", project_context=None, provider="dsh")
    old.save_dsh_session("dsn-old-gone")
    old.record_done("completed", "最终文本", tool_calls=1, questions=0)
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects").mock(return_value=Response(200, json=[]))
        code = run_main(
            ["继续", "--resume", old.run_id],
            provider_factory=_factory(stub),
            session_live_check=lambda sid: False,
            steer_input=io.StringIO(),
        )
    assert code == 0
    history = stub.requests[0].history
    # spec ⑤：history 为 {"role","content"} 列表（单条摘要注入）
    assert isinstance(history, list) and len(history) == 1
    assert set(history[0].keys()) == {"role", "content"}
    assert history[0]["role"] == "user"
    assert "历史由 harness 内存重建" in history[0]["content"]


# ------------------------------------------------------------------ OpenAI SSE 空行/keepalive
@pytest.mark.asyncio
async def test_openai_sse_skips_empty_and_keepalive_lines() -> None:
    sse = (
        'data: {"choices":[{"delta":{"content":"甲"}}]}\n'
        "\n"
        "data: \n"
        "\n"
        ": keepalive\n"
        'data: {"choices":[{"delta":{"content":"乙"}}]}\n'
        "\n"
        "data: [DONE]\n"
        "\n"
    )
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(
            return_value=Response(200, headers={"content-type": "text/event-stream"}, content=sse))
        provider = OpenAIProvider(
            settings=_settings(), registry=build_registry(),
            executor=ToolExecutor(registry=build_registry()))
        sink = _Sink()
        result = await provider.run_agentic(_orequest(), sink, cancel=threading.Event())
    assert result.status == "completed"
    assert [e[1] for e in sink.events if e[0] == "text"] == ["甲", "乙"]


# ------------------------------------------------------------------ OpenAI tool 参数非对象
@pytest.mark.asyncio
async def test_openai_tool_arguments_non_object_is_protocol() -> None:
    sse = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
           '"function":{"name":"whoami","arguments":"[1,2,3]"}}]}}]}\n\ndata: [DONE]\n\n')
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(
            return_value=Response(200, headers={"content-type": "text/event-stream"}, content=sse))
        provider = OpenAIProvider(
            settings=_settings(), registry=build_registry(),
            executor=lambda name, args, ctx: ToolResult(True, "x"))
        with pytest.raises(ProviderError) as exc:
            await provider.run_agentic(_orequest(), _Sink(), cancel=threading.Event())
    assert exc.value.kind == "protocol"
    assert "参数应为对象" in exc.value.message


# ------------------------------------------------------------------ OpenAI HTTP 非 200 非 JSON
@pytest.mark.asyncio
async def test_openai_http_non_json_error_body_normalized() -> None:
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(return_value=Response(502, text="bad gateway <html>"))
        provider = OpenAIProvider(
            settings=_settings(), registry=build_registry(),
            executor=lambda name, args, ctx: ToolResult(True, "x"))
        with pytest.raises(ProviderError) as exc:
            await provider.run_agentic(_orequest(), _Sink(), cancel=threading.Event())
    assert exc.value.kind == "unavailable"
    assert "HTTP 502" in exc.value.message
    assert "bad gateway" in exc.value.message
