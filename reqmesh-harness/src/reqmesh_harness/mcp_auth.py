"""MCP HTTP 端点的鉴权（可选，默认关闭）：Bearer 头 **或** 路径 token。

为什么需要
----------
MCP 协议本身没有认证层，而本 harness 的 READ 工具（28 个）**不受审批门保护**
——审批门只管写工具。因此一旦把端点暴露到本机之外（`0.0.0.0`、反向代理、云主机），
全部项目数据对任何可达客户端可见。本模块提供一层最小、确定性的准入控制。

两种凭据形态，对应两类客户端
----------------------------
1. **`Authorization: Bearer <token>`**（`REQMESH_MCP_TOKEN`）—— 给支持自定义请求头
   的客户端（如 DSH 的 streamable-HTTP）。
2. **URL 路径 token**（`REQMESH_MCP_PATH_TOKEN`）—— 给**只能填一个服务地址**的客户端。
   实测依据：通义灵码 / Qoder CN 的 SSE 配置项只有"名称 + 服务地址"两个字段，
   **没有自定义 header**（官方文档：仅支持 STDIO 与 SSE）。
   形如 `https://host/mcp/<path-token>/sse`。

   为什么不能把 token 放 query：SSE 握手时服务端在 `endpoint` 事件里宣告后续
   message POST 的路径；该路径**不含 query**，客户端照它发第二个请求时 token 就丢了，
   鉴权随即失败。放**路径**则子路径被继承，两个请求都带上凭据。

   代价：路径会进访问日志 / 代理日志 / 客户端历史，泄漏面大于请求头。因此建议
   **独立 token**——与 Bearer 那个分开，可独立轮换、独立废止。

设计取舍
--------
- **纯 ASGI 中间件**，不用 Starlette 的 `BaseHTTPMiddleware`：后者会包一层
  anyio 任务组，对 streamable-HTTP / SSE 的流式响应有干扰风险。
- **静态 token**，不做 OAuth：MCP SDK 自带的 `auth=AuthSettings(...)` 强制要求
  `issuer_url` / `resource_server_url`，属 OAuth 资源服务器语义；对"一个账号一个
  token"是过度设计，且会额外暴露 OAuth 元数据端点。需要 OAuth 时改用 SDK 原生路径。
- **默认关闭**：两个 token 都为空即完全放行，保持本机开发与 stdio 用法零变化。
- **fail-closed**：只要配置了任一 token，请求必须命中其中之一；不会因为
  "另一个 token 没配"而放行。
- **常量时间比较**（`hmac.compare_digest`），头与路径段一视同仁。
- 401 带 `WWW-Authenticate: Bearer`，符合 HTTP 语义，便于客户端与反代识别。
"""

from __future__ import annotations

import hmac
import json

_UNAUTHORIZED_BODY = json.dumps(
    {
        "error": "unauthorized",
        "detail": "missing or invalid credential (bearer header or path token)",
    }
).encode("utf-8")

#: 路径 token 所在的前缀：`/mcp/<token>/...`（SSE 端点挂在这个子路径下）
_PATH_PREFIX = "/mcp/"


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
    """要求 Bearer 头**或**路径 token；都不匹配返回 401。

    两个 token 都为空时**完全放行**（未启用鉴权）——调用方据此决定是否包装本中间件。
    """

    def __init__(self, app, token: str, path_token: str = "") -> None:
        self.app = app
        self._token = (token or "").encode("utf-8")
        self._path_token = (path_token or "").encode("utf-8")

    def _path_token_ok(self, path: str) -> bool:
        """校验 `/mcp/<path-token>/...` 的第一段是否等于配置的路径 token。"""
        if not self._path_token or not path.startswith(_PATH_PREFIX):
            return False
        segment = path[len(_PATH_PREFIX):].split("/", 1)[0]
        if not segment:
            return False
        return hmac.compare_digest(segment.encode("utf-8"), self._path_token)

    async def __call__(self, scope, receive, send) -> None:
        # 只拦 HTTP；lifespan / websocket 原样透传
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # 未启用鉴权：两个 token 都没配 → 完全放行
        if not self._token and not self._path_token:
            await self.app(scope, receive, send)
            return

        # 凭据一：URL 路径 token（给只能填服务地址的客户端）
        if self._path_token_ok(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        # 凭据二：Authorization: Bearer（给支持自定义头的客户端）
        presented = _extract_bearer(scope)
        if (
            self._token
            and presented is not None
            and hmac.compare_digest(presented.encode("utf-8"), self._token)
        ):
            await self.app(scope, receive, send)
            return

        # fail-closed：配了任一 token 就必须命中其中之一
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


def wrap_with_bearer_auth(app, token: str, path_token: str = ""):
    """按需包装 ASGI app：两个 token 都为空时原样返回，不引入任何行为变化。"""
    if not token and not path_token:
        return app
    return BearerTokenMiddleware(app, token, path_token)


__all__ = ["BearerTokenMiddleware", "wrap_with_bearer_auth"]
