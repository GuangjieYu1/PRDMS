"""whoami 的凭据剥离（READ 工具的**唯一**加工点）。

背景（实测事故）：阿里云部署后，通过远程 MCP 调 `whoami`，返回体里带着
**服务账号**的会话 JWT 与 CSRF token——因为该工具逐字透传了上游
`/api/auth/whoami` 的响应。持有 MCP token 的任何客户端都能拿到它。

本文件锁定修复：凭据必须被剥离，而 `password_change_required` 这类状态标志
**不得**被误伤（所以 denylist 用精确键名，不用子串匹配）。
"""

from __future__ import annotations

import respx
from httpx import Response

from reqmesh_harness.tools.groups import auth_project

#: 上游真实响应形状（取自 tests/fixtures/http/whoami.json + 实测带凭据的返回）
_UPSTREAM = {
    "username": "reqmesh-harness",
    "role": "maintainer",
    "full_name": "",
    "email": "",
    "email_verified": False,
    "last_active": "2026-10-10T02:15:14Z",
    "joined": "2026-10-10T02:03:06Z",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.FAKE.SIGNATURE",
    "csrf_token": "WRtYGb77iWQkC3R8O8mQgdVvWhgNxIKeWbZD3hLC04c",
    "password_change_required": False,
}


def test_whoami_strips_session_credentials(reqmesh_env) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(return_value=Response(200, json=_UPSTREAM))
        result = auth_project.whoami()

    assert "token" not in result
    assert "csrf_token" not in result
    # 身份核验所需字段必须保留
    assert result["username"] == "reqmesh-harness"
    assert result["role"] == "maintainer"


def test_whoami_keeps_password_change_flag(reqmesh_env) -> None:
    """`password_change_required` 含 "password" 子串，但它是状态标志，不能误删。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(return_value=Response(200, json=_UPSTREAM))
        result = auth_project.whoami()

    assert result["password_change_required"] is False


def test_whoami_strips_other_credential_shaped_keys(reqmesh_env) -> None:
    payload = dict(_UPSTREAM, access_token="a", refresh_token="r", api_key="k", secret="s")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(return_value=Response(200, json=payload))
        result = auth_project.whoami()

    for key in ("access_token", "refresh_token", "api_key", "secret"):
        assert key not in result, key
    assert result["role"] == "maintainer"


def test_whoami_passes_through_non_dict(reqmesh_env) -> None:
    """上游返回非对象时不崩（原样返回，不做假设）。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(return_value=Response(200, json=[1, 2]))
        assert auth_project.whoami() == [1, 2]
