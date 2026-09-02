"""FakeProvider：脚本化 turn 序列（离线测试资产；无网络、无随机，spec ③）。

- 脚本 = 顺序步骤序列（Text/Tool/Question/End），每步确定的下一状态；
- 工具步骤：`sink.on_tool_call` → executor（registry.call 回灌）→ `sink.on_tool_result`；
  回灌结果与步骤期望（ok/text）失配 → AssertionError 归一为 ProviderError(protocol)——
  「含工具调用序列断言」落在此处（验收 2）；
- 问题步骤：`sink.on_question` 通知 + 注入的 `question_answerer` 被调用（问题应答）；
- 取消：步骤间检查 `cancel`，置位即返回 RunResult(cancelled)；
- executor 经属性注入（RunDriver 对 tool-loop provider 统一注入，不改 Provider 协议）。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from ..errors import ProviderError
from .provider import (
    AgentRequest,
    ProjectContext,
    Question,
    RunResult,
    StreamSink,
    ToolResult,
)

Answerer = Callable[[Question], str]
Executor = Callable[[str, dict[str, Any], ProjectContext | None], ToolResult]


@dataclass(frozen=True)
class TextStep:
    text: str


@dataclass(frozen=True)
class ToolStep:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    expect_ok: bool = True
    expect_text: str | None = None  # None = 只断言 ok


@dataclass(frozen=True)
class QuestionStep:
    question: Question


@dataclass(frozen=True)
class EndStep:
    status: Literal["completed", "failed", "cancelled"] = "completed"
    final_text: str = ""


FakeStep = TextStep | ToolStep | QuestionStep | EndStep


def _deny_answerer(q: Question) -> str:
    return f"（FakeProvider 未注入 question_answerer，按拒绝处理：{q.question}）"


class FakeProvider:
    name = "fake"
    execution = "tool-loop"

    def __init__(
        self,
        steps: list[FakeStep],
        *,
        executor: Executor | None = None,
        question_answerer: Answerer | None = None,
    ) -> None:
        self._steps = list(steps)
        self.executor = executor
        self._answerer = question_answerer or _deny_answerer

    async def run_agentic(
        self, request: AgentRequest, sink: StreamSink, *, cancel: threading.Event
    ) -> RunResult:
        texts: list[str] = []
        tool_calls = 0
        questions = 0
        try:
            for step in self._steps:
                if cancel.is_set():
                    return RunResult(
                        "cancelled", "".join(texts), tool_calls, questions, None
                    )
                if isinstance(step, TextStep):
                    sink.on_text(step.text)
                    texts.append(step.text)
                elif isinstance(step, QuestionStep):
                    sink.on_question(step.question)
                    self._answerer(step.question)
                    questions += 1
                elif isinstance(step, ToolStep):
                    if self.executor is None:
                        raise ProviderError(
                            "protocol",
                            "FakeProvider 工具步骤未注入 executor（自驱执行契约缺失）",
                        )
                    sink.on_tool_call(step.name, dict(step.args))
                    result = self.executor(
                        step.name, dict(step.args), request.project_context
                    )
                    sink.on_tool_result(step.name, result.ok, result.text)
                    tool_calls += 1
                    if result.ok != step.expect_ok or (
                        step.expect_text is not None and result.text != step.expect_text
                    ):
                        raise AssertionError(
                            f"工具 {step.name} 回灌结果失配：期望 ok={step.expect_ok} "
                            f"text={step.expect_text!r}，实际 ok={result.ok} text={result.text!r}"
                        )
                elif isinstance(step, EndStep):
                    sink.on_turn_end(step.status)
                    final = step.final_text or "".join(texts)
                    return RunResult(step.status, final, tool_calls, questions, None)
            return RunResult("completed", "".join(texts), tool_calls, questions, None)
        except AssertionError as exc:
            raise ProviderError(
                "protocol", f"FakeProvider 脚本断言失败: {exc}"
            ) from exc


__all__ = [
    "EndStep",
    "FakeProvider",
    "FakeStep",
    "QuestionStep",
    "TextStep",
    "ToolStep",
]
