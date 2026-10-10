"""MCP streamable-HTTP 端点的 Bearer 鉴权（可选，默认关闭）。

为什么需要
----------
MCP 协议本身没有认证层，而本 harness 的 READ 工具（28 个）**不受审批门保护**
——审批门只管写工具。因此一旦把端点暴露到本机之外（`0.0.0.0`、反向代理、云主机），
全部项目数据对任何可达客户端可见。本模块提供一层最小、确定性的准入控制。

设计取舍
--------
- **纯 ASGI 中间件**，不用 Starlette 的 `BaseHTTPMiddleware`：后者会包一层
  anyio 任务组，对 streamable-HTTP 的流式/SSE 响应有干扰风险。
- **单静态 token**，不做 OAuth：MCP SDK 自带的 `auth=AuthSettings(...)` 强制要求
  `issuer_url` / `resource_server_url`，属 OAuth 资源服务器语义；对"一个账号一个
  token"是过度设计，且会额外暴露 OAuth 元数据端点。需要 OAuth 时改用 SDK 原生路径。
- **默认关闭**：token 为空即完全放行，保持本机开发与 stdio 用法零变化。
- **常量时间比较**（`hmac.compare_digest`），避免按字节比较泄漏 token 前缀。
- 401 带 `WWW-Authenticate: Bearer`，符合 HTTP 语义，便于客户端与反代识别。
"""

from __future__ import annotations

import hmac
import json

_UNAUTHORIZED_BODY = json.dumps(
    {"error": "unauthorized", "detail": "missing or invalid bearer token"}
).encode("utf-8")


def _extract_bearer(scope: dict) -> str | None:
    """从 ASGI scope 的请求头取 Bearer token（大小写不敏感，符合 HTTP 语义）。"""
    for name, value in scope.get("headers") or ():
        if name.lower() == b"authorization":
            try:
                raw = value.decode("latin-1").strip()
            except Exception:  # noqa: BLE001 - 头值非法一律视为未提供
                return None
            prefix = "bearer "
            if raw.lower().startswith(prefix):
                return raw[len(prefix):].strip()
            return None
    return None


class BearerTokenMiddleware:
    """要求 `Authorization: Bearer <token>`；不匹配返回 401。

    `token` 为空字符串时**完全放行**（未启用鉴权）——调用方据此决定是否安装本中间件。
    """

    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    async def __call__(self, scope, receive, send) -> None:
        # 只拦 HTTP；lifespan / websocket 原样透传
        if scope.get("type") != "http" or not self._token:
            await self.app(scope, receive, send)
            return

        presented = _extract_bearer(scope)
        if presented is not None and hmac.compare_digest(
            presented.encode("utf-8"), self._token
        ):
            await self.app(scope, receive, send)
            return

        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="reqmesh-harness"'),
                (b"content-length", str(len(_UNAUTHORIZED_BODY)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": _UNAUTHORIZED_BODY})


def wrap_with_bearer_auth(app, token: str):
    """按需包装 ASGI app：`token` 为空时原样返回，不引入任何行为变化。"""
    if not token:
        return app
    return BearerTokenMiddleware(app, token)


__all__ = ["BearerTokenMiddleware", "wrap_with_bearer_auth"]
