"""guardrails：写路径护栏（P2）——审批门 + 白名单 + dry-run 语义 + 审计日志。

- 白名单（TOML，XDG config，0600）是**唯一裁决源**：`approvals` CLI 与手改文件同源；
- 审批门对每次调用按当前白名单 fail-closed 裁决（白名单每次调用重读，不缓存）；
- dry-run 不是绕过审批的后门：dry_run=true 照跑审批门；
- 审计日志（JSONL，XDG state，0600）记录全部写工具调用（含 denied/dry_run/错误路径）。
"""

from .audit import AuditLog, summarize_params
from .gate import ApprovalDecision, ApprovalGate, GateToken, WhitelistEntry
from .whitelist import WhitelistStore

__all__ = [
    "ApprovalDecision",
    "ApprovalGate",
    "AuditLog",
    "GateToken",
    "WhitelistEntry",
    "WhitelistStore",
    "summarize_params",
]
