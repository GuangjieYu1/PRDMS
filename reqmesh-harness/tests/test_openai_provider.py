"""#42 OpenAI 兼容 provider（自驱 tool-loop）：请求形状（system 指令 + 历史 + tools=export_openai_functions
1:1）、SSE 流式解析（content delta + tool_calls delta 累积）、工具结果回灌第二请求、防御轮数、
无 key 启动错误归一（spec 验收 11）。全离线 respx。"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
import respx
from httpx import Response

from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime.loop import ToolExecutor
from reqmesh_harness.runtime.openai_provider import OpenAIProvider
from reqmesh_harness.runtime.provider import AgentRequest, ProjectContext, ToolResult
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.export import export_openai_functions

FIXTURES = Path(__file__).parent / "fixtures" / "openai"
OPENAI = "http://openai.test"
CTX = ProjectContext(
    project_id="cessna-172",
    base_url="http://reqmesh.test",
    created_at="2026-01-01T00:00:00Z",
)


def _settings(**overrides) -> Settings:
    kw = dict(
        openai_base_url=OPENAI, openai_api_key="sk-test", openai_model="deepseek-chat"
    )
    kw.update(overrides)
    return Settings(**kw)


class RecordingSink:
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


def _request(**overrides) -> AgentRequest:
    kw = dict(
        task="查一下当前用户",
        project_context=CTX,
        history=[{"role": "user", "content": "此前进展"}],
        tools=[],
        max_rounds=3,
    )
    kw.update(overrides)
    return AgentRequest(**kw)


def _sse(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_request_shape_matches_export_openai_functions(reqmesh_env) -> None:
    """请求体契约：system=指令（含任务）、history 原样、tools == export_openai_functions(registry) 1:1。"""
    captured: dict = {}

    def handler(request) -> Response:
        captured["body"] = json.loads(request.content)
        return Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse("chat_final_sse.txt"),
        )

    registry = build_registry()
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(side_effect=handler)
        provider = OpenAIProvider(
            settings=_settings(),
            registry=registry,
            executor=ToolExecutor(registry=registry),
        )
        result = await provider.run_agentic(
            _request(), RecordingSink(), cancel=threading.Event()
        )
    body = captured["body"]
    assert body["model"] == "deepseek-chat"
    assert body["stream"] is True
    # tools == export_openai_functions（40 个工具 1:1，无 $defs 残留）
    assert body["tools"] == export_openai_functions(registry)
    assert len(body["tools"]) == 40
    # messages：system（指令）+ history + user（任务）
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert "你是 reqmesh-harness 的内置 agent" in messages[0]["content"]
    assert (
        messages[0]["content"].endswith("最多进行 3 轮")
        or "3 轮" in messages[0]["content"]
    )
    assert messages[1] == {"role": "user", "content": "此前进展"}
    assert messages[2] == {"role": "user", "content": "查一下当前用户"}
    assert result.status == "completed"
    assert result.final_text == "任务完成。"


@pytest.mark.asyncio
async def test_tool_call_deltas_accumulate_and_result_feeds_second_request(
    reqmesh_env,
) -> None:
    """SSE：content delta + tool_calls delta（arguments 分片）→ executor 执行 → 第二请求带
    assistant tool_calls + tool 结果 → 最终文本。"""
    requests: list[dict] = []

    def handler(request) -> Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=_sse("chat_tool_sse.txt"),
            )
        return Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse("chat_final_sse.txt"),
        )

    registry = build_registry()
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(side_effect=handler)
        with respx.mock(base_url="http://reqmesh.test") as reqmesh_router:
            reqmesh_router.get("/api/auth/whoami").mock(
                return_value=Response(
                    200, json={"username": "reqmesh-harness", "role": "maintainer"}
                )
            )
            provider = OpenAIProvider(
                settings=_settings(),
                registry=registry,
                executor=ToolExecutor(registry=registry),
            )
            sink = RecordingSink()
            result = await provider.run_agentic(
                _request(history=[]), sink, cancel=threading.Event()
            )
    # ① 流式：text chunks 逐块 + tool_call/tool_result/…/turn_end
    assert [e[0] for e in sink.events] == [
        "text",
        "text",
        "tool_call",
        "tool_result",
        "text",
        "turn_end",
    ]
    tool_result = [e for e in sink.events if e[0] == "tool_result"][0]
    assert tool_result[1] == "whoami" and tool_result[2] is True
    assert result.status == "completed"
    assert result.tool_calls == 1
    assert "任务完成" in result.final_text
    # ② 第二请求：assistant message（tool_calls）+ tool 结果回灌
    second = requests[1]
    assert len(second["messages"]) == 4  # system + user + assistant + tool
    assistant = second["messages"][2]
    assert assistant["role"] == "assistant"
    assert len(assistant["tool_calls"]) == 1
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert assistant["tool_calls"][0]["function"]["name"] == "whoami"
    assert (
        json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {}
    )  # 分片累积
    tool_msg = second["messages"][3]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert "reqmesh-harness" in tool_msg["content"]
    assert second["messages"][1]["content"] == "查一下当前用户"


@pytest.mark.asyncio
async def test_no_api_key_raises_unavailable_before_any_request() -> None:
    with respx.mock(base_url=OPENAI) as router:
        provider = OpenAIProvider(
            settings=_settings(openai_api_key=""), registry=build_registry()
        )
        with pytest.raises(ProviderError) as exc:
            await provider.run_agentic(
                _request(), RecordingSink(), cancel=threading.Event()
            )
    assert exc.value.kind == "unavailable"
    assert "REQMESH_OPENAI_API_KEY" in exc.value.message
    assert router.calls == []


@pytest.mark.asyncio
async def test_max_rounds_defense_limit(reqmesh_env) -> None:
    """持续工具调用超过 max_rounds → ProviderError(protocol)（防御上限，spec ③）。"""
    requests: list[dict] = []

    def handler(request) -> Response:
        requests.append(json.loads(request.content))
        return Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse("chat_tool_sse.txt"),
        )

    registry = build_registry()
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(side_effect=handler)
        with respx.mock(base_url="http://reqmesh.test") as reqmesh_router:
            reqmesh_router.get("/api/auth/whoami").mock(
                return_value=Response(200, json={"username": "x", "role": "view"})
            )
            provider = OpenAIProvider(
                settings=_settings(),
                registry=registry,
                executor=ToolExecutor(registry=registry),
            )
            with pytest.raises(ProviderError) as exc:
                await provider.run_agentic(
                    _request(max_rounds=2), RecordingSink(), cancel=threading.Event()
                )
    assert exc.value.kind == "protocol"
    assert "防御" in exc.value.message or "轮数" in exc.value.message


@pytest.mark.asyncio
async def test_http_error_normalized_to_unavailable() -> None:
    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(
            return_value=Response(500, json={"error": {"message": "boom"}})
        )
        provider = OpenAIProvider(
            settings=_settings(),
            registry=build_registry(),
            executor=lambda name, args, ctx: ToolResult(True, "x"),
        )
        with pytest.raises(ProviderError) as exc:
            await provider.run_agentic(
                _request(), RecordingSink(), cancel=threading.Event()
            )
    assert exc.value.kind == "unavailable"
    assert "boom" in exc.value.message


@pytest.mark.asyncio
async def test_cancel_between_model_calls(reqmesh_env) -> None:
    """cancel 置位于工具执行后、第二轮模型调用前 → RunResult(cancelled)（不再发第二轮请求）。"""
    requests: list[dict] = []

    def handler(request) -> Response:
        requests.append(json.loads(request.content))
        return Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse("chat_tool_sse.txt"),
        )

    registry = build_registry()
    cancel = threading.Event()

    class CancelAfterCall:
        def __init__(self, inner, event: threading.Event) -> None:
            self._inner = inner
            self._event = event

        def __call__(self, name, args, ctx):
            result = self._inner(name, args, ctx)
            self._event.set()  # 工具执行完成后置位（模拟 Ctrl-C）
            return result

    with respx.mock(base_url=OPENAI) as router:
        router.post("/chat/completions").mock(side_effect=handler)
        with respx.mock(base_url="http://reqmesh.test") as reqmesh_router:
            reqmesh_router.get("/api/auth/whoami").mock(
                return_value=Response(200, json={"username": "x", "role": "view"})
            )
            provider = OpenAIProvider(settings=_settings(), registry=registry)
            provider.executor = CancelAfterCall(ToolExecutor(registry=registry), cancel)
            result = await provider.run_agentic(
                _request(max_rounds=5), RecordingSink(), cancel=cancel
            )
    assert result.status == "cancelled"
    assert len(requests) == 1  # 第二轮未发出
