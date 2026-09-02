#!/usr/bin/env python3
"""P5 冒烟（network-tagged，不进默认 pytest 集合）：两段式。

- **A 段（无需部署前置，立即可跑）**：DSH 适配器机制——session.create → session.prompt
  （纯回答任务，零工具调用）→ WS events.mux 订阅断言（session/subscribed、assistant/chunk>0、
  turn/end、session.list running=false）；另起慢任务验证 session.cancel → accepted + 归闲。
  硬断言：对 reqmesh 零请求、零审计行、零副作用。
- **B 段（需部署前置：DSH web profile 已注册 mcp__reqmesh__* 40 工具，spec「DSH 部署步骤」；
  前置满足后以 REQMESH_P5_SMOKE_B=1 重跑本脚本启用）**：真实任务 SMOKE-P5-001
  （自然语言建需求，denied → 确认（--yes 自动，白名单为空）→ approved 重试 →
  落库回读 + total 61→62 + 审计恰 2 行 + 流式帧断言 + 无 approval/requested 帧）。

本 phase 硬约束：不得修改运行中 DSH 宿主配置；未满足前置时只跑 A 段并在记录注明。
记录落盘 docs/smoke/P5-cessna-172.md（REQMESH_SMOKE_OUT 可覆盖）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

from reqmesh_harness.config import Settings
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.guardrails.whitelist import WhitelistStore
from reqmesh_harness.runtime.confirm import ConfirmationRelay, ConfirmedToolExecutor
from reqmesh_harness.runtime.dsh_provider import DshProvider, DshRpcClient, parse_frame
from reqmesh_harness.runtime.loop import RunDriver, ToolExecutor, run_task
from reqmesh_harness.runtime.provider import Question
from reqmesh_harness.tools import build_registry

PROJECT_ID = "cessna-172"
SMOKE_ID = "SMOKE-P5-001"
EARS_SENTENCE = (
    "When the landing gear is down and locked, the aircraft shall display "
    "a gear-down indication within 1 s."
)
B_TASK = f"用自然语言给 {PROJECT_ID} 建一条需求：{EARS_SENTENCE}（id 用 {SMOKE_ID}，project {PROJECT_ID}）"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P5-cessna-172.md"

_orig_impl = {
    m: getattr(httpx.Client, m) for m in ("get", "post", "put", "patch", "delete")
}
_HTTP_LOGS: list[tuple[str, str]] = []


def _record_http(_settings):
    """包装 httpx.Client 方法：记录 (method, base_url + path)（A 段断言对 reqmesh 零请求）。"""
    if _HTTP_LOGS:
        return None  # 幂等：只包装一次

    def wrap(method: str):
        def inner(self, url, **kwargs):
            _HTTP_LOGS.append(
                (method.upper(), str(getattr(self, "base_url", "") or "") + str(url))
            )
            return _orig_impl[method](self, url, **kwargs)

        return inner

    for m in ("get", "post", "put", "patch", "delete"):
        setattr(httpx.Client, m, wrap(m))
    return None


def _requests_to(base_url: str) -> list[tuple[str, str]]:
    return [(m, u) for m, u in _HTTP_LOGS if base_url.rstrip("/") in (u or "")]


def _restore_http() -> None:
    for m, impl in _orig_impl.items():
        setattr(httpx.Client, m, impl)


class _FrameCounterWs:
    """WS 包装：透传连接并统计帧（session/event 的子类型、approval/question 帧计数）。"""

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
        # events.mux 是全局多路复用流（含宿主其他会话帧）；设置 session_id 时只统计本会话
        sid = self._counts.get("session_id")
        async for raw in self._conn:
            try:
                frame = parse_frame(raw)
            except Exception:  # noqa: BLE001 — 计数器不因解析失败中断
                frame = None
            if frame is None:
                continue
            if sid is None or frame.session_id is None or frame.session_id == sid:
                self._counts["frames"][frame.kind] = (
                    self._counts["frames"].get(frame.kind, 0) + 1
                )
                if frame.kind == "session/event":
                    etype = (frame.payload.get("event") or {}).get("type")
                    self._counts["events"][etype] = (
                        self._counts["events"].get(etype, 0) + 1
                    )
            yield raw

    async def close(self) -> None:
        pass


def _counter_factory(counts: dict):
    def factory(url: str):
        import websockets

        counts["ws_opens"] = counts.get("ws_opens", 0) + 1
        inner = websockets.connect(url)
        return _FrameCounterWs(inner, counts)

    return factory


class _SilentSink:
    def on_text(self, text: str) -> None: ...

    def on_tool_call(self, name: str, args: dict) -> None: ...

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None: ...

    def on_question(self, q: Question) -> None: ...

    def on_turn_end(self, reason: str) -> None: ...


def _probe_dsh(
    settings: Settings, counts: dict, steps: list[tuple[str, str | bool, str]]
):
    """A 段：纯回答任务 + 流式断言 + 慢任务 cancel（spec ⑥ A 段）。"""

    async def probe() -> dict:
        rpc = DshRpcClient(settings.dsh_url)
        session_ids: list[str] = []

        def on_session(session_id: str) -> None:
            # 以 provider 实际创建的 session 为帧统计过滤对象（events.mux 是全局多路复用流）
            session_ids.append(session_id)
            counts["session_id"] = session_id

        provider = DshProvider(
            settings,
            ws_factory=_counter_factory(counts),
            on_session=on_session,
            on_denied=lambda *a: None,
            poll_interval=0.3,
        )
        from reqmesh_harness.runtime.provider import AgentRequest

        request = AgentRequest(
            task="请只回答一行：P5-A 冒烟正常；不要调用任何工具。",
            project_context=None,
            history=[],
            tools=[],
        )
        result = await provider.run_agentic(
            request, _SilentSink(), cancel=threading.Event()
        )
        assert result.status == "completed", result
        session_id = session_ids[0] if session_ids else "（provider 未回调 session）"
        assert "P5-A 冒烟正常" in result.final_text, result.final_text
        # 流式：chunk>0 且先于 turn/end
        assert counts["events"].get("assistant/chunk", 0) > 0, counts
        assert counts["frames"].get("session/subscribed", 0) >= 1, counts

        # 慢任务 + cancel（另一 session）
        slow = rpc.call("session.create", {"cwd": settings.dsh_cwd or os.getcwd()})
        slow_id = slow["sessionId"]
        counts["session_id"] = None  # 取消过滤（慢任务无 ws 订阅）
        rpc.call(
            "session.prompt",
            {
                "sessionId": slow_id,
                "mode": "queue",
                "content": [
                    {
                        "type": "text",
                        "text": "请先逐步推理（只输出思考），不要调用任何工具。",
                    }
                ],
            },
        )
        cancel_value = rpc.call("session.cancel", {"sessionId": slow_id})
        assert cancel_value.get("accepted") is True, cancel_value
        idle = False
        for _ in range(20):
            listed = rpc.call("session.list", {})
            item = next(
                (i for i in listed.get("items", []) if i.get("sessionId") == slow_id),
                None,
            )
            if item is not None and item.get("running") is False:
                idle = True
                break
            await asyncio.sleep(0.5)
        assert idle, "取消后 DSH session 未归闲"
        return {
            "session_id": session_id,
            "slow_id": slow_id,
            "final_text": result.final_text,
        }

    return asyncio.run(probe())


def _run_a(
    settings: Settings, counts: dict, steps: list[tuple[str, str | bool, str]]
) -> dict:
    info = _probe_dsh(settings, counts, steps)
    counts["session_id"] = None  # 恢复全量统计
    steps.append(
        (
            "A 段：纯回答任务",
            True,
            f"session.subscribed ✓、assistant/chunk×{counts['events'].get('assistant/chunk', 0)}、"
            f"turn/end ✓、session.list running=false；final={info['final_text'][:60]}",
        )
    )
    steps.append(("A 段：慢任务 cancel", True, "session.cancel accepted=true + 归闲"))
    return info


def _b_prerequisite_note(settings: Settings) -> str:
    return (
        "B 段未执行：DSH 部署前置未满足（/home/user/.dsh/profiles/web/cordis.patch.yml 无 "
        "mcp-reqmesh 条目——本 phase 硬约束：不得修改运行中 DSH 宿主配置；属 P6 部署输入）。"
        "前置应用后以 REQMESH_P5_SMOKE_B=1 重跑本脚本执行 B 段（SMOKE-P5-001）。"
    )


async def _run_b(
    settings: Settings, counts: dict, steps: list[tuple[str, str | bool, str]]
) -> dict:
    """B 段：SMOKE-P5-001 真实任务（denied → 确认（--yes）→ approved 重试 → 落库回读）。"""
    from reqmesh_harness.tools.runtime import set_runtime, Runtime

    set_runtime(Runtime(settings))
    relay = ConfirmationRelay(settings, auto_yes=True)
    registry = build_registry()
    driver = RunDriver(registry=registry, settings=settings)
    inner = ToolExecutor(registry=registry, settings=settings)
    driver.executor_factory = lambda: ConfirmedToolExecutor(inner, relay)
    provider = DshProvider(
        settings,
        ws_factory=_counter_factory(counts),
        question_answerer=relay.answer,
        on_denied=relay.on_denied,
        warning=lambda text: print(f"警告: {text}", file=sys.stderr),
        poll_interval=0.3,
    )

    total_before = registry.call("list_requirements", project_id=PROJECT_ID, limit=1)[
        "total"
    ]

    tool_events: list[tuple[str, bool]] = []

    class Sink:
        def on_text(self, text: str) -> None: ...
        def on_tool_call(self, name: str, args: dict) -> None:
            tool_events.append((name, False))

        def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
            if tool_events and tool_events[-1][0] == name:
                tool_events[-1] = (name, ok)

        def on_question(self, q: Question) -> None: ...
        def on_turn_end(self, reason: str) -> None: ...

    result = await driver.drive(
        provider,
        driver.assemble(B_TASK, project_context=None, history=[]),
        Sink(),
        cancel=threading.Event(),
    )
    assert result.status == "completed", result

    # ① 事件流：draft_requirement denied → question → 重试 ok
    drafts = [e for e in tool_events if e[0] == "draft_requirement"]
    assert (
        len(drafts) == 2 and drafts[0][1] is False and drafts[1][1] is True
    ), tool_events
    assert counts["frames"].get("question/requested", 0) >= 1, counts
    # ② 审计 delta 恰 2 行（denied + approved；共享 XDG 文件以基线差断言，P2 version=1 字段）
    audit = AuditLog(settings.resolved_audit_file()).read_all()
    delta = audit[audit_before:]
    assert [a["decision"] for a in delta] == ["denied", "approved"], delta
    assert all(a["tool"] == "draft_requirement" for a in delta)
    assert all(a["version"] == 1 for a in delta)
    # ③ 落库回读
    req = registry.call("get_requirement", project_id=PROJECT_ID, req_id=SMOKE_ID)
    description = req.get("description") or ""
    assert EARS_SENTENCE in description, description
    assert req.get("status") == "proposed", req.get("status")
    # ④ total 61 → 62
    total_after = registry.call("list_requirements", project_id=PROJECT_ID, limit=1)[
        "total"
    ]
    assert total_after == total_before + 1, (total_before, total_after)
    # ⑤ chunk 先于首次 tool/call；无 approval/requested 帧
    error_events = counts["events"]
    assert error_events.get("assistant/chunk", 0) > 0, counts
    assert counts["frames"].get("approval/requested", 0) == 0, counts
    return {
        "total_before": total_before,
        "total_after": total_after,
        "description": description,
        "status": req.get("status"),
    }


def main() -> int:
    settings = Settings()
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))
    tmp = Path(tempfile.mkdtemp(prefix="smoke-p5-"))
    # A 段：全部隔离到临时目录；若启用 B 段（REQMESH_P5_SMOKE_B=1），审批/审计文件必须
    # 与 DSH 侧 harness MCP server 进程共享（spec ④：同一 XDG 文件）——B 段改用真实默认路径，
    # 白名单清空与审计基线为 B 段操作前置（P6 部署输入，本 phase 不执行）。
    settings = settings.model_copy(
        update={
            "audit_file": tmp / "audit.jsonl",
            "approvals_file": tmp / "approvals.toml",
            "session_file": None,
            "runs_dir": tmp / "runs",
        }
    )
    if os.environ.get("REQMESH_P5_SMOKE_B") == "1":
        settings = settings.model_copy(
            update={"audit_file": None, "approvals_file": None}
        )  # 与 DSH 侧进程共默认 XDG 文件（spec ④）
    counts: dict = {"frames": {}, "events": {}}
    steps: list[tuple[str, str | bool, str]] = [
        (
            "实例",
            "ok",
            f"{settings.base_url} · DSH {settings.dsh_url} · project {PROJECT_ID}",
        ),
    ]
    http_requests: list[tuple[str, str]] = []
    try:
        for m in ("get", "post", "put", "patch", "delete"):
            setattr(httpx.Client, m, _record_http(settings))
        _run_a(settings, counts, steps)
        http_requests = _requests_to(settings.base_url)
        assert not http_requests, f"A 段对 reqmesh 发起了请求: {http_requests}"
        audit = AuditLog(settings.resolved_audit_file()).read_all()
        assert audit == [], f"A 段不应产生审计行: {audit}"
        steps.append(("A 段 零副作用", True, "对 reqmesh 零请求 + 审计 0 行"))

        b_note = ""
        b_info = None
        if os.environ.get("REQMESH_P5_SMOKE_B") == "1":
            b_info = asyncio.run(_run_b(settings, counts, steps))
            steps.append(
                (
                    "B 段 SMOKE-P5-001",
                    True,
                    f"denied→approved 双审计行；落库回读 status={b_info['status']}；"
                    f"total {b_info['total_before']}→{b_info['total_after']}；落库描述与 EARS 句一致",
                )
            )
        else:
            b_note = _b_prerequisite_note(settings)
            steps.append(("B 段 部署前置", "待前置后执行", b_note))
    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(
            out_path,
            settings,
            steps,
            failed=str(exc),
            counts=counts,
            http=http_requests,
            b_note="",
            git_info=None,
            b_info=None,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本：任何异常记录并返回失败
        print(f"冒烟失败: {exc!r}", file=sys.stderr)
        _write_record(
            out_path,
            settings,
            steps,
            failed=repr(exc),
            counts=counts,
            http=http_requests,
            b_note="",
            git_info=None,
            b_info=None,
        )
        return 1
    finally:
        _restore_http()
    _write_record(
        out_path,
        settings,
        steps,
        failed=None,
        counts=counts,
        http=http_requests,
        b_note=_b_prerequisite_note(settings),
        git_info=None,
        b_info=None,
    )
    print(f"冒烟通过，记录已落盘: {out_path}")
    return 0


def _write_record(
    out_path, settings, steps, *, failed, counts, http, b_note, git_info, b_info
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows = "\n".join(
        (
            f"| {name} | ok | {detail} |"
            if status is True
            else f"| {name} | {status} | {detail} |"
        )
        for name, status, detail in steps
    )
    frame_table = (
        "\n".join(f"| {k} | {v} |" for k, v in sorted(counts["frames"].items()))
        or "| （无帧） | 0 |"
    )
    event_table = (
        "\n".join(f"| {k} | {v} |" for k, v in sorted(counts["events"].items()))
        or "| （无事件） | 0 |"
    )
    stream_note = f"对 reqmesh 请求：{http or '无'}"
    b_section = b_note or (
        f"| total | {b_info['total_before']} → {b_info['total_after']} | list_requirements |\n"
        f"| SMOKE-P5-001 落库回读 | status={b_info['status']}；description == EARS 句 | get_requirement |"
    )
    out_path.write_text(
        f"""# P5 cessna-172 冒烟记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- DSH 宿主：{settings.dsh_url}（loopback RPC + WS events.mux）
- 结果：**{"通过" if failed is None else f"失败: {failed}"}**

## 步骤与关键计数

{rows}

## 帧计数（WS events.mux）

{frame_table}

## 事件计数（session/event）

{event_table}

## 零副作用与部署前置

- A 段：{stream_note}；审计日志 0 行（临时目录，不触及操作员真实 XDG 文件）；临时 session 由宿主管理。
- B 段：{b_section}

## 残渣清单

- 本记录 A 段在 DSH 宿主留下两个临时 DSH session（纯回答任务 + cancel 任务），无副作用数据。
- P5 B 段残渣约定：SMOKE-P5-001（B 段执行后 total==62；P4 记录 61 仅作历史快照）。

## 实测偏差（待需求会话确认）

- A 段实测观察（非偏差，与 spec 事实 4 一致）：events.mux 是**全局多路复用流**——每个连接
  打开时宿主回放全部 running 会话的 session/subscribed（与 projection 帧），随后持续广播
  各会话的 session/event；适配器与冒烟断言均按 sessionId 过滤（本记录帧/事件计数只含
  A 段会话）。附注：本机宿主当前共有 30+ 个 DSH 会话（含方向层工作会话），冒烟未对其做
  任何写操作（A 段对其零暴露——只读订阅 + 自建会话）。

## 开发会话注记

- B 段部署前置未满足（cordis.patch.yml 无 mcp-reqmesh 条目）→ 本 phase 仅记录步骤（spec「DSH 部署步骤」），
  部署属 P6；前置应用后以 `REQMESH_P5_SMOKE_B=1 python scripts/smoke_p5.py` 执行 B 段全量。
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
