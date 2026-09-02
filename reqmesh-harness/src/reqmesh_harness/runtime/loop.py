"""P5 loop 内核：任务指令组装（②）、compose_prompt（DSH 首条 content）、自驱 executor、RunDriver。

- 指令模板内容为契约（spec ②「工具清单进指令」+三条规则+轮次约束），测试断言关键句；
- executor：registry.call 执行（门/审计/dry-run 全链路复用，零复制），HarnessError →
  工具错误文本（ApprovalDeniedError 文本含 fix_hint，与 DSH 侧 MCP tool error 同形态）；
  未知工具名 → ProviderError(protocol)；`mcp__reqmesh__` 前缀剥除后查找；
- RunDriver：tool-loop provider 注入 executor（属性赋值，不改 Provider 协议）；两执行所有权
  分支都经同一 StreamSink 输出（delegated 由 provider 内部闭环，harness 只做流式中继）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable

from ..config import Settings, get_settings
from ..errors import HarnessError, ProviderError
from ..tools import build_registry
from ..tools.registry import ToolRegistry
from .provider import (
    MAX_ROUNDS_DEFAULT,
    AgentRequest,
    ProjectContext,
    RunResult,
    StreamSink,
    ToolHint,
    ToolResult,
)

_DSH_TOOL_PREFIX = "mcp__reqmesh__"

_RULES = (
    "规则：\n"
    "① 只允许调用 mcp__reqmesh__* 工具完成本任务，不得使用 bash/文件工具修改任何文件；\n"
    "② 写工具被审批门拒绝时（错误含 `approvals add` 修复建议），用提问机制向用户确认是否批准，"
    "得到批准后重试一次；用户拒绝则放弃该写操作并在最终总结中说明；\n"
    "③ 最终总结须列出你调用过的工具名与关键结果。"
)


def is_denied_error(text: str) -> bool:
    """denied 判定单一来源（ApprovalDeniedError 文本嗅探；P2 错误形状 == 工具错误文本）。

    DSH 侧工具结果帧与自驱 executor 回灌文本同形态（spec ④/⑦），两处判定都走这里。
    """
    return "ApprovalDeniedError" in text or "审批门拒绝" in text


def first_line(text: str) -> str:
    line = text.strip().splitlines()
    return line[0] if line else ""


def tool_hints(registry: ToolRegistry) -> list[ToolHint]:
    return [
        ToolHint(
            name=spec.name, description=first_line(spec.description), level=spec.level
        )
        for spec in registry.all()
    ]


def assemble_request(
    task: str,
    *,
    project_context: ProjectContext | None,
    history: list[dict[str, str]] | None = None,
    registry: ToolRegistry | None = None,
    max_rounds: int | None = None,
) -> AgentRequest:
    """AgentRequest 快照：任务 + project context + 内存摘要 + 注册表派生工具清单。"""
    registry = registry or build_registry()
    request = AgentRequest(
        task=task,
        project_context=project_context,
        history=list(history or []),
        tools=tool_hints(registry),
        max_rounds=max_rounds if max_rounds is not None else MAX_ROUNDS_DEFAULT,
    )
    return request


def build_task_instruction(request: AgentRequest) -> str:
    """任务指令（DSH 委托路线内容契约，spec ②；测试断言关键句）。"""
    ctx = request.project_context
    if ctx is None:
        ctx_line = "未指定 project context（纯只读任务或未显式 --project 的任务）"
    else:
        ctx_line = (
            f"project context：project_id={ctx.project_id} base_url={ctx.base_url} "
            f"created_at={ctx.created_at}"
        )
    tool_lines = "\n".join(
        f"- mcp__reqmesh__{h.name}：{h.description}（{h.level} 层）"
        for h in request.tools
    )
    return (
        "你是 reqmesh-harness 的内置 agent，运行任务由 harness 委派。\n"
        f"{ctx_line}\n"
        f"可用工具仅限 `mcp__reqmesh__*`（清单：\n{tool_lines}\n共 {len(request.tools)} 个）。\n"
        f"{_RULES}\n"
        f"本任务最多进行 {request.max_rounds} 轮（防御上限：超出后停止并总结）。"
    )


def compose_prompt(request: AgentRequest) -> str:
    """DSH 首条 user content：指令 + 历史摘要（resume 重建注入，明示来源）+ 任务。"""
    parts = [build_task_instruction(request)]
    if request.history:
        history_lines = "\n".join(
            f"- {item.get('role', 'user')}：{str(item.get('content', ''))[:800]}"
            for item in request.history
        )
        parts.append(
            f"此前进展（历史由 harness 内存重建，非本次 DSH 会话历史）：\n{history_lines}"
        )
    parts.append(f"任务：{request.task}")
    return "\n\n".join(parts)


@dataclass(frozen=True)
class ToolExecutor:
    """自驱 executor 契约：`(name, args, project_context) -> ToolResult`（spec ③ ⑦）。"""

    registry: ToolRegistry | None = None
    settings: Settings | None = None

    def __call__(
        self, name: str, args: dict[str, Any], project_context: ProjectContext | None
    ) -> ToolResult:
        registry = self.registry or build_registry()
        raw = (
            name[len(_DSH_TOOL_PREFIX) :] if name.startswith(_DSH_TOOL_PREFIX) else name
        )
        try:
            registry.get(raw)
        except KeyError:
            raise ProviderError(
                "protocol",
                f"未知工具名: {name}（注册表无 {raw!r}；只允许 mcp__reqmesh__*）",
            ) from None
        try:
            value = registry.call(raw, **args)
            return ToolResult(ok=True, text=_render_result(value))
        except HarnessError as exc:
            return ToolResult(ok=False, text=f"{type(exc).__name__}: {exc}")


def _render_result(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text[:8000]


class RunDriver:
    """一次 run 的编排：任务指令组装 → provider 驱动 → 结果归一；tool-loop 注入 executor。

    `executor_factory`：run 层可注入确认中继包装（ConfirmedToolExecutor）等；None 时
    使用默认 ToolExecutor（registry.call 全链路）。
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        settings: Settings | None = None,
        *,
        executor_factory: Callable[[], ToolExecutor] | None = None,
    ) -> None:
        self.registry = registry or build_registry()
        self.settings = settings or get_settings()
        self.executor_factory = executor_factory

    def assemble(
        self,
        task: str,
        *,
        project_context: ProjectContext | None,
        history: list[dict[str, str]] | None = None,
        max_rounds: int | None = None,
    ) -> AgentRequest:
        return assemble_request(
            task,
            project_context=project_context,
            history=history,
            registry=self.registry,
            max_rounds=max_rounds,
        )

    def executor(self) -> ToolExecutor:
        return ToolExecutor(registry=self.registry, settings=self.settings)

    async def drive(
        self,
        provider,
        request: AgentRequest,
        sink: StreamSink,
        *,
        cancel: threading.Event | None = None,
    ) -> RunResult:
        if (
            provider.execution == "tool-loop"
            and getattr(provider, "executor", None) is None
        ):
            provider.executor = (
                self.executor_factory()
                if self.executor_factory is not None
                else ToolExecutor(registry=self.registry, settings=self.settings)
            )
        return await provider.run_agentic(
            request, sink, cancel=cancel or threading.Event()
        )


async def run_task(
    task: str,
    *,
    provider,
    project_context: ProjectContext | None = None,
    history: list[dict[str, str]] | None = None,
    max_rounds: int | None = None,
    registry: ToolRegistry | None = None,
    settings: Settings | None = None,
    sink: StreamSink | None = None,
    cancel: threading.Event | None = None,
) -> RunResult:
    """库接口（spec ①）：RUN 编排入口——FakeProvider 离线测试与嵌入方走这里。"""
    driver = RunDriver(registry=registry, settings=settings)
    request = driver.assemble(
        task, project_context=project_context, history=history, max_rounds=max_rounds
    )
    return await driver.drive(provider, request, sink or _NullSink(), cancel=cancel)


class _NullSink:
    """无渲染 sink（库接口默认：只做驱动，不输出）。"""

    def on_text(self, text: str) -> None: ...

    def on_tool_call(self, name: str, args: dict) -> None: ...

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None: ...

    def on_question(self, q) -> None: ...

    def on_turn_end(self, reason: str) -> None: ...


__all__ = [
    "RunDriver",
    "ToolExecutor",
    "assemble_request",
    "is_denied_error",
    "build_task_instruction",
    "compose_prompt",
    "first_line",
    "run_task",
    "tool_hints",
]
