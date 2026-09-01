"""工具调用级审计日志（P2）：JSONL append-only、0600、字段契约 version=1。

- 范围：全部写工具调用（批准/拒绝/dry_run/失败路径都记，一行一次调用）；READ 不记；
- 文件：`REQMESH_AUDIT_FILE`（默认 XDG state `~/.local/state/reqmesh-harness/audit.jsonl`）；
- 写入失败不得阻断工具调用（降级告警日志）；
- 审计日志不提供 READ 工具（不向模型暴露；本地文件供操作员/审计方查阅）；
- 参数摘要：标量原值截断 200 字符；容器记类型与长度；绝不含凭据
  （凭据不进工具参数，双保险）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("reqmesh_harness.audit")

TRUNCATE_AT = 200


def summarize_params(params: dict[str, Any]) -> dict[str, Any]:
    """参数摘要：标量原值截断 200 字符；容器记类型与长度；其余记类型名。"""
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or isinstance(value, (str, bool, int, float)):
            text = str(value)
            out[key] = text if len(text) <= TRUNCATE_AT else text[:TRUNCATE_AT] + "…"
        elif isinstance(value, (list, tuple, set)):
            out[key] = {"type": type(value).__name__, "length": len(value)}
        elif isinstance(value, dict):
            out[key] = {"type": "dict", "length": len(value)}
        else:
            out[key] = {"type": type(value).__name__}
    return out


class AuditLog:
    """JSONL 审计日志（append-only、0600；写入失败降级告警、不阻断调用）。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        tool: str,
        level: str,
        project_id: str,
        dry_run: bool,
        params_summary: dict[str, Any],
        reason: str,
        decision: str,
        approved_by: str | None,
        deny_reason: str | None,
        upstream: dict[str, str] | None,
        http_status: int | None,
        result: str,
        duration_ms: int,
    ) -> None:
        """追加一行（字段契约 version=1，见 spec 审计节）。"""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "level": level,
            "project_id": project_id,
            "dry_run": bool(dry_run),
            "params_summary": params_summary,
            "reason": reason or "",
            "decision": decision,
            "approved_by": approved_by,
            "deny_reason": deny_reason,
            "upstream": upstream,
            "http_status": http_status,
            "result": result,
            "duration_ms": int(duration_ms),
            "version": 1,
        }
        line = json.dumps(entry, ensure_ascii=False)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.write("\n")
            os.chmod(self._path, 0o600)
        except OSError as exc:
            logger.warning("审计日志写入失败（不阻断工具调用）: %s", exc)

    def read_all(self) -> list[dict[str, Any]]:
        """读取全部行（测试/本地方便调试用；非工具面）。"""
        if not self._path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
