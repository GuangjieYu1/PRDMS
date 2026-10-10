"""认证/项目域 READ 工具：whoami、list_projects。"""

from __future__ import annotations

from typing import Any

from ._common import PROJECT_PATH, read_json

#: 会话凭据字段的**精确键名** denylist（小写比较）。
#:
#: 为什么需要：上游 `/api/auth/whoami` 会把会话凭据放进响应体，而本工具此前**逐字
#: 透传**——任何持有 MCP token 的客户端因此能拿到**服务账号**的会话 JWT 与 CSRF
#: token。实测确认（2026-10-10，阿里云部署）：返回体含
#: `"token": "eyJhbGciOi..."` 与 `"csrf_token": "WRtYGb77..."`。
#:
#: 用精确匹配而非子串匹配：`password_change_required` 含 "password" 但它是调用方
#: 需要的状态标志，子串匹配会误伤。
_CREDENTIAL_FIELDS = frozenset({
    "token", "csrf_token", "access_token", "refresh_token",
    "password", "secret", "api_key", "apikey",
})


def whoami() -> Any:
    """READ-ONLY 返回当前登录用户与角色（身份核验）。

    **凭据字段被剥离**：上游响应中的会话 `token` / `csrf_token` 不返回给调用方。
    会话凭据不属于身份核验所需信息，且持有它即可冒充服务账号直接调用 reqmesh。
    这是本工具**唯一**相对上游响应的加工（故 mapping 中 passthrough=False）。
    """
    payload = read_json("/api/auth/whoami")
    if not isinstance(payload, dict):
        return payload
    return {
        key: value
        for key, value in payload.items()
        if key.lower() not in _CREDENTIAL_FIELDS
    }


def list_projects(project_id: str | None = None) -> Any:
    """READ-ONLY 列出项目；给出 project_id 时返回单个项目详情。"""
    if project_id:
        return read_json(f"{PROJECT_PATH}/{project_id}")
    return read_json(PROJECT_PATH)
