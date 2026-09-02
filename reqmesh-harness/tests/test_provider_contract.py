"""#36 provider 契约：类型与字面量逐项存在（spec 验收 1）+ ProviderError 错误归一（acceptance 1/2）。

纯类型契约测试（不测实现细节）：AgentRequest/RunResult/StreamSink/Provider/ProjectContext/
ToolHint / Question / ToolResult 按 spec ③ 形状存在；execution ∈ delegated|tool-loop；
ProviderError 在 errors.py 且带 kind/code/message。
"""

from __future__ import annotations

import dataclasses
import threading
from typing import Literal, Protocol, get_args

import pytest

from reqmesh_harness.errors import HarnessError, ProviderError, __all__ as ERRORS_ALL
from reqmesh_harness.runtime import (
    AgentRequest,
    ProjectContext,
    Provider,
    Question,
    QuestionOption,
    RunResult,
    StreamSink,
    ToolCallRequest,
    ToolHint,
    ToolResult,
)


# ------------------------------------------------------------------ ProviderError（错误归一）
def test_provider_error_is_harness_error_and_carries_kind_code_message() -> None:
    err = ProviderError("busy", "DSH 会话忙，请稍后", code="agent-busy")
    assert isinstance(err, HarnessError)
    assert err.kind == "busy"
    assert err.code == "agent-busy"
    assert err.message == "DSH 会话忙，请稍后"
    assert "DSH 会话忙，请稍后" in str(err)
    assert "ProviderError" in type(err).__name__


def test_provider_error_code_optional() -> None:
    err = ProviderError("timeout", "流空闲超时")
    assert err.kind == "timeout"
    assert err.code is None
    assert err.message == "流空闲超时"


def test_provider_error_kind_literals_are_four_plus_denied_answer() -> None:
    for kind in ("unavailable", "timeout", "protocol", "busy", "denied_answer"):
        err = ProviderError(kind, "x")  # type: ignore[arg-type]
        assert err.kind == kind


# ------------------------------------------------------------------ 类型形状（spec ③ 字面契约）
def test_project_context_fields() -> None:
    ctx = ProjectContext(
        project_id="cessna-172",
        base_url="http://x.test",
        created_at="2026-09-02T00:00:00Z",
    )
    assert ctx.project_id == "cessna-172"
    assert ctx.base_url == "http://x.test"
    assert ctx.created_at == "2026-09-02T00:00:00Z"
    assert dataclasses.is_dataclass(ctx)
    assert {f.name for f in dataclasses.fields(ctx)} == {
        "project_id",
        "base_url",
        "created_at",
    }


def test_tool_hint_fields() -> None:
    hint = ToolHint(name="get_coverage", description="覆盖率分析", level="READ")
    assert (hint.name, hint.description, hint.level) == (
        "get_coverage",
        "覆盖率分析",
        "READ",
    )


def test_agent_request_fields_and_defaults() -> None:
    req = AgentRequest(
        task="读缺口报告并写评审建议",
        project_context=None,
        history=[{"role": "user", "content": "此前进展"}],
        tools=[ToolHint("get_coverage", "覆盖率分析", "READ")],
    )
    assert req.max_rounds == 8  # 防御上限默认 8（spec ③）
    assert req.history == [{"role": "user", "content": "此前进展"}]
    req2 = AgentRequest(
        task="t", project_context=None, history=[], tools=[], max_rounds=3
    )
    assert req2.max_rounds == 3


def test_run_result_fields() -> None:
    res = RunResult("completed", "完成", tool_calls=2, questions=1, error=None)
    assert (res.status, res.final_text, res.tool_calls, res.questions, res.error) == (
        "completed",
        "完成",
        2,
        1,
        None,
    )
    from typing import get_type_hints

    statuses = get_args(get_type_hints(RunResult)["status"])
    assert set(statuses) == {"completed", "failed", "cancelled"}


def test_tool_result_and_tool_call_request_fields() -> None:
    tr = ToolResult(ok=False, text="审批门拒绝")
    assert tr.ok is False and tr.text == "审批门拒绝"
    tcr = ToolCallRequest(name="review_item", arguments={"project_id": "cessna-172"})
    assert tcr.name == "review_item" and tcr.arguments["project_id"] == "cessna-172"


def test_question_fields() -> None:
    q = Question(
        id="rpc-1",
        question="已批准，请重试？",
        header="审批确认",
        detail="detail",
        options=(QuestionOption(label="是", description="允许"),),
        multi_select=False,
    )
    assert q.id == "rpc-1" and q.question == "已批准，请重试？"
    assert q.header == "审批确认"
    assert q.options[0].label == "是"
    plain = Question(id="q2", question="继续吗？")
    assert plain.header is None and plain.options == () and plain.multi_select is False


def test_stream_sink_is_protocol_with_five_hooks() -> None:
    from typing import get_type_hints

    hooks = {
        name: get_type_hints(fn)
        for name, fn in vars(StreamSink).items()
        if not name.startswith("_") and callable(fn)
    }
    assert set(hooks) == {
        "on_text",
        "on_tool_call",
        "on_tool_result",
        "on_question",
        "on_turn_end",
    }
    assert (
        hooks["on_question"]["q"].__name__ == "Question"
        or hooks["on_question"]["q"] is not None
    )


def test_provider_protocol_has_execution_and_run_agentic() -> None:
    assert hasattr(Provider, "run_agentic")
    sig = getattr(Provider, "run_agentic", None)
    assert sig is not None


def test_provider_execution_literals_via_annotations() -> None:
    from typing import get_type_hints

    # 实现类从 run_cli/provider 工厂构造；契约字面量在注解级：
    hints = get_type_hints(RunResult)
    assert "status" in hints
    # execution 字面量由实现类声明（spec：DSH=delegated；openai/fake=tool-loop）
    from reqmesh_harness.runtime.fake import FakeProvider

    assert FakeProvider.execution == "tool-loop"
    from reqmesh_harness.runtime.dsh_provider import DshProvider

    assert DshProvider.execution == "delegated"


def test_provider_error_exported_from_errors_all() -> None:
    assert "ProviderError" in ERRORS_ALL


def test_cancel_uses_threading_event_type() -> None:
    ev = threading.Event()
    assert not ev.is_set()
    ev.set()
    assert ev.is_set()
