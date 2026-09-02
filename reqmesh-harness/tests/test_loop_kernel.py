"""#39 loop 内核：指令模板（spec ② 契约语句）、executor（registry.call + 错误回灌 + 未知工具名）、
RunDriver 两执行所有权分支走同一 StreamSink（验收 6/7）。"""

from __future__ import annotations

import json
import threading

import pytest
import respx
from httpx import Response

from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime import AgentRequest, ProjectContext
from reqmesh_harness.runtime.loop import (
    RunDriver,
    ToolExecutor,
    assemble_request,
    build_task_instruction,
    compose_prompt,
    run_task,
)
from reqmesh_harness.runtime.fake import EndStep, FakeProvider, TextStep, ToolStep
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import set_runtime

CTX = ProjectContext(
    project_id="cessna-172",
    base_url="http://reqmesh.test",
    created_at="2026-01-01T00:00:00Z",
)


def test_assemble_request_tool_hints_from_registry() -> None:
    request = assemble_request(
        "读缺口报告",
        project_context=CTX,
        history=[],
        registry=build_registry(),
        max_rounds=8,
    )
    assert isinstance(request, AgentRequest)
    assert request.task == "读缺口报告"
    assert request.project_context == CTX
    assert request.max_rounds == 8
    names = {h.name for h in request.tools}
    assert "get_traceability_gap_report" in names
    assert "draft_requirement" in names
    assert len(request.tools) == 40  # P1–P4 契约：40 个工具
    hint = next(h for h in request.tools if h.name == "review_item")
    assert hint.level == "DRAFT"
    assert hint.description.startswith("DRAFT")  # description 首行 = docstring 首行


def test_instruction_template_contract_sentences() -> None:
    request = assemble_request(
        "用自然语言建一条需求",
        project_context=CTX,
        history=[],
        registry=build_registry(),
        max_rounds=3,
    )
    text = build_task_instruction(request)
    # spec ② 模板关键句（内容为契约，测试断言包含关键句）
    assert "你是 reqmesh-harness 的内置 agent，运行任务由 harness 委派" in text
    assert "project context：project_id=cessna-172" in text
    assert "可用工具仅限 `mcp__reqmesh__*`" in text
    assert "mcp__reqmesh__review_item" in text and "提交对某需求的评审" in text
    assert "只允许调用 mcp__reqmesh__* 工具完成本任务" in text
    assert "不得使用 bash/文件工具修改任何文件" in text
    assert "approvals add" in text
    assert "提问机制" in text and "确认" in text
    assert "重试一次" in text
    assert "最终总结须列出你调用过的工具名与关键结果" in text
    assert "最多进行 3 轮" in text


def test_instruction_template_without_project_context() -> None:
    request = assemble_request(
        "列出项目", project_context=None, history=[], registry=build_registry()
    )
    text = build_task_instruction(request)
    assert "未指定 project context" in text


def test_compose_prompt_injects_history_and_task() -> None:
    request = AgentRequest(
        task="继续建需求",
        project_context=CTX,
        history=[{"role": "user", "content": "此前已读到缺口报告"}],
        tools=[],
    )
    prompt = compose_prompt(request)
    assert build_task_instruction(request) in prompt
    assert "历史由 harness 内存重建" in prompt
    assert "此前已读到缺口报告" in prompt
    assert "任务：继续建需求" in prompt


def test_compose_prompt_no_history_no_marker() -> None:
    request = AgentRequest(task="纯任务", project_context=None, history=[], tools=[])
    prompt = compose_prompt(request)
    assert "历史由 harness 内存重建" not in prompt
    assert "任务：纯任务" in prompt


class _Exec:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict, ctx) -> object:
        self.calls.append((name, args))
        return None


def test_executor_runs_registry_call_and_renders_json(reqmesh_env, monkeypatch) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(
            return_value=Response(
                200, json={"username": "reqmesh-harness", "role": "maintainer"}
            )
        )
        ex = ToolExecutor(registry=build_registry())
        result = ex("whoami", {}, None)
    assert result.ok is True
    data = json.loads(result.text)
    assert data["username"] == "reqmesh-harness"


def test_executor_strips_mcp_prefix(reqmesh_env, monkeypatch) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(
            return_value=Response(
                200, json={"username": "reqmesh-harness", "role": "maintainer"}
            )
        )
        ex = ToolExecutor(registry=build_registry())
        result = ex("mcp__reqmesh__whoami", {}, None)
    assert result.ok is True


def test_executor_maps_denied_to_error_text_with_fix_hint(
    reqmesh_env, monkeypatch
) -> None:
    """ApprovalDeniedError → ok=False 错误文本（含 fix_hint），与 DSH 侧 MCP tool error 同形态。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        ex = ToolExecutor(registry=build_registry())
        result = ex(
            "review_item", {"project_id": "cessna-172", "req_id": "AFRM0000"}, CTX
        )
    assert result.ok is False
    assert "approvals add review_item" in result.text


def test_executor_unknown_tool_is_protocol_error() -> None:
    with pytest.raises(ProviderError) as exc:
        ToolExecutor(registry=build_registry())("bash", {}, None)
    assert exc.value.kind == "protocol"
    assert "未知工具名" in exc.value.message


@pytest.mark.asyncio
async def test_run_driver_injects_executor_and_drives_tool_loop(
    reqmesh_env, monkeypatch
) -> None:
    """tool-loop 分支：RunDriver 注入 executor → FakeProvider 脚本 → 同一 StreamSink 事件。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(
            return_value=Response(
                200, json={"username": "reqmesh-harness", "role": "maintainer"}
            )
        )
        events: list[str] = []

        class Sink:
            def on_text(self, text: str) -> None:
                events.append("text:" + text)

            def on_tool_call(self, name: str, args: dict) -> None:
                events.append("call:" + name)

            def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
                events.append("result:" + name + ":" + str(ok))

            def on_question(self, q) -> None:
                events.append("question")

            def on_turn_end(self, reason: str) -> None:
                events.append("turn_end:" + reason)

        provider = FakeProvider(
            [
                TextStep("读取"),
                ToolStep("whoami", {}),
                EndStep("completed", "完成"),
            ]
        )
        result = await run_task(
            "查询用户",
            provider=provider,
            project_context=CTX,
            registry=build_registry(),
            sink=Sink(),
            cancel=threading.Event(),
        )
    assert result.status == "completed"
    assert result.tool_calls == 1
    assert events == [
        "text:读取",
        "call:whoami",
        "result:whoami:True",
        "turn_end:completed",
    ]


@pytest.mark.asyncio
async def test_run_task_delegated_branch_passthrough() -> None:
    """delegated 分支：RunResult 原样透传（DSH provider 内部闭环；此处以 stub 验证驱动层）。"""

    class Delegated:
        name = "stub"
        execution = "delegated"

        def __init__(self, result) -> None:
            self.result = result

        async def run_agentic(self, request, sink, *, cancel):
            sink.on_text("来自 provider")
            return self.result

    result = await run_task(
        "任意任务",
        provider=Delegated(object()),
        registry=build_registry(),
        sink=_DeadSink(),
    )
    assert result is not None


class _DeadSink:
    def on_text(self, text): ...
    def on_tool_call(self, name, args): ...
    def on_tool_result(self, name, ok, summary): ...
    def on_question(self, q): ...
    def on_turn_end(self, reason): ...
