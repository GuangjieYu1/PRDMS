"""审批门（P2）：白名单 fail-closed 裁决 + GateToken 签发 + ADMIN 显式开启预留。

- 层级来源：调用方（注册表 ToolSpec.level，ADR-0002）——绝不解析工具名推断层级；
- 每次调用重读白名单（不缓存），fail-closed；
- DRAFT：条目 `tool` 必填，`project` 可省略（= 通配全部项目）；
- MUTATE/ADMIN：条目 `tool` + 具体 `project` 必填（禁止通配）；
- `dry_run_only=true` 条目只放行 dry_run 调用（灰度上线用）；
- ADMIN 层：`REQMESH_ENABLE_ADMIN=1` + 白名单条目，双卡缺一不可（D6「危险操作卡两道」）；
- GateToken 只由本门在批准时签发（不可自行伪造），WriteClient 构造强依赖它。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..config import Settings
from .whitelist import WhitelistEntry, WhitelistStore

DecisionStatus = Literal["approved", "denied", "admin_disabled"]

_DENY_FIX = """修复建议（二选一，白名单为唯一裁决源）:
  1) 交互式添加: reqmesh-harness approvals add {tool}{project_arg}
  2) 手动编辑 {file} 后重试:
     [[approvals]]
     tool = "{tool}"{project_line}"""

_KEY = object()  # GateToken 内部签发键（模块私有，外部不可构造）


class GateToken:
    """结构护栏令牌：仅审批门批准时签发（外部不可伪造），写视图凭其可创建。

    `WriteClient` 构造函数要求 GateToken——未过门的调用方在类型上拿不到写客户端，
    与 P1 只读视图（结构上只有 get()）对称。令牌内容不暴露（repr 脱敏）。
    """

    __slots__ = ("_tool", "_project", "_entry")

    def __init__(self, tool: str, project: str | None, entry: WhitelistEntry, key: object = None) -> None:
        if key is not _KEY:
            raise TypeError("GateToken 只能由审批门签发（内部构造，不可伪造）")
        self._tool = tool
        self._project = project
        self._entry = entry

    @property
    def entry(self) -> WhitelistEntry:
        return self._entry

    def __repr__(self) -> str:
        return f"GateToken(tool={self._tool!r}, project={self._project!r})"


@dataclass(frozen=True)
class ApprovalDecision:
    """审批门裁决结果（写工具按此分支：approved → 写；denied → ApprovalDeniedError）。"""

    status: DecisionStatus
    level: str
    tool: str
    project_id: str
    dry_run: bool
    token: GateToken | None = None
    entry: str | None = None          # approved_by：命中的白名单条目（tool[+project]）
    deny_reason: str | None = None    # 未命中/禁用/仅 dry_run 的规则描述
    fix_hint: str | None = None       # denied 时的精确修复建议（CLI 命令 + TOML 片段）

    @property
    def approved(self) -> bool:
        return self.status == "approved"


class ApprovalGate:
    """白名单审批门：fail-closed；白名单文件每次调用重读，不缓存。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._store = WhitelistStore(self.settings.resolved_approvals_file())

    @property
    def approvals_file(self):
        return self._store.path

    def decide(self, tool: str, project_id: str, dry_run: bool, level: str) -> ApprovalDecision:
        """按注册表层级裁决一次调用（READ 直通——本门只处理写层级）。"""
        if level == "READ":
            return ApprovalDecision("approved", level, tool, project_id, dry_run)
        if level == "ADMIN" and not self.settings.enable_admin:
            return ApprovalDecision(
                "admin_disabled",
                level,
                tool,
                project_id,
                dry_run,
                deny_reason="REQMESH_ENABLE_ADMIN 未开启（ADMIN 层默认可用性为关闭）",
            )
        entries = self._store.load()  # 损坏 → ApprovalConfigError（fail-closed）
        matched = [e for e in entries if e.tool == tool]
        if not matched:
            return self._deny(tool, project_id, dry_run, level, "白名单无该工具的条目")
        if level == "DRAFT":
            hit = [e for e in matched if e.project is None or e.project == project_id]
        else:  # MUTATE / ADMIN：tool + 具体 project 必填（禁止通配）
            hit = [e for e in matched if e.project == project_id]
            if not hit:
                return self._deny(
                    tool,
                    project_id,
                    dry_run,
                    level,
                    f"未命中条目（{level} 层要求条目含具体 project={project_id}；通配条目无效）",
                )
        # dry_run_only 条目：仅放行 dry_run 调用
        for entry in hit:
            if not entry.dry_run_only:
                return ApprovalDecision(
                    "approved", level, tool, project_id, dry_run,
                    token=self._issue(tool, project_id, entry), entry=entry.label,
                )
        if dry_run and hit:
            entry = hit[0]
            return ApprovalDecision(
                "approved", level, tool, project_id, dry_run,
                token=self._issue(tool, project_id, entry), entry=entry.label,
            )
        return self._deny(
            tool, project_id, dry_run, level, "白名单条目为 dry_run_only（只放行 dry_run 调用）"
        )

    # ------------------------------------------------------------------ 内部
    def _issue(self, tool: str, project_id: str, entry: WhitelistEntry) -> GateToken:
        return GateToken(tool, project_id, entry, key=_KEY)

    def _deny(
        self, tool: str, project_id: str, dry_run: bool, level: str, reason: str
    ) -> ApprovalDecision:
        if level == "MUTATE":
            project_arg = f" --project {project_id}"
            project_line = f'\n     project = "{project_id}"'
        elif level == "ADMIN":
            project_arg = f" --project {project_id}"
            project_line = f'\n     project = "{project_id}"'
        else:  # DRAFT：project 可省略（建议给出，便于最小权限）
            project_arg = ""
            project_line = ""
        return ApprovalDecision(
            "denied",
            level,
            tool,
            project_id,
            dry_run,
            deny_reason=reason,
            fix_hint=_DENY_FIX.format(
                tool=tool,
                project_arg=project_arg,
                project_line=project_line,
                file=self._store.path,
            ),
        )
