"""harness 类型化错误：工具层向上（MCP tool error）给出诊断，不泄露凭据。"""

from __future__ import annotations


class HarnessError(Exception):
    """harness 所有类型化错误的基类。"""


class ConfigError(HarnessError):
    """配置缺失/非法（例如未配置凭据）。"""


class AuthenticationError(HarnessError):
    """认证失败（登录被拒、会话失效且重登失败）。"""


class LoginFailedError(AuthenticationError):
    """登录被上游拒绝（凭据错误等）。"""


class SessionExpiredError(AuthenticationError):
    """会话 401 且自动重登后仍失败。"""


class UpstreamError(HarnessError):
    """上游返回非 2xx（工具以工具错误返回状态码与响应摘要）。"""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"上游 {status_code}: {detail[:500]}")


class TransportError(HarnessError):
    """实例不可达 / 连接失败 / 超时。"""


class ApprovalDeniedError(HarnessError):
    """写工具被审批门拒绝（白名单未命中，fail-closed）。

    错误消息含精确修复建议（`reqmesh-harness approvals add ...` 命令与 TOML 片段）。
    """


class AdminDisabledError(HarnessError):
    """ADMIN 层工具在 REQMESH_ENABLE_ADMIN=1 未设置时被拒绝（显式开启预留）。"""


class ApprovalConfigError(HarnessError):
    """审批白名单文件损坏/非法（fail-closed：宁可拒绝也不放行）。"""


class InputParseError(HarnessError):
    """复合工具（P3 draft_requirement）的自然语言输入解析失败。

    消息含受支持形态示例；按 spec ⑤ 边界：不发起写请求、不记审计。
    """


class ProviderError(HarnessError):
    """P5 provider 错误（统一归一，spec ③）：kind/code/message 三元组。

    - kind ∈ {unavailable, timeout, protocol, busy, denied_answer}；
    - code：DSH rpcError 的 code 原样保留（非 DSH 源错误为 None）；
    - message：中文语义化消息（不含凭据、不含上游原始内文细节）。
    """

    def __init__(self, kind: str, message: str, code: str | None = None) -> None:
        self.kind = kind
        self.code = code
        self.message = message
        super().__init__(message)


__all__ = [
    "HarnessError",
    "ConfigError",
    "AuthenticationError",
    "LoginFailedError",
    "SessionExpiredError",
    "UpstreamError",
    "TransportError",
    "ApprovalDeniedError",
    "AdminDisabledError",
    "ApprovalConfigError",
    "InputParseError",
    "ProviderError",
]
