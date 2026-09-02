"""P5 内置运行时包：provider 契约、会话内存、DSH 适配器、loop 内核、确认中继、CLI。

对外入口（库接口）：
- `run_task(...)`——一次 run 的编排入口（任务指令组装 → provider 驱动 → 结果归一）；
- 类型：AgentRequest/RunResult/StreamSink/Provider/ProjectContext/ToolHint/Question/…。
"""

from .fake import EndStep, FakeProvider, FakeStep, QuestionStep, TextStep, ToolStep
from .provider import (
    AgentRequest,
    MAX_ROUNDS_DEFAULT,
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

__all__ = [
    "AgentRequest",
    "EndStep",
    "FakeProvider",
    "FakeStep",
    "MAX_ROUNDS_DEFAULT",
    "ProjectContext",
    "Provider",
    "Question",
    "QuestionOption",
    "QuestionStep",
    "RunResult",
    "StreamSink",
    "TextStep",
    "ToolCallRequest",
    "ToolHint",
    "ToolResult",
    "ToolStep",
    "run_task",
]


def run_task(*args, **kwargs):  # 延迟导入避免 loop 未就绪时的循环导入
    from .loop import run_task as _run_task

    return _run_task(*args, **kwargs)
