"""#36 FakeProvider：脚本化 turn 序列 + 工具序列断言 + 问题应答 + 取消（离线、无网络）。

脚本步骤（Text/Tool/Question/End）按顺序消费；executor 回灌结果与步骤期望失配 →
ProviderError(protocol)；取消事件在步骤间生效。
"""

from __future__ import annotations

import threading

import pytest

from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime import (
    AgentRequest,
    ProjectContext,
    Question,
    RunResult,
    ToolResult,
)
from reqmesh_harness.runtime.fake import (
    EndStep,
    FakeProvider,
    QuestionStep,
    TextStep,
    ToolStep,
)

CTX = ProjectContext(
    project_id="cessna-172",
    base_url="http://reqmesh.test",
    created_at="2026-01-01T00:00:00Z",
)


def _request(**overrides) -> AgentRequest:
    kw = dict(
        task="读缺口报告并写评审建议",
        project_context=CTX,
        history=[],
        tools=[],
        max_rounds=8,
    )
    kw.update(overrides)
    return AgentRequest(**kw)


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def on_text(self, text: str) -> None:
        self.events.append(("text", text))

    def on_tool_call(self, name: str, args: dict) -> None:
        self.events.append(("tool_call", (name, args)))

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.events.append(("tool_result", (name, ok, summary)))

    def on_question(self, q: Question) -> None:
        self.events.append(("question", q))

    def on_turn_end(self, reason: str) -> None:
        self.events.append(("turn_end", reason))


class Executor:
    def __init__(self, results: list[ToolResult]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, name: str, args: dict, project_context) -> ToolResult:
        self.calls.append((name, args))
        if not self.results:
            raise AssertionError("executor 被调用了意外次数")
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_fake_script_sequence_consumed_and_events_ordered() -> None:
    """文本 → 工具调用（ok）→ 结束：事件顺序 text→tool_call→tool_result→turn_end。"""
    executor = Executor(
        [ToolResult(ok=True, text="报告已生成"), ToolResult(ok=True, text="已提交评审")]
    )
    provider = FakeProvider(
        [
            TextStep("先读一下缺口报告。"),
            ToolStep("get_traceability_gap_report", {"project_id": "cessna-172"}),
            TextStep("发现缺口，提交评审。"),
            ToolStep(
                "review_item",
                {
                    "project_id": "cessna-172",
                    "req_id": "AFRM0000",
                    "comment": "补充来源",
                },
                expect_ok=True,
                expect_text="已提交评审",
            ),
            EndStep(status="completed", final_text="任务完成：1 条评审建议已提交。"),
        ],
        executor=executor,
    )
    sink = RecordingSink()
    result = await provider.run_agentic(_request(), sink, cancel=threading.Event())
    assert isinstance(result, RunResult)
    assert result.status == "completed"
    assert "任务完成" in result.final_text
    assert result.tool_calls == 2
    assert result.questions == 0
    # 工具调用序列断言（落在此处）
    assert executor.calls == [
        ("get_traceability_gap_report", {"project_id": "cessna-172"}),
        (
            "review_item",
            {"project_id": "cessna-172", "req_id": "AFRM0000", "comment": "补充来源"},
        ),
    ]
    kinds = [e[0] for e in sink.events]
    assert kinds == [
        "text",
        "tool_call",
        "tool_result",
        "text",
        "tool_call",
        "tool_result",
        "turn_end",
    ]


@pytest.mark.asyncio
async def test_fake_script_tool_error_expected() -> None:
    """工具错误步骤：executor 回灌 ok=False（如审批门拒绝）且文本匹配 → 继续脚本。"""
    executor = Executor(
        [ToolResult(ok=False, text="审批门拒绝 review_item: 白名单无该工具的条目")]
    )
    provider = FakeProvider(
        [
            ToolStep(
                "review_item",
                {"project_id": "cessna-172", "req_id": "AFRM0000"},
                expect_ok=False,
                expect_text="审批门拒绝 review_item: 白名单无该工具的条目",
            ),
            EndStep("completed", "总结：评审未提交。"),
        ],
        executor=executor,
    )
    sink = RecordingSink()
    result = await provider.run_agentic(_request(), sink, cancel=threading.Event())
    assert result.status == "completed"
    tool_result = [e for e in sink.events if e[0] == "tool_result"]
    assert tool_result[0][1][1] is False


@pytest.mark.asyncio
async def test_fake_script_order_mismatch_is_protocol_error() -> None:
    """顺序失配（期望 ok 但实际失败）→ AssertionError 归一为 ProviderError(protocol)。"""
    executor = Executor([ToolResult(ok=False, text="审批门拒绝")])
    provider = FakeProvider(
        [
            ToolStep("review_item", {"project_id": "cessna-172"}, expect_ok=True),
            EndStep("completed"),
        ],
        executor=executor,
    )
    with pytest.raises(ProviderError) as exc:
        await provider.run_agentic(
            _request(), RecordingSink(), cancel=threading.Event()
        )
    assert exc.value.kind == "protocol"
    assert "脚本断言失败" in exc.value.message


@pytest.mark.asyncio
async def test_fake_script_mismatch_text_is_protocol_error() -> None:
    executor = Executor([ToolResult(ok=True, text="其他文本")])
    provider = FakeProvider(
        [
            ToolStep(
                "review_item",
                {"project_id": "cessna-172"},
                expect_ok=True,
                expect_text="已提交评审",
            )
        ],
        executor=executor,
    )
    with pytest.raises(ProviderError) as exc:
        await provider.run_agentic(
            _request(), RecordingSink(), cancel=threading.Event()
        )
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_fake_question_step_answered_via_injected_answerer() -> None:
    """问题步骤：sink.on_question 通知 + answerer 被调用（问题应答）；计数进 RunResult.questions。"""
    answers: list[Question] = []

    def answerer(q: Question) -> str:
        answers.append(q)
        return "已批准，请重试"

    provider = FakeProvider(
        [
            TextStep("工具被拒绝。"),
            QuestionStep(
                question=Question(id="rpc-1", question="是否批准 review_item？")
            ),
            EndStep("completed", "已批准并重试成功。"),
        ],
        question_answerer=answerer,
    )
    sink = RecordingSink()
    result = await provider.run_agentic(_request(), sink, cancel=threading.Event())
    assert result.questions == 1
    assert [q.id for q in answers] == ["rpc-1"]
    assert any(e[0] == "question" for e in sink.events)
    # 问题步骤不产生工具调用
    assert result.tool_calls == 0


@pytest.mark.asyncio
async def test_fake_cancel_between_steps() -> None:
    cancel = threading.Event()
    provider = FakeProvider([TextStep("第一段")], executor=Executor([]))
    cancel.set()
    result = await provider.run_agentic(_request(), RecordingSink(), cancel=cancel)
    assert result.status == "cancelled"


@pytest.mark.asyncio
async def test_fake_tool_step_without_executor_is_protocol_error() -> None:
    provider = FakeProvider([ToolStep("get_coverage", {"project_id": "cessna-172"})])
    with pytest.raises(ProviderError) as exc:
        await provider.run_agentic(
            _request(), RecordingSink(), cancel=threading.Event()
        )
    assert exc.value.kind == "protocol"


@pytest.mark.asyncio
async def test_fake_sets_executor_later_via_attribute() -> None:
    """RunDriver 以属性注入 executor（可插拔适配不改变 Provider 协议）。"""
    executor = Executor([ToolResult(ok=True, text="ok")])
    provider = FakeProvider(
        [ToolStep("get_coverage", {"project_id": "cessna-172"}, expect_text="ok")]
    )
    provider.executor = executor
    result = await provider.run_agentic(
        _request(), RecordingSink(), cancel=threading.Event()
    )
    assert result.tool_calls == 1


@pytest.mark.asyncio
async def test_fake_end_failed_status() -> None:
    provider = FakeProvider([TextStep("出错了"), EndStep("failed", "失败")])
    result = await provider.run_agentic(
        _request(), RecordingSink(), cancel=threading.Event()
    )
    assert result.status == "failed"
    assert result.error is None
