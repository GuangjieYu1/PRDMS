"""P5 provider 契约（runtime 包核心抽象）：工具层与 provider 解耦（ADR-0001 Consequences）。

- `Execution`：执行所有权——`delegated`（DSH：provider 全权执行工具并在会话内闭环，
  harness 只做指令装配/流式中继/审批确认/完成判定）vs `tool-loop`（openai/fake：
  provider 产出文本与 tool_calls，由 harness 自驱 executor 经 registry.call 执行并回灌）；
- 全部为本包的类型契约（纯数据 + Protocol）；任何 provider 实现（DSH/OpenAI/Fake）
  的异常一律归一为 `ProviderError`（errors.py），run CLI 只处理该族与既有 HarnessError；
- 术语（CONTEXT.md）：provider 无「会话」概念；DSH 宿主侧会话一律称「DSH session」。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..errors import ProviderError

Execution = Literal["delegated", "tool-loop"]
RunStatus = Literal["completed", "failed", "cancelled"]

MAX_ROUNDS_DEFAULT = (
    8  # 防御上限（spec ③）：DSH 委托路线写入指令、tool-loop 路线由内核兜底
)


@dataclass(frozen=True)
class ProjectContext:
    """运行时会话锚定的 reqmesh 项目（project context，CONTEXT.md 词表）。"""

    project_id: str
    base_url: str
    created_at: str


@dataclass(frozen=True)
class ToolHint:
    """工具提示行：注册表名（DSH 路线映射为 mcp__reqmesh__<name>）+ description 首行 + 层级。"""

    name: str
    description: str
    level: str


@dataclass(frozen=True)
class AgentRequest:
    """一次 provider 驱动的请求快照（任务 + project context + 内存摘要 + 工具清单）。"""

    task: str
    project_context: ProjectContext | None
    history: list[dict[str, str]]  # 会话内存摘要（resume 重建/DSH 会话自带历史时为空）
    tools: list[ToolHint]
    max_rounds: int = MAX_ROUNDS_DEFAULT


@dataclass(frozen=True)
class QuestionOption:
    label: str
    description: str | None = None


@dataclass(frozen=True)
class Question:
    """agent 提问（DSH question/requested 帧 / 脚本化问题）；id = 帧 rpcId（应答定位）。"""

    id: str
    question: str
    header: str | None = None
    detail: str | None = None
    options: tuple[QuestionOption, ...] = ()
    multi_select: bool = False


@dataclass(frozen=True)
class ToolResult:
    """自驱 executor 回灌结果（executor 契约；文本与 DSH 侧 MCP tool error 同形态）。"""

    ok: bool
    text: str


@dataclass(frozen=True)
class ToolCallRequest:
    """provider 产出的工具调用请求（tool-loop 路线的中间产物）。"""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class RunResult:
    """一次 run 的归一结果。"""

    status: RunStatus
    final_text: str
    tool_calls: int
    questions: int
    error: ProviderError | None


class StreamSink(Protocol):
    """流式回调（CLI 渲染与测试断言共用；全部同步调用，由 provider 异步循环触发）。"""

    def on_text(self, text: str) -> None: ...

    def on_tool_call(self, name: str, args: dict) -> None: ...

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None: ...

    def on_question(self, q: Question) -> None: ...  # 审批/问题中继入口（spec ④）

    def on_turn_end(self, reason: str) -> None: ...


class Provider(Protocol):
    """可插拔 provider 契约。

    `cancel`：threading.Event——运行方（run CLI Ctrl-C / 测试）置位后 provider 应尽快
    中止（DSH 路线调 session.cancel；tool-loop 路线停止取新步）并返回 cancelled。
    """

    name: str
    execution: Execution  # 执行所有权（delegated = DSH；tool-loop = openai/fake）

    async def run_agentic(
        self, request: AgentRequest, sink: StreamSink, *, cancel: threading.Event
    ) -> RunResult: ...


__all__ = [
    "AgentRequest",
    "Execution",
    "MAX_ROUNDS_DEFAULT",
    "ProjectContext",
    "Provider",
    "Question",
    "QuestionOption",
    "RunResult",
    "RunStatus",
    "StreamSink",
    "ToolCallRequest",
    "ToolHint",
    "ToolResult",
]
