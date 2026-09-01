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


__all__ = [
    "HarnessError",
    "ConfigError",
    "AuthenticationError",
    "LoginFailedError",
    "SessionExpiredError",
    "UpstreamError",
    "TransportError",
]
