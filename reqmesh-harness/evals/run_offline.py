#!/usr/bin/env python3
"""P6 evals 离线 runner（零网络；spec p6-delivery.md 决策①/验收 2）。

- 5 个黄金任务 G1–G5（任务定义 = 数据，见 tasks.py）；退出码 0 即全绿；
- 全部隔离：每任务临时目录（审计/白名单/session/runs），respx 打桩 reqmesh HTTP，
  FakeProvider + registry 全链路（审批门/审计/白名单经既有实现，零复制裁决逻辑）；
- 断言只测外部行为：执行器实际调用 == 期望序列、写负载形状、审计行、读回响应；
- 本脚本不进 pytest 集合（spec 决策①；533 离线基线计数不变）；
- --selftest：runner 自身的顺序失配/参数失配/审计失配报错路径自证（最小夹具，
  零网络零注册表——spec「Testing Decisions」runner 单元级质量口径）。

用法（在 reqmesh-harness/ 下）：uv run python evals/run_offline.py [--task G1..G5] [--selftest]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import threading
from pathlib import Path

import respx

from reqmesh_harness.config import Settings
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.runtime.confirm import ConfirmationRelay, ConfirmedToolExecutor
from reqmesh_harness.runtime.fake import FakeProvider
from reqmesh_harness.runtime.loop import RunDriver, ToolExecutor
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import Runtime, set_runtime

from tasks import (
    ANY,
    BY_ID,
    EvalEnv,
    GOLDEN_TASKS,
    GoldenTask,
    matches,
)

_SESSION_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "session.json"


# ------------------------------------------------------------------ 记录 sink（工具序列断言数据源）
class RecordingSink:
    """事件记录：tool_call（name/args/ok/text 配对）+ question/turn_end（顺序断言用）。"""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.tool_records: list[dict | None] = []

    def on_text(self, text: str) -> None:
        self.events.append({"kind": "text", "text": text})

    def on_tool_call(self, name: str, args: dict) -> None:
        self.events.append({"kind": "tool_call", "name": name, "args": dict(args)})
        self.tool_records.append({"name": name, "args": dict(args), "ok": None, "text": None})

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.events.append({"kind": "tool_result", "name": name, "ok": bool(ok), "text": summary})
        if self.tool_records and self.tool_records[-1]["name"] == name:
            self.tool_records[-1]["ok"] = bool(ok)
            self.tool_records[-1]["text"] = summary

    def on_question(self, q) -> None:
        self.events.append({"kind": "question", "question": str(getattr(q, "question", q))})

    def on_turn_end(self, reason: str) -> None:
        self.events.append({"kind": "turn_end", "reason": reason})


# ------------------------------------------------------------------ 纯断言助手（selftest 同源）
def check_sequence(task: GoldenTask, tool_events: list[dict]) -> list[str]:
    """执行器实际调用（sink on_tool_call 序列）== 期望序列（name + args 子集匹配）。"""
    errors: list[str] = []
    expected = [c.name for c in task.expected_calls]
    actual = [e["name"] for e in tool_events]
    if actual != expected:
        errors.append(f"工具序列失配：期望 {expected}，实际 {actual}")
    for i, (ev, call) in enumerate(zip(tool_events, task.expected_calls)):
        for key, want in (call.args or {}).items():
            got = ev["args"].get(key)
            if not matches(want, got):
                errors.append(
                    f"第 {i} 次调用 {call.name} 参数 {key} 失配：期望 {want!r}，实际 {got!r}"
                )
    return errors


def check_audit(task: GoldenTask, rows: list[dict]) -> list[str]:
    """审计期望：决策序列 + tool/level/result 逐行 + version=1（P2 字段契约）。"""
    errors: list[str] = []
    expected = [(r.decision, r.tool) for r in task.audit]
    actual = [(r.get("decision"), r.get("tool")) for r in rows]
    if actual != expected:
        errors.append(f"审计行失配：期望 {expected}，实际 {actual}")
    for want in task.audit:
        row = next(
            (r for r in rows if r.get("decision") == want.decision and r.get("tool") == want.tool),
            None,
        )
        if row is None:
            errors.append(f"缺审计行：{want.decision}/{want.tool}")
            continue
        if want.level is not None and row.get("level") != want.level:
            errors.append(f"审计行 {want.tool} level 失配：期望 {want.level}，实际 {row.get('level')}")
        if want.result is not None and row.get("result") != want.result:
            errors.append(f"审计行 {want.tool} result 失配：期望 {want.result}，实际 {row.get('result')}")
        if row.get("version") != 1:
            errors.append(f"审计行 {want.tool} version 契约失配：{row.get('version')}")
    return errors


# ------------------------------------------------------------------ 单任务离线执行
async def execute_offline(task: GoldenTask) -> list[str]:
    """执行一个黄金任务；返回错误列表（空 = 全绿）。每任务独立临时目录 + respx 作用域。"""
    errors: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix=f"eval-{task.id}-"))
    settings = Settings(
        base_url="http://reqmesh.test",
        session_file=tmp / "session.json",
        approvals_file=tmp / "approvals.toml",
        audit_file=tmp / "audit.jsonl",
        runs_dir=tmp / "runs",
    )
    (tmp / "session.json").write_bytes(_SESSION_FIXTURE.read_bytes())
    set_runtime(Runtime(settings))

    try:
        # respx 作用域贯穿 驱动 + 最终状态断言（router.calls 须在块内采集——respx 退出清空）
        with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
            env = EvalEnv(router=router, settings=settings, registry=build_registry())
            try:
                task.setup(env)
            except Exception as exc:  # noqa: BLE001 - setup 失败 = 任务失败（记录原因）
                return [f"setup 失败: {type(exc).__name__}: {exc}"]

            try:
                driver = RunDriver(registry=env.registry, settings=settings)
                relay = None
                if task.run_confirmation:
                    relay = ConfirmationRelay(settings, auto_yes=True)
                    inner = ToolExecutor(registry=env.registry, settings=settings)
                    driver.executor_factory = lambda: ConfirmedToolExecutor(inner, relay)

                from reqmesh_harness.runtime.memory import LoggingSink, RunRecorder

                recorder = RunRecorder.create(settings.resolved_runs_dir())
                recorder.init_context(task=f"eval-{task.id}", project_context=None, provider="fake")
                recorder.record_task(f"P6 eval {task.id}（{task.capability}）")
                env.recorder = recorder

                sink = RecordingSink()
                env.sink = sink
                provider = FakeProvider(
                    list(task.steps),
                    question_answerer=relay.answer if relay is not None else None,
                )
                request = driver.assemble(
                    f"P6 eval {task.id}（{task.capability}）", project_context=None
                )
                run = await driver.drive(
                    provider,
                    request,
                    LoggingSink(recorder, sink),
                    cancel=threading.Event(),
                )
                recorder.record_done(
                    run.status, run.final_text, tool_calls=run.tool_calls, questions=run.questions
                )
                env.run = run
            except Exception as exc:  # noqa: BLE001 - 驱动异常 = 任务失败（含 FakeProvider 协议失配）
                return [f"run 驱动失败: {type(exc).__name__}: {exc}"]

            # ---- 通用断言：序列 / 审计
            tool_events = [e for e in sink.events if e["kind"] == "tool_call"]
            errors += check_sequence(task, tool_events)
            audit_rows = AuditLog(settings.resolved_audit_file()).read_all()
            errors += check_audit(task, audit_rows)
            # ---- 任务专属最终状态断言
            import traceback as _tb

            try:
                task.final_state(env)
            except AssertionError as exc:
                detail = str(exc)
                if not detail:
                    frame = _tb.extract_tb(exc.__traceback__)[-1]
                    detail = f"{Path(frame.filename).name}:{frame.lineno} {frame.line}"
                errors.append(f"最终状态断言失败: {detail}")
            except Exception as exc:  # noqa: BLE001 - 断言代码内部异常也归任务失败
                errors.append(f"最终状态断言异常: {type(exc).__name__}: {exc}")
    finally:
        set_runtime(None)
    return errors


def _run_one(task: GoldenTask) -> tuple[bool, list[str]]:
    errors = asyncio.run(execute_offline(task))
    return (not errors, errors)


# ------------------------------------------------------------------ selftest（runner 失配报错路径自证）
def selftest() -> list[str]:
    """最小夹具（零网络零注册表）：顺序失配/参数失配/审计失配/匹配器语义。"""
    failures: list[str] = []

    def expect(desc: str, result: list[str], want_err: bool) -> None:
        ok = (len(result) > 0) == want_err
        if not ok:
            failures.append(f"{desc}: 期望{'报错' if want_err else '通过'}，实际 {result}")

    task = GOLDEN_TASKS[0]  # G1 的期望序列为夹具
    good = [
        {"name": "draft_requirement", "args": {"project_id": "cessna-172", "id": "SMOKE-EVAL-P6-G1"}},
        {"name": "get_requirement_quality", "args": {"project_id": "cessna-172", "req_id": "SMOKE-EVAL-P6-G1"}},
        {"name": "get_requirement", "args": {"project_id": "cessna-172", "req_id": "SMOKE-EVAL-P6-G1"}},
    ]
    expect("顺序正确", check_sequence(task, good), False)
    bad_order = list(reversed(good))
    expect("顺序失配报错", check_sequence(task, bad_order), True)
    bad_args = [
        good[0],
        {"name": "get_requirement_quality", "args": {"project_id": "cesna-172", "req_id": "X"}},
        good[2],
    ]
    expect("参数失配报错", check_sequence(task, bad_args), True)
    expect("匹配器语义（ANY/字面量）", check_sequence(task, []), True)
    assert matches("x", "x") and matches(ANY, object()) and matches("1", 1) is False
    audit_rows = [
        {"decision": "approved", "tool": "draft_requirement", "level": "DRAFT", "result": "ok", "version": 1}
    ]
    expect("审计全对通过", check_audit(task, audit_rows), False)
    expect(
        "审计 decision 失配报错",
        check_audit(task, [{"decision": "denied", "tool": "draft_requirement", "version": 1}]),
        True,
    )
    expect(
        "审计 version 失配报错",
        check_audit(task, [{"decision": "approved", "tool": "draft_requirement", "version": 2}]),
        True,
    )
    return failures


# ------------------------------------------------------------------ main
def _fmt(errors: list[str]) -> str:
    return "; ".join(errors) if errors else "全部断言通过"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals/run_offline.py", description="P6 evals 离线 runner（零网络）")
    parser.add_argument("--task", default=None, choices=sorted(BY_ID), help="只跑单个任务（默认全部）")
    parser.add_argument("--selftest", action="store_true", help="runner 自身失配报错路径自证")
    args = parser.parse_args(argv)

    if args.selftest:
        failures = selftest()
        if failures:
            print("selftest 失败:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("selftest 通过（顺序/参数/审计失配报错路径 + 匹配器语义）")
        return 0

    tasks = [BY_ID[args.task]] if args.task else GOLDEN_TASKS
    results: list[tuple[GoldenTask, bool, list[str]]] = []
    for task in tasks:
        ok, errors = _run_one(task)
        results.append((task, ok, errors))
        mark = "✓" if ok else "✗"
        detail = _fmt(errors[:3]) if errors else "工具序列/审计/最终状态全部符合"
        print(f"{mark} {task.id}  {task.capability}\n    {detail}")
        for extra in errors[3:]:
            print(f"    - {extra}")
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\noffline evals: {passed}/{len(tasks)} 全绿" if passed == len(tasks) else f"\noffline evals: {passed}/{len(tasks)}")
    return 0 if passed == len(tasks) else 1


if __name__ == "__main__":
    sys.exit(main())
