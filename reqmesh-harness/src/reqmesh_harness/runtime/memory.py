"""run 级会话内存：project context + run 事件日志（JSONL），XDG state 持久化 + resume 语义（spec ⑤）。

- run 目录：`runs/run-<YYYYmmddTHHMMSS>-<id8>/`（目录 0700、文件 0600）；
  resume 派生目录带 `-resume` 后缀并在 context.json 记录 `resumed_from`；
- context.json：AgentRequest 快照（task、project context、provider、created_at、resumed_from?）；
- run.jsonl：编排轨迹（task/text/tool_call/tool_result/question/turn_end/error/done）——
  与审计日志分文件分语义（审计只记写工具尝试，P2；本日志记整个 run 轨迹，本地文件）；
- dsn-session.txt：DSH sessionId 映射（resume 判定 DSH 会话是否存活）；
- resume 摘要重建：final text + 工具调用序列 + 未决问题（失活分支注入新 DSH 会话）；
- 损坏文件 fail-fast（read_events/read_context 抛 ValueError，绝不静默吞数据）。
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..guardrails.audit import summarize_params
from .provider import ProjectContext

_RUN_NAME_RE = re.compile(r"^run-\d{8}T\d{6}-[0-9a-f]{8}(-resume)?$")

_CONTEXT_FILE = "context.json"
_LOG_FILE = "run.jsonl"
_DSH_FILE = "dsn-session.txt"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass  # 权限尽力而为（网络盘等不支持 chmod 的环境不阻断）


def _write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".run-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class RunRecorder:
    """一次 run 的内存载体：目录 + 三个文件（写路径全部原子替换，路径解析失败即抛）。"""

    def __init__(self, run_dir: Path) -> None:
        self._dir = run_dir

    # ------------------------------------------------------------------ 构造
    @classmethod
    def create(cls, runs_root: Path) -> "RunRecorder":
        runs_root.mkdir(parents=True, exist_ok=True)
        _chmod(runs_root, 0o700)
        ts = _now().strftime("%Y%m%dT%H%M%S")
        run_dir = runs_root / f"run-{ts}-{secrets.token_hex(4)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _chmod(run_dir, 0o700)
        return cls(run_dir)

    def create_resume(self) -> "RunRecorder":
        """同 run-id 恢复 → 新目录 `run-<ts>-<id8>-resume`，context.json 记录 resumed_from。"""
        parent = self._dir.parent
        ts = _now().strftime("%Y%m%dT%H%M%S")
        run_dir = parent / f"run-{ts}-{secrets.token_hex(4)}-resume"
        run_dir.mkdir(parents=True, exist_ok=True)
        _chmod(run_dir, 0o700)
        rec = RunRecorder(run_dir)
        ctx = self.read_context() or {}
        context = {
            "task": ctx.get("task", ""),
            "project_context": ctx.get("project_context"),
            "provider": ctx.get("provider", ""),
            "created_at": _now().isoformat(),
            "resumed_from": self.run_id,
        }
        _write_json_atomic(run_dir / _CONTEXT_FILE, context)
        return rec

    @staticmethod
    def lookup(runs_root: Path, run_id: str) -> Path | None:
        if not _RUN_NAME_RE.match(run_id) or not run_id:
            return None
        path = runs_root / run_id
        return path if path.is_dir() else None

    # ------------------------------------------------------------------ 上下文
    @property
    def dir(self) -> Path:
        return self._dir

    @property
    def run_id(self) -> str:
        return self._dir.name

    def init_context(
        self,
        *,
        task: str,
        project_context: ProjectContext | None,
        provider: str,
        resumed_from: str | None = None,
    ) -> None:
        context: dict[str, Any] = {
            "task": task,
            "project_context": (
                None
                if project_context is None
                else {
                    "project_id": project_context.project_id,
                    "base_url": project_context.base_url,
                    "created_at": project_context.created_at,
                }
            ),
            "provider": provider,
            "created_at": _now().isoformat(),
        }
        if resumed_from is not None:
            context["resumed_from"] = resumed_from
        _write_json_atomic(self._dir / _CONTEXT_FILE, context)

    def read_context(self) -> dict | None:
        path = self._dir / _CONTEXT_FILE
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ValueError(f"run context.json 损坏: {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"run context.json 形状非法（应为对象）: {path}")
        return data

    # ------------------------------------------------------------------ 事件日志
    def record(self, kind: str, **data: Any) -> None:
        line: dict[str, Any] = {"ts": _now().isoformat(), "kind": kind}
        line.update(data)
        path = self._dir / _LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False))
            fh.write("\n")
        _chmod(path, 0o600)

    def record_text(self, text: str) -> None:
        self.record("text", text=text[:2000])  # 流式增量截断（与其它事件字段同口径）

    def record_task(self, task: str) -> None:
        self.record("task", task=task[:2000])

    def record_tool_call(self, name: str, args: dict) -> None:
        # 复用 guardrails 参数摘要（P2 既有公共函数；run 日志与审计同口径，只 import 不复制）
        self.record("tool_call", name=name, args=summarize_params(args or {}))

    def record_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.record("tool_result", name=name, ok=bool(ok), summary=summary[:500])

    def record_question(self, question: str, answer: str) -> None:
        self.record("question", question=question[:500], answer=answer[:500])

    def record_turn_end(self, reason: str) -> None:
        self.record("turn_end", reason=reason)

    def record_error(self, kind: str, message: str) -> None:
        self.record("error", error_kind=kind, message=message[:500])

    def record_done(
        self, status: str, final_text: str, *, tool_calls: int, questions: int
    ) -> None:
        self.record(
            "done",
            status=status,
            final_text=final_text[:2000],
            tool_calls=tool_calls,
            questions=questions,
        )

    def read_events(self) -> list[dict[str, Any]]:
        path = self._dir / _LOG_FILE
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError as exc:
                raise ValueError(f"run.jsonl 第 {line_no} 行损坏: {exc}") from exc
            if not isinstance(data, dict) or not isinstance(data.get("kind"), str):
                raise ValueError(f"run.jsonl 第 {line_no} 行形状非法: {path}")
            out.append(data)
        return out

    # ------------------------------------------------------------------ DSH session 映射
    def save_dsh_session(self, session_id: str) -> None:
        """dsn-session.txt 映射（resume 用；run.jsonl 只记 spec ⑤ 枚举的 kind 集合）。"""
        self._dir.joinpath(_DSH_FILE).write_text(session_id, encoding="utf-8")
        _chmod(self._dir / _DSH_FILE, 0o600)

    def read_dsh_session(self) -> str | None:
        path = self._dir / _DSH_FILE
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8").strip() or None


def rebuild_summary(run_dir: Path) -> str:
    """从 run.jsonl 重建「此前进展摘要」（resume 失活分支；spec ⑤）。

    内容：最终文本（无 done 事件则列已生成文本段）、工具调用序列（含结果摘要）、
    未决问题；明确标注「历史由 harness 内存重建」。损坏日志 fail-fast。
    """
    rec = RunRecorder(run_dir)
    events = rec.read_events()
    lines: list[str] = [
        f"（历史由 harness 内存重建，来源 run 日志 {rec.run_id}）此前进展摘要：",
        "",
    ]
    done = next((e for e in events if e["kind"] == "done"), None)
    if done:
        lines.append(f"- 最终文本：{done.get('final_text', '') or '（无）'}")
        lines.append(
            f"- 状态：{done.get('status')}（工具调用 {done.get('tool_calls', 0)} 次；问题 {done.get('questions', 0)} 个）"
        )
    else:
        texts = [e.get("text", "") for e in events if e["kind"] == "text"]
        lines.append(
            "- 最终文本：未知（上一 run 未到达完成事件；已生成文本段："
            + "".join(texts)[:500]
            + "）"
        )
    calls: list[str] = []
    for e in events:
        if e["kind"] == "tool_call":
            calls.append(f"{e.get('name')}({_brief(e.get('args'))})")
    if calls:
        lines.append("- 工具调用序列：" + " → ".join(calls))
    results = [e for e in events if e["kind"] == "tool_result"]
    for e in results:
        mark = "成功" if e.get("ok") else "失败"
        lines.append(
            f"- 工具结果 {e.get('name')}：{mark}——{str(e.get('summary', ''))[:120]}"
        )
    for e in events:
        if e["kind"] == "question":
            lines.append(f"- 未决问题：{e.get('question')}（答复：{e.get('answer')}）")
    for e in events:
        if e["kind"] == "error":
            lines.append(f"- 错误：{e.get('error_kind')}——{e.get('message')}")
    return "\n".join(lines)


def _brief(args: Any) -> str:
    if not isinstance(args, dict) or not args:
        return "-"
    return ", ".join(f"{k}={str(v)[:40]}" for k, v in list(args.items())[:6])


class LoggingSink:
    """StreamSink 装饰：转发 inner 渲染的同时把事件写入 RunRecorder（run 事件日志）。"""

    def __init__(self, recorder: RunRecorder, inner) -> None:
        self._recorder = recorder
        self._inner = inner

    def on_text(self, text: str) -> None:
        self._recorder.record_text(text)
        self._inner.on_text(text)

    def on_tool_call(self, name: str, args: dict) -> None:
        self._recorder.record_tool_call(name, args)
        self._inner.on_tool_call(name, args)

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self._recorder.record_tool_result(name, ok, summary)
        self._inner.on_tool_result(name, ok, summary)

    def on_question(self, q) -> None:
        self._inner.on_question(q)

    def on_turn_end(self, reason: str) -> None:
        self._recorder.record_turn_end(reason)
        self._inner.on_turn_end(reason)


__all__ = ["LoggingSink", "RunRecorder", "rebuild_summary"]
