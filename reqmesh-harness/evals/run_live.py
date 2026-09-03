#!/usr/bin/env python3
"""P6 evals live runner（network-tagged，不进默认 pytest 集合；spec p6-delivery.md 决策①/验收 3）。

- 前置：DSH web profile 已注册 mcp__reqmesh__* 40 工具（cordis.patch.yml 含 `- id: mcp-reqmesh`
  条目，spec 决策③——与 smoke_p5 B 段同前置）；凭据经环境变量/.env（Settings，.env 不落盘）；
- G1–G4 经 DSH 委托路线（DshProvider + RunDriver + ConfirmationRelay）逐任务驱动：
  写工具 denied → 确认中继（G1/G3 自动批准重试；G4 明确拒绝）→ approved；事件流工具序列断言；
- 审计 = 共享 XDG 文件基线差口径（P2 version=1，与 P5 B 段同口径）；G1/G3 残渣
  SMOKE-EVAL-P6-* 入残渣清单；G2 全 READ 零残渣；G4 denied 落库零行无残渣；
- 前置未满足：记录「待前置后执行」（与 P5 B 段同款），不做任何写操作；
- 记录落盘 docs/smoke/P6-cessna-172.md（REQMESH_SMOKE_OUT 可覆盖）：时间戳/实例/
  DSH URL/每步结果/残渣/前置状态/实测偏差。

用法（在 reqmesh-harness/ 下）：uv run python evals/run_live.py [--task G1..G4]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from reqmesh_harness.config import Settings
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.runtime.confirm import ConfirmationRelay
from reqmesh_harness.runtime.dsh_provider import DshProvider
from reqmesh_harness.runtime.loop import RunDriver
from reqmesh_harness.runtime.memory import LoggingSink, RunRecorder
from reqmesh_harness.tools import build_registry

from run_offline import RecordingSink
from tasks import EvalEnv, LIVE_TASKS, PROJECT_ID, GoldenTask

PATCH_PATH = Path("/home/user/.dsh/profiles/web/cordis.patch.yml")
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P6-cessna-172.md"


# ------------------------------------------------------------------ 部署前置
def prerequisite_satisfied() -> tuple[bool, str]:
    """DSH 注册前置：patch 文件存在且含 mcp-reqmesh 条目（spec 决策③ 注册条目定稿口径）。"""
    if not PATCH_PATH.exists():
        return False, f"{PATCH_PATH} 不存在（web profile patch 层缺失）"
    text = PATCH_PATH.read_text(encoding="utf-8")
    if "- id: mcp-reqmesh" in text:
        return True, "mcp-reqmesh 条目已存在"
    return False, f"{PATCH_PATH} 无 mcp-reqmesh 条目（注册属操作员维护窗口，spec 决策③；脚本 scripts/dsh_register.sh）"


class _FrameCounterWs:
    """WS 包装：透传连接并统计帧（记录用；与 smoke_p5 同口径但更轻）。"""

    def __init__(self, inner, counts: dict) -> None:
        self._inner = inner
        self._counts = counts

    async def __aenter__(self):
        self._conn = await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner.__aexit__(*exc)

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        from reqmesh_harness.runtime.dsh_provider import parse_frame

        sid = self._counts.get("session_id")
        async for raw in self._conn:
            try:
                frame = parse_frame(raw)
            except Exception:  # noqa: BLE001 — 计数器不因解析失败中断
                frame = None
            if frame is None:
                continue
            if sid is None or frame.session_id is None or frame.session_id == sid:
                self._counts["frames"][frame.kind] = self._counts["frames"].get(frame.kind, 0) + 1
                if frame.kind == "session/event":
                    etype = (frame.payload.get("event") or {}).get("type")
                    self._counts["events"][etype] = self._counts["events"].get(etype, 0) + 1
            yield raw

    async def close(self) -> None:
        pass


def _counter_factory(counts: dict):
    def factory(url: str):
        import websockets

        counts["ws_opens"] = counts.get("ws_opens", 0) + 1
        return _FrameCounterWs(websockets.connect(url), counts)

    return factory


# ------------------------------------------------------------------ 单任务 live 驱动
async def run_live_task(task: GoldenTask, settings: Settings, counts: dict) -> dict:
    """执行一个 live 任务（G1–G4）；返回记录信息（序列/残渣/审计 delta/结果）。"""
    audit = AuditLog(settings.resolved_audit_file())
    audit_before = len(audit.read_all())
    approvals_path = settings.resolved_approvals_file()
    digits_before = approvals_path.read_bytes() if approvals_path.exists() else None

    # G4 拒绝通道：auto_yes=False + 确认输入恒 N；其余 G1/G3 自动批准重试（与 smoke_p5 B 同款）
    auto_yes = task.id != "G4"
    relay = ConfirmationRelay(
        settings, auto_yes=auto_yes, confirm_reader=lambda prompt: "n" if not auto_yes else "y"
    )

    tmp = Path(tempfile.mkdtemp(prefix=f"eval-live-{task.id}-"))
    registry = build_registry()
    env = EvalEnv(settings=settings, registry=registry, dsh_url=settings.dsh_url, dsh_counts=counts)
    env.db["total_before"] = registry.call("list_requirements", project_id=PROJECT_ID, limit=1)["total"]

    recorder = RunRecorder.create(tmp / "runs")
    recorder.init_context(task=task.live_task, project_context=None, provider="dsh")
    recorder.record_task(f"P6 eval live {task.id}")
    env.recorder = recorder

    sink = RecordingSink()
    env.sink = sink

    def on_session(session_id: str) -> None:
        env.dsh_session_ids.append(session_id)
        counts["session_id"] = session_id

    driver = RunDriver(registry=registry, settings=settings)
    provider = DshProvider(
        settings,
        ws_factory=_counter_factory(counts),
        on_session=on_session,
        question_answerer=relay.answer,
        on_denied=relay.on_denied,
        warning=lambda text: print(f"警告: {text}", file=sys.stderr),
        poll_interval=0.3,
    )
    result = await driver.drive(
        provider,
        driver.assemble(task.live_task, project_context=None, max_rounds=settings.dsh_max_rounds),
        LoggingSink(recorder, sink),
        cancel=threading.Event(),
    )
    recorder.record_done(result.status, result.final_text, tool_calls=result.tool_calls, questions=result.questions)
    env.run = result

    # ---- live 通用断言
    errors: list[str] = []
    if result.status != "completed":
        errors.append(f"run 状态 {result.status} != completed")
    # 审计 delta：任务工具行（共享 XDG 文件：并发安全口径 = 精确序列断言——与 P5 B 段同口径）
    delta = audit.read_all()[audit_before:]
    expected = [(r.decision, r.tool) for r in task.live_audit]
    actual = [(r.get("decision"), r.get("tool")) for r in delta]
    if actual != expected:
        errors.append(f"审计 delta 失配：期望 {expected}，实际 {actual}")
    # 工具序列：期望名称逐一出现（DSH agent 调用次序详情由任务专属断言把关）
    calls = [e["name"] for e in sink.events if e["kind"] == "tool_call"]
    for name in task.live_expected_names:
        if name not in calls:
            errors.append(f"工具序列缺 {name}：实际 {calls}")
    # 白名单未被 G4 修改（确认通道拒绝 + 无 append）
    if task.id == "G4":
        digits_after = approvals_path.read_bytes() if approvals_path.exists() else None
        if digits_after != digits_before:
            errors.append("G4 白名单文件被修改（拒绝通道不应 append）")

    # ---- 任务专属 live 断言
    if task.live_final_state is not None:
        try:
            task.live_final_state(env)
        except AssertionError as exc:
            errors.append(f"live 最终状态断言失败: {exc}")
    total_after = None
    try:
        total_after = registry.call("list_requirements", project_id=PROJECT_ID, limit=1)["total"]
    except Exception:  # noqa: BLE001 — 记录信息尽力而为
        pass
    return {
        "task": task.id,
        "errors": errors,
        "calls": calls,
        "audit_delta": actual,
        "residue": list(task.live_residue),
        "dsn_sessions": list(env.dsh_session_ids),
        "status": result.status,
        "final_text": result.final_text[:200],
        "total_after": total_after,
    }


def _run_live_sequence(settings: Settings, counts: dict, task_ids: list[str]) -> dict[str, dict]:
    async def go() -> dict[str, dict]:
        infos = {}
        for task in [t for t in LIVE_TASKS if t.id in task_ids]:
            counts["session_id"] = None
            try:
                infos[task.id] = await run_live_task(task, settings, counts)
            except Exception as exc:  # noqa: BLE001 - 每任务独立记录
                infos[task.id] = {
                    "task": task.id,
                    "errors": [f"run 异常: {type(exc).__name__}: {exc}"],
                    "calls": [],
                    "audit_delta": [],
                    "residue": [],
                    "dsn_sessions": [],
                    "status": "exception",
                    "final_text": "",
                    "total_after": None,
                }
        return infos

    return asyncio.run(go())


# ------------------------------------------------------------------ 记录
PATCH_PRESENT = PATCH_PATH.exists()

def _write_record(out_path: Path, settings: Settings, steps: list, counts: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows = "\n".join(
        f"| {name} | ok | {detail} |" if status is True else f"| {name} | {status} | {detail} |"
        for name, status, detail in steps
    )
    frame_table = "\n".join(f"| {k} | {v} |" for k, v in sorted(counts.get("frames", {}).items())) or "| （无帧） | 0 |"
    event_table = "\n".join(f"| {k} | {v} |" for k, v in sorted(counts.get("events", {}).items())) or "| （无事件） | 0 |"
    patch_note = "mcp-reqmesh 条目已存在" if (PATCH_PRESENT and "- id: mcp-reqmesh" in PATCH_PATH.read_text(encoding="utf-8")) else "无 mcp-reqmesh 条目（待操作员维护窗口注册）"
    out_path.write_text(
        f"""# P6 cessna-172 冒烟/evals live 记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- DSH 宿主：{settings.dsh_url}（loopback RPC + WS events.mux）
- 项目：cessna-172
- 结果：详见「步骤」

## 步骤

{rows}

## 帧计数（WS events.mux）

{frame_table}

## 事件计数（session/event）

{event_table}

## 残渣清单

- live 残渣约定（spec 验收 3）：G1 需求 id SMOKE-EVAL-P6-G1、G3 追踪链接 target SMOKE-EVAL-P6-G3
  （SMOKE-EVAL-P6-* 统一前缀）；G2 全 READ 零残渣；G4 denied 落库零行无残渣；
  P5 B 段残渣 SMOKE-P5-001（total 62）与 P4 记录 total 61 均按历史快照口径（spec 验收口径⑥）。

## 部署前置状态

- {PATCH_PATH}：{patch_note}

## 实测偏差（待需求会话确认）

- **G5 run.jsonl 的 question 事件**：spec P6 验收 2 写「run 事件日志 kind 顺序
  （task→tool_call→tool_result→question→…→done）」，但 P5 实现的 LoggingSink.on_question
  只转发不落盘（run.jsonl 无 question kind——离线 G5 按实际形态断言：
  task→text→tool_call→tool_result×3→turn_end→done，并在 sink 层断言 question 事件位于
  两次 review_item 调用之间）。属 P5 实现与 P5 spec ⑤ 记录形态的偏差，P6 不改 runtime。
- **G4 fix_hint 形态**：spec 验收 2 写「fix_hint（approvals add 命令）」——DRAFT 层
  create_requirement 的修复建议为 reqmesh-harness approvals add create_requirement
  （无 --project；gate.py _deny 按 DRAFT project 可省略=通配），G4 按此断言。

## 注记

- 离线 evals 全绿命令：uv run python evals/run_offline.py（零网络；5/5）。
- live 前置由操作员按 docs/deployment.md「DSH 注册」维护窗口执行后，以
  uv run python evals/run_live.py 执行（REQMESH_SMOKE_OUT 可覆盖记录路径）。
""",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evals/run_live.py", description="P6 evals live runner（network-tagged）")
    parser.add_argument("--task", default=None, choices=["G1", "G2", "G3", "G4"], help="只跑单个任务（默认全部）")
    args = parser.parse_args(argv)

    settings = Settings()
    if not settings.has_credentials():
        print("未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）", file=sys.stderr)
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))
    counts: dict = {"frames": {}, "events": {}}
    ok, note = prerequisite_satisfied()
    steps: list = [("实例", "ok", f"{settings.base_url} · DSH {settings.dsh_url}")]

    if not ok:
        steps.append(("live 前置（DSH 注册）", "待前置后执行", note))
        steps.append(("evals live G1–G4", "待前置后执行", "前置应用后执行：uv run python evals/run_live.py"))
        _write_record(out_path, settings, steps, counts)
        print(f"记录已落盘（前置未满足，待前置后执行）: {out_path}")
        return 0

    task_ids = [args.task] if args.task else ["G1", "G2", "G3", "G4"]
    infos = _run_live_sequence(settings, counts, task_ids)
    all_ok = True
    for task_id in task_ids:
        info = infos.get(task_id, {})
        errors = info.get("errors") or []
        if errors:
            all_ok = False
        steps.append(
            (
                f"live {task_id}",
                True if not errors else f"失败: {errors[0]}",
                (
                    f"运行状态={info.get('status')}；工具序列 {info.get('calls')}；"
                    f"审计 delta {info.get('audit_delta')}；残渣 {info.get('residue') or '无'}；"
                    f"DSH session×{len(info.get('dsn_sessions') or [])}"
                ),
            )
        )
    _write_record(out_path, settings, steps, counts)
    print(f"live evals 记录已落盘: {out_path}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
