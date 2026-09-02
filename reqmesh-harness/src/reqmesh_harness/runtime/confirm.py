"""审批门交互时序：run 层「确认中继」（spec ④；#41）。

- 裁决源不变：白名单唯一裁决源、每次调用重读、fail-closed——gate.py/whitelist.py/audit.py
  零 diff（只 import）；本模块只维护白名单文件（`WhitelistStore.append`，与 approvals CLI
  同源同规则），无「仅本次放行」临时通道；
- 三类通道（优先级：预先白名单 > --yes 无头自动 > TTY 逐条）：
  - 预先白名单：run 前操作员 `approvals add`（既有 CLI）——run 全程无交互；
  - --yes 自动：on_denied 时立即 append（DRAFT/MUTATE 规则与 approvals CLI 完全一致，
    MUTATE 必须带 project；缺 project 无法确认 → 按拒绝答复）；
  - TTY 逐条：denied 后问题帧到达时呈现 spec ④ 提示文本，y → append；N/其他 → 拒绝；
- 通用问题（无 pending 审批）兜底：TTY 转提问内容征求回答；--yes 下答复「请继续」；
- 审计行为不在这里产生：denied/approved 两行由 gate/写工具处理器按 P2 语义产生
  （本模块不写审计文件）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..config import Settings, get_settings
from ..guardrails.approvals_cli import LEVELS_NEEDING_PROJECT, _tool_level
from ..guardrails.whitelist import WhitelistEntry, WhitelistStore
from .loop import ToolExecutor, is_denied_error
from .provider import Question, ToolResult

APPROVE_ANSWER = "已批准，请重试；白名单条目已添加。"
REJECT_ANSWER = "用户拒绝了该写操作，请放弃该操作并在最终总结中说明。"
GENERIC_CONTINUE = "请继续。"


@dataclass(frozen=True)
class PendingApproval:
    """一次 denied 写调用的确认上下文（tool/project/level/dry_run 来自调用参数，不猜）。"""

    tool: str
    project_id: str | None
    level: str
    dry_run: bool

    @property
    def display_project(self) -> str:
        return self.project_id or "<通配>"


class ConfirmationRelay:
    """确认中继：denied（ApprovalDeniedError）→ 确认通道 → 白名单维护 → 回答 agent。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        auto_yes: bool = False,
        confirm_reader: Callable[[str], str] | None = None,
        warning: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._store = WhitelistStore(self.settings.resolved_approvals_file())
        self._auto_yes = auto_yes
        self._reader = confirm_reader or input
        self._warning = warning or (lambda text: None)
        self._pending: PendingApproval | None = None

    @property
    def pending(self) -> PendingApproval | None:
        return self._pending

    @property
    def approvals_file(self) -> Path:
        return self._store.path

    # ------------------------------------------------------------------ 拒绝上报
    def on_denied(self, tool: str, args: dict, error_text: str) -> None:
        """run 层收到 denied 工具结果（ApprovalDeniedError 文本）→ 记录 + --yes 自动通道。"""
        level = _tool_level(
            tool
        )  # 与 approvals CLI 同源（注册表层级；未知工具 → None）
        if level is None:
            self._warning(f"无法确认 {tool}：工具不在注册表（未知层级），按拒绝处理。")
            self._pending = None
            return
        project_id = args.get("project_id") if isinstance(args, dict) else None
        if not isinstance(project_id, str) or not project_id:
            project_id = None
        dry_run = bool(args.get("dry_run")) if isinstance(args, dict) else False
        self._pending = PendingApproval(
            tool=tool, project_id=project_id, level=level, dry_run=dry_run
        )
        # --yes 无头自动：denied 即写白名单（重试无需等待问题帧；无法确认时留待 answer 拒绝）
        if self._auto_yes and self._can_confirm(self._pending):
            self._append(self._pending)

    # ------------------------------------------------------------------ 问题答复
    def answer(self, q: Question) -> str:
        """agent 提问（question/requested）→ 回复文本；按 pending 状态进入确认通道。"""
        if self._pending is None:
            return self._answer_generic(q)
        pending = self._pending
        self._pending = None
        if self._auto_yes:
            if self._can_confirm(pending):
                self._append(pending)
                return APPROVE_ANSWER
            self._warning(
                f"无法自动批准 {pending.tool}（{pending.level} 层需要具体 project，"
                "调用参数未提供 project_id），按拒绝答复。"
            )
            return REJECT_ANSWER
        answer = self._reader(self._confirm_prompt(pending)).strip().lower()
        if answer in ("y", "yes"):
            if self._can_confirm(pending):
                self._append(pending)
                return APPROVE_ANSWER
            self._warning(
                f"无法批准 {pending.tool}（{pending.level} 层需要具体 project）——未写白名单，按拒绝答复。"
            )
            return REJECT_ANSWER
        return REJECT_ANSWER

    def confirm_now(self) -> str | None:
        """tool-loop 路线的确认触发点：denied 工具结果即确认（无 DSH question 帧可言）。

        - --yes：on_denied 已 append，此处只清 pending（幂等）；
        - TTY：立即呈现审批确认提示（y → append；否则拒绝）；
        - 无 pending（已被决议）：返回 None。
        返回 APPROVE_ANSWER / REJECT_ANSWER / None。
        """
        if self._pending is None:
            return None
        return self.answer(Question(id="", question=""))

    # ------------------------------------------------------------------ 内部
    def _can_confirm(self, pending: PendingApproval) -> bool:
        # 与 approvals CLI 完全一致的层级规则（单一来源：guardrails.approvals_cli）
        if pending.level in LEVELS_NEEDING_PROJECT and not pending.project_id:
            return False
        return True

    def _append(self, pending: PendingApproval) -> None:
        entry = WhitelistEntry(
            tool=pending.tool, project=pending.project_id, dry_run_only=False
        )
        existing = self._store.load()
        if entry not in existing:
            self._store.append(entry)

    def _confirm_prompt(self, pending: PendingApproval) -> str:
        return (
            f"审批确认：tool={pending.tool} project={pending.display_project} "
            f"level={pending.level} dry_run={pending.dry_run} —— "
            f"批准将写入白名单条目并重试 [y/N] "
        )

    def _answer_generic(self, q: Question) -> str:
        if self._auto_yes:
            return GENERIC_CONTINUE
        text = self._reader(f"用户提问：{q.question}\n请回答：").strip()
        return text or GENERIC_CONTINUE


class ConfirmedToolExecutor:
    """tool-loop 路线的确认中继接线：denied 错误文本 → relay.on_denied（与 DSH 侧 handler 同语义）。"""

    def __init__(self, inner: ToolExecutor, relay: ConfirmationRelay) -> None:
        self._inner = inner
        self._relay = relay

    def __call__(self, name: str, args: dict, project_context) -> ToolResult:
        result = self._inner(name, args, project_context)
        if not result.ok and is_denied_error(result.text):
            self._relay.on_denied(name, args, result.text)
            # tool-loop 路线没有 DSH question/requested 帧：denial 即确认（TTY 提示/--yes 已 append）
            self._relay.confirm_now()
        return result


__all__ = [
    "APPROVE_ANSWER",
    "ConfirmedToolExecutor",
    "ConfirmationRelay",
    "GENERIC_CONTINUE",
    "PendingApproval",
    "REJECT_ANSWER",
]
