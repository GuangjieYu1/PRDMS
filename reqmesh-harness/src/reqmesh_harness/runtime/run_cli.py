"""`reqmesh-harness run` CLI：内置运行时入口（spec ①；#40）。

- 参数：`run "<任务>" [--project P] [--provider dsh|openai|fake] [--resume RUN_ID]
  [--yes] [--show-reasoning] [--max-rounds N]`；
- 薄壳：解析 → 装配（project context/recorder/relay/provider）→ 流式渲染 → 退出码；
- project context：--project 显式优先；任务文本唯一命中项目 id → fail-fast 提示显式给出
  （不做启发式猜测）；无 → None（纯只读任务可用）；
- 三通道确认中继（④）：预先白名单（approvals CLI）> --yes 无头自动 > TTY 逐条 y/N；
- resume（⑤）：两分支——DSH 会话存活 → 沿用 sessionId（history 空）；失活 →
  run.jsonl 重建摘要注入（history 字段 + 明示来源）；
- TTY `/steer <文本>` → session.prompt(mode=steer)；仅指导注入，不承载审批裁决；
- 退出码：completed 0 / failed 非 0（1）/ cancelled 130；失败路径记录 run 日志 error 事件；
- run 结束打印审计摘要（读 REQMESH_AUDIT_FILE；本地文件，不向 agent 暴露——P2 契约）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
from typing import Callable, Sequence

from ..config import Settings, get_settings
from ..errors import HarnessError, InputParseError, ProviderError
from ..guardrails.audit import AuditLog
from ..tools import build_registry
from ..tools.registry import ToolRegistry
from .confirm import ConfirmationRelay, ConfirmedToolExecutor
from .dsh_provider import DshProvider, DshRpcClient
from .loop import RunDriver, ToolExecutor
from .memory import LoggingSink, RunRecorder, rebuild_summary
from .openai_provider import OpenAIProvider
from .provider import ProjectContext


class RenderingSink:
    """流式渲染：text 逐块 stdout；工具行摘要；问题行；结束行。reasoning 由 provider 折叠。"""

    def __init__(self, stream=None) -> None:
        self._stream = stream or sys.stdout

    def on_text(self, text: str) -> None:
        self._stream.write(text)
        self._stream.flush()

    def on_tool_call(self, name: str, args: dict) -> None:
        self._stream.write(f"\n[工具] {name}({_brief_args(args)})\n")
        self._stream.flush()

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        mark = "✓" if ok else "✗"
        self._stream.write(f"[结果] {mark} {name}：{str(summary)[:200]}\n")
        self._stream.flush()

    def on_question(self, q) -> None:
        self._stream.write(f"\n[提问] {q.question}\n")
        self._stream.flush()

    def on_turn_end(self, reason: str) -> None:
        self._stream.write(f"\n[结束] {reason}\n")
        self._stream.flush()


def _brief_args(args: dict) -> str:
    if not args:
        return ""
    return json.dumps(args, ensure_ascii=False, default=str)[:200]


def _exit_code(status: str) -> int:
    return {"completed": 0, "failed": 1, "cancelled": 130}.get(status, 1)


def _make_provider_factory(registry: ToolRegistry) -> Callable:
    """默认 provider 工厂：按 settings.provider 装配（dsh 默认 | openai；fake 仅库接口）。"""

    def factory(
        settings: Settings,
        *,
        registry: ToolRegistry | None = None,
        question_answerer=None,
        on_session=None,
        on_denied=None,
        warning=None,
        show_reasoning: bool = False,
        session_id: str | None = None,
        executor=None,
    ):
        registry = registry or build_registry()
        if settings.provider == "dsh":
            return DshProvider(
                settings,
                question_answerer=question_answerer,
                on_session=on_session,
                on_denied=on_denied,
                warning=warning,
                show_reasoning=show_reasoning,
                dsh_session_id=session_id,
            )
        if settings.provider == "openai":
            return OpenAIProvider(settings, registry=registry, executor=executor)
        raise ProviderError(
            "protocol",
            f"provider={settings.provider!r} 不支持（dsh|openai；fake 仅供库接口离线测试）",
        )

    return factory


def _default_live_check(settings: Settings) -> Callable[[str], bool]:
    client = DshRpcClient(settings.dsh_url)

    def check(session_id: str) -> bool:
        value = client.call("session.list", {})
        items = value.get("items") if isinstance(value, dict) else None
        return any(
            isinstance(i, dict) and i.get("sessionId") == session_id
            for i in (items or [])
        )

    return check


def run_main(
    argv: Sequence[str],
    *,
    provider_factory: Callable | None = None,
    session_live_check: Callable[[str], bool] | None = None,
    steer_input=None,
) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="reqmesh-harness run",
        description="内置运行时：以本地 DSH（默认）或 OpenAI 兼容 provider 驱动 P1–P4 工具完成任务",
    )
    parser.add_argument(
        "task",
        nargs="?",
        default="",
        help="自然语言任务（--resume 时可省略=继续原任务）",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="project context 的项目 id（显式给出，不做启发式猜测）",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["dsh", "openai", "fake"],
        help="provider（默认 REQMESH_PROVIDER=dsh）",
    )
    parser.add_argument(
        "--resume",
        default=None,
        metavar="RUN_ID",
        help="继续此前 run（两分支见 spec ⑤）",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="无头自动确认（denied → 自动维护白名单并重试）",
    )
    parser.add_argument(
        "--show-reasoning", action="store_true", help="展开推理增量（默认折叠）"
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=None,
        help="防御轮数上限（默认 REQMESH_DSH_MAX_ROUNDS=8）",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"provider": args.provider})
    if args.show_reasoning:
        settings = settings.model_copy(update={"show_reasoning": True})
    if settings.provider == "fake":
        print(
            "错误: --provider fake 仅供库接口离线测试（需脚本化 FakeProvider 步骤）；"
            "CLI 可用 dsh（默认）或 openai",
            file=sys.stderr,
        )
        return 2
    factory = provider_factory or _make_provider_factory(build_registry())
    registry = build_registry()
    runs_root = settings.resolved_runs_dir()
    warn = lambda text: print(text, file=sys.stderr)  # noqa: E731

    # ------------------------------------------------------------------ project context
    try:
        project_context = _resolve_project_context(
            args.task, registry, settings, explicit=args.project
        )
    except HarnessError as exc:
        return _fail(exc, code=2 if isinstance(exc, InputParseError) else 1)

    # ------------------------------------------------------------------ resume
    resumed_dir: Path | None = None
    old_recorder: RunRecorder | None = None
    if args.resume:
        resumed_dir = RunRecorder.lookup(runs_root, args.resume)
        if resumed_dir is None:
            print(
                f"错误: run {args.resume} 不存在于 {runs_root}（--resume 需完整 run-id）",
                file=sys.stderr,
            )
            return 2
        old_recorder = RunRecorder(resumed_dir)
        ctx = old_recorder.read_context() or {}
        if not args.provider:
            settings = settings.model_copy(
                update={"provider": ctx.get("provider", "dsh")}
            )
        if project_context is None and isinstance(ctx.get("project_context"), dict):
            pc = ctx["project_context"]
            project_context = ProjectContext(
                project_id=str(pc.get("project_id", "")),
                base_url=str(pc.get("base_url", "")),
                created_at=str(pc.get("created_at", "")),
            )
        if not args.task:
            args.task = str(ctx.get("task", ""))
    if not args.task:
        print(
            "错误: 未提供任务文本（任务为空；--resume 时可省略以继续原任务）",
            file=sys.stderr,
        )
        return 2

    # ------------------------------------------------------------------ recorder / relay
    recorder = (
        old_recorder.create_resume()
        if old_recorder is not None
        else RunRecorder.create(runs_root)
    )
    recorder.init_context(
        task=args.task,
        project_context=project_context,
        provider=settings.provider,
        resumed_from=args.resume,
    )
    recorder.record_task(args.task)
    relay = ConfirmationRelay(settings, auto_yes=bool(args.yes), warning=warn)

    # ------------------------------------------------------------------ resume 历史分支
    history: list[dict[str, str]] = []
    dsh_session_id: str | None = None
    if args.resume and settings.provider == "dsh" and old_recorder is not None:
        old_session_id = old_recorder.read_dsh_session()
        if old_session_id:
            check = session_live_check or _default_live_check(settings)
            if check(old_session_id):
                dsh_session_id = old_session_id  # 分支①：沿用 DSH 会话（原生历史）
            else:
                history = [
                    {"role": "user", "content": rebuild_summary(resumed_dir)}
                ]  # 分支②
        else:
            history = [{"role": "user", "content": rebuild_summary(resumed_dir)}]

    # ------------------------------------------------------------------ provider / run
    driver = RunDriver(registry=registry, settings=settings)
    inner_executor = ToolExecutor(registry=registry, settings=settings)
    driver.executor_factory = lambda: ConfirmedToolExecutor(inner_executor, relay)
    provider = factory(
        settings,
        registry=registry,
        question_answerer=relay.answer,
        on_session=recorder.save_dsh_session,
        on_denied=relay.on_denied,
        warning=warn,
        show_reasoning=settings.show_reasoning,
        session_id=dsh_session_id,
    )
    request = driver.assemble(
        args.task,
        project_context=project_context,
        history=history,
        max_rounds=(
            args.max_rounds if args.max_rounds is not None else settings.dsh_max_rounds
        ),
    )
    sink = LoggingSink(recorder, RenderingSink())
    cancel = threading.Event()
    stop_steer = threading.Event()
    steer_thread: threading.Thread | None = None
    if hasattr(provider, "steer"):
        input_stream = steer_input if steer_input is not None else sys.stdin
        steer_thread = threading.Thread(
            target=_steer_loop, args=(provider, input_stream, stop_steer), daemon=True
        )
        steer_thread.start()
    try:
        try:
            result = asyncio.run(driver.drive(provider, request, sink, cancel=cancel))
        except KeyboardInterrupt:
            cancel.set()
            if hasattr(provider, "cancel_remote"):
                provider.cancel_remote()
            print("\n已取消（Ctrl-C）", file=sys.stderr)
            return 130
        except (ProviderError, HarnessError) as exc:
            recorder.record_error(getattr(exc, "kind", type(exc).__name__), str(exc))
            return _fail(exc, code=1)
    finally:
        stop_steer.set()
        if steer_thread is not None:
            steer_thread.join(timeout=1.0)
    recorder.record_done(
        result.status,
        result.final_text,
        tool_calls=result.tool_calls,
        questions=result.questions,
    )
    print(
        f"\n[最后] 状态={result.status}；工具调用 {result.tool_calls} 次；问题 {result.questions} 个"
    )
    _print_audit_summary(settings)
    return _exit_code(result.status)


def _resolve_project_context(
    task: str, registry: ToolRegistry, settings: Settings, *, explicit: str | None
) -> ProjectContext | None:
    """project context 解析：--project 显式优先；唯一命中 → fail-fast；无 → None。"""
    if explicit:
        detail = registry.call("list_projects", project_id=explicit)
        if not isinstance(detail, dict):
            raise InputParseError(
                f"项目 {explicit} 不存在（list_projects 响应形状未知）"
            )
        return ProjectContext(
            project_id=str(detail.get("id", explicit)),
            base_url=settings.base_url,
            created_at=str(detail.get("created_at") or detail.get("created") or ""),
        )
    hit = _detect_project_mention(task, registry)
    if hit is not None:
        raise InputParseError(
            f"任务文本包含项目 id {hit!r}，但未显式给出 --project；"
            "请以 --project {id} 显式指定（不做启发式猜测，fail-fast）。"
        )
    return None


def _detect_project_mention(task: str, registry: ToolRegistry) -> str | None:
    """任务文本中的项目 id 唯一命中检测（无凭据/不可达 → None=跳过检测）。"""
    try:
        projects = registry.call("list_projects")
    except HarnessError:
        return None
    ids = [str(p["id"]) for p in projects if isinstance(p, dict) and p.get("id")]
    hits = [pid for pid in ids if pid in task]
    return hits[0] if len(hits) == 1 else None


def _fail(exc: Exception, *, code: int) -> int:
    print(f"错误: {exc}", file=sys.stderr)
    return code


def _print_audit_summary(settings: Settings) -> None:
    """run 结束审计摘要（本地文件；不向 agent 暴露审计内容——P2 契约）。"""
    path = settings.resolved_audit_file()
    try:
        lines = AuditLog(path).read_all()
    except (OSError, ValueError) as exc:
        print(f"审计摘要：读取失败（{path}）: {exc}", file=sys.stderr)
        return
    denied = sum(1 for l in lines if l.get("decision") == "denied")
    approved = sum(1 for l in lines if l.get("decision") == "approved")
    tools = sorted({str(l.get("tool", "")) for l in lines})
    print(
        f"审计摘要（{path}）：共 {len(lines)} 行；denied {denied}；approved {approved}；"
        f"写尝试工具：{'、'.join(tools) if tools else '（无）'}"
    )


def _steer_loop(provider, input_stream, stop: threading.Event) -> None:
    """TTY steer 读取线程：行首 `/steer ` → provider.steer；其余行忽略。"""
    for line in iter(input_stream.readline, ""):
        if stop.is_set():
            return
        line = line.strip()
        if line.startswith("/steer"):
            text = line[len("/steer") :].strip()
            if text:
                try:
                    provider.steer(text)
                except ProviderError as exc:
                    print(f"steer 失败: {exc}", file=sys.stderr)


__all__ = ["RenderingSink", "run_main", "_exit_code"]
