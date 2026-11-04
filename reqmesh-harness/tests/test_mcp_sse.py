"""SSE 端点 + 路径 token：给只能填"服务地址"、无自定义 header 的客户端。

背景（实测依据）：通义灵码 / Qoder CN 的 SSE 配置只有"名称 + 服务地址"两个字段，
**没有自定义 header**（官方文档：仅 STDIO 与 SSE）。因此把凭据放进 URL 路径：
`GET /mcp/<path-token>/sse`。

本文件锁住三件容易退化的行为：

1. 路径 token 的准入判定（对/错/缺失，且配置后 fail-closed）；
2. `sse_app()` **不能**传 mount_path——`SseServerTransport` 自己拼 `root_path`，
   重复传会宣告出 `/mcp/<t>/mcp/<t>/messages/`，客户端 POST 必然 404；
3. 外层 Starlette 必须接管 streamable app 的 lifespan——否则首个请求抛
   `RuntimeError: Task group is not initialized. Make sure to use run()`。
"""

from __future__ import annotations

import asyncio

import pytest
from mcp import ClientSession
from mcp.client.sse import sse_client
from starlette.applications import Starlette

from reqmesh_harness.mcp_auth import BearerTokenMiddleware, wrap_with_bearer_auth

# --------------------------------------------------------------------------- #
# 中间件层：路径 token 与 Bearer 头的判定
# --------------------------------------------------------------------------- #


def _middleware(token: str, path_token: str):
    """构造"内层 app 恒回 200"的中间件，便于只观察准入判定。"""

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return BearerTokenMiddleware(inner, token, path_token)


async def _call(mw, path: str, headers: list[tuple[bytes, bytes]] | None = None) -> int:
    """驱动一次最小 ASGI 请求，返回状态码（放行 → 内层 200，拦截 → 401）。"""
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": path, "headers": headers or []}
    await mw(scope, receive, send)
    return sent[0]["status"]


def test_path_token_accepted() -> None:
    mw = _middleware("hdr", "ptok")
    assert asyncio.run(_call(mw, "/mcp/ptok/sse")) == 200


def test_path_token_rejected() -> None:
    mw = _middleware("hdr", "ptok")
    assert asyncio.run(_call(mw, "/mcp/wrong/sse")) == 401


def test_path_token_missing_segment() -> None:
    """`/mcp//sse` 这种空段不应被当成"空 token 匹配空配置"。"""
    mw = _middleware("hdr", "ptok")
    assert asyncio.run(_call(mw, "/mcp//sse")) == 401


def test_header_still_works_alongside_path_token() -> None:
    mw = _middleware("hdr", "ptok")
    hdrs = [(b"authorization", b"Bearer hdr")]
    assert asyncio.run(_call(mw, "/mcp", hdrs)) == 200


def test_fail_closed_when_only_path_token_configured() -> None:
    """只配路径 token 时，/mcp 无凭据也必须 401——不能因"另一个 token 没配"而放行。"""
    mw = _middleware("", "ptok")
    assert asyncio.run(_call(mw, "/mcp")) == 401
    assert asyncio.run(_call(mw, "/mcp/ptok/sse")) == 200


def test_passthrough_when_no_token_at_all() -> None:
    """两个 token 都为空 → wrap 不包装，行为零变化。"""

    async def app(scope, receive, send):  # pragma: no cover - 不应被包装
        raise AssertionError("不应进入下游")

    assert wrap_with_bearer_auth(app, "", "") is app


# --------------------------------------------------------------------------- #
# 应用组合层：路由与前缀
# --------------------------------------------------------------------------- #


def test_sse_routes_have_single_prefix(monkeypatch) -> None:
    """注册表里只出现一次 token 前缀（防止 mount_path 与 Mount 双重叠加）。"""
    from reqmesh_harness.server import _build_http_app, create_server

    mcp = create_server()
    app = _build_http_app(mcp, "ptok")
    assert isinstance(app, Starlette)
    paths = [getattr(r, "path", None) for r in app.routes if hasattr(r, "path")]
    assert "/mcp/ptok" in paths, paths


def test_no_path_token_returns_plain_streamable_app() -> None:
    """未配置路径 token → 原样返回 streamable app，不引入 SSE 路由。"""
    from reqmesh_harness.server import _build_http_app, create_server

    mcp = create_server()
    app = _build_http_app(mcp, "")
    assert not isinstance(app, Starlette) or all(
        "/sse" not in str(getattr(r, "path", "")) for r in getattr(app, "routes", [])
    )


# --------------------------------------------------------------------------- #
# 集成：真启 uvicorn + 真 SSE 客户端（锁住 lifespan 与路径前缀两处修复）
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sse_client_end_to_end(tmp_path, monkeypatch) -> None:
    """完整的 SSE 握手 + tools/list。

    这个用例同时覆盖两个**静默**缺陷：
    - 外层 Starlette 不接管 streamable lifespan → 首个请求 500（Task group 未初始化）；
    - `sse_app(mount_path=...)` 与外层 Mount 双重加前缀 → 客户端 POST 404。

    两者都不会在"构造 app"阶段报错，只有真跑一遍客户端才暴露，所以必须集成测。
    """
    from mcp.client.sse import sse_client

    from reqmesh_harness.server import _build_http_app, create_server
    from tests.support.uvicorn_run import serve_app, stop_app

    monkeypatch.setenv("REQMESH_BASE_URL", "http://127.0.0.1:9")  # 无需上游（只测协议）
    monkeypatch.setenv("REQMESH_USERNAME", "dev")
    monkeypatch.setenv("REQMESH_PASSWORD", "dev-pass")
    monkeypatch.setenv("REQMESH_TOKEN", "")
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.setenv("REQMESH_TIMEOUT", "5")
    from reqmesh_harness.tools.runtime import set_runtime

    set_runtime(None)

    path_token = "e2e-path-token"
    mcp = create_server()
    app = wrap_with_bearer_auth(_build_http_app(mcp, path_token), "", path_token)

    server, thread, port = serve_app(app)
    try:
        url = f"http://127.0.0.1:{port}/mcp/{path_token}/sse"
        async with sse_client(url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 41
    finally:
        stop_app(server, thread)


@pytest.mark.asyncio
async def test_sse_client_rejected_without_valid_path_token(tmp_path, monkeypatch) -> None:
    """路径 token 不对 → 握手阶段即失败（不会建立会话）。"""
    from mcp.client.sse import sse_client

    from reqmesh_harness.server import _build_http_app, create_server
    from tests.support.uvicorn_run import serve_app, stop_app

    monkeypatch.setenv("REQMESH_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("REQMESH_USERNAME", "dev")
    monkeypatch.setenv("REQMESH_PASSWORD", "dev-pass")
    monkeypatch.setenv("REQMESH_TOKEN", "")
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.setenv("REQMESH_TIMEOUT", "5")
    from reqmesh_harness.tools.runtime import set_runtime

    set_runtime(None)

    mcp = create_server()
    app = wrap_with_bearer_auth(_build_http_app(mcp, "real-token"), "", "real-token")

    server, thread, port = serve_app(app)
    try:
        url = f"http://127.0.0.1:{port}/mcp/wrong-token/sse"
        with pytest.raises(Exception):  # noqa: B017 - 具体异常类型由 httpx 决定
            async with sse_client(url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
    finally:
        stop_app(server, thread)
