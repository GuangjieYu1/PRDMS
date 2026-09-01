"""审批白名单存储：TOML 读写（唯一裁决源文件）。

格式（与 spec 一致，`approvals` CLI 与手改同源）：

    [[approvals]]
    tool = "create_requirement"   # 必填：工具名
    project = "cessna-172"        # 可选；省略 = DRAFT 通配全部项目；MUTATE/ADMIN 必填
    dry_run_only = false          # 可选；true = 只放行 dry_run 调用

- 缺失文件 → 空白名单（fail-closed 的 trivial 情形）；
- 损坏文件 → ApprovalConfigError（fail-closed：宁可拒绝也不放行，且不覆盖原文件）。
"""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..errors import ApprovalConfigError

# 白名单条目数上限：防御恶意/失控写入（每次调用全量重读，条目数必须可控）
MAX_ENTRIES = 1000


@dataclass(frozen=True)
class WhitelistEntry:
    tool: str
    project: str | None = None
    dry_run_only: bool = False

    @property
    def label(self) -> str:
        """审计 approved_by 字段：命中条目的描述（`tool[+project]`）。"""
        return f"{self.tool}+{self.project}" if self.project else self.tool


class WhitelistStore:
    """白名单文件存储（读：tomllib；写：规范化 TOML，0600）。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[WhitelistEntry]:
        if not self._path.exists():
            return []
        try:
            raw = tomllib.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ApprovalConfigError(f"白名单文件损坏/不可读: {self._path}: {exc}") from exc
        return _parse(raw, self._path)

    def append(self, entry: WhitelistEntry) -> None:
        """追加一条（先读校验原文件合法 + 去重，再以规范化写入全部条目）。"""
        entries = self.load()
        if entry in entries:
            return
        if len(entries) >= MAX_ENTRIES:
            raise ApprovalConfigError(f"白名单条目数已达上限 {MAX_ENTRIES}")
        self._save(entries + [entry])

    def remove(self, tool: str, project: str | None = None) -> int:
        """删除匹配条目（project 为 None 时删除该工具的全部条目）；返回删除数量。"""
        entries = self.load()
        kept = [
            e
            for e in entries
            if not (e.tool == tool and (project is None or e.project == project))
        ]
        removed = len(entries) - len(kept)
        if removed:
            self._save(kept)
        return removed

    def replace(self, entries: list[WhitelistEntry]) -> None:
        """整体替换（CLI remove 复用；空列表 = 清空白名单）。"""
        if len(entries) >= MAX_ENTRIES:
            raise ApprovalConfigError(f"白名单条目数已达上限 {MAX_ENTRIES}")
        self._save(entries)

    # ------------------------------------------------------------------ 内部
    def _save(self, entries: list[WhitelistEntry]) -> None:
        text = _to_toml(entries)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".approvals-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


def _parse(raw: dict, path: Path) -> list[WhitelistEntry]:
    entries = raw.get("approvals", [])
    if not isinstance(entries, list):
        raise ApprovalConfigError(f"白名单文件格式非法（approvals 应为表数组）: {path}")
    out: list[WhitelistEntry] = []
    for i, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ApprovalConfigError(f"白名单条目 {i} 不是表: {path}")
        tool = item.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ApprovalConfigError(f"白名单条目 {i} 缺 tool（字符串）: {path}")
        project = item.get("project")
        if project is not None and not isinstance(project, str):
            raise ApprovalConfigError(f"白名单条目 {i} 的 project 应为字符串: {path}")
        dry_run_only = item.get("dry_run_only", False)
        if not isinstance(dry_run_only, bool):
            raise ApprovalConfigError(f"白名单条目 {i} 的 dry_run_only 应为布尔: {path}")
        out.append(WhitelistEntry(tool=tool, project=project, dry_run_only=bool(dry_run_only)))
    return out


def _to_toml(entries: list[WhitelistEntry]) -> str:
    """规范化序列化：条目按 (tool, project) 排序，值经 json.dumps 确保 TOML 合法转义。

    注：CLI 写回时以规范化格式整体替换（可读性优先；上游手写注释由 CLI add 的
    读取校验兜底——不会静默破坏非法文件）。
    """
    lines = [
        "# reqmesh-harness 审批白名单（唯一裁决源；勿与文件外渠道双轨维护）",
        "# DRAFT 条目 project 可省略（通配全部项目）；MUTATE/ADMIN 必须指定具体 project。",
        "",
    ]
    for entry in sorted(entries, key=lambda e: (e.tool, e.project or "")):
        lines.append("[[approvals]]")
        lines.append(f'tool = {json.dumps(entry.tool, ensure_ascii=False)}')
        if entry.project is not None:
            lines.append(f'project = {json.dumps(entry.project, ensure_ascii=False)}')
        lines.append(f"dry_run_only = {str(entry.dry_run_only).lower()}")
        lines.append("")
    return "\n".join(lines)
