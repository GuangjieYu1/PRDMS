"""#14 streamable-HTTP：ASGI app 启动 → list tools（与 stdio 对账）→ 调用工具（会话复用）。"""

from __future__ import annotations

import json

import pytest
from httpx import URL
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from reqmesh_harness.config import Settings
from reqmesh_harness.server import create_server
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import set_runtime
from tests.conftest import HTTP_FIXTURES
from tests.support.stub_server import StubServer
from tests.support.uvicorn_run import serve_app, stop_app

ROUTES = {
    "/api/projects/cessna-172/requirements": "requirements_list.json",
    "/api/auth/whoami": "whoami.json",
}


@pytest.fixture
def stub():
    server = StubServer(HTTP_FIXTURES, routes=ROUTES)
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_streamable_http_list_tools_and_call(stub, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("REQMESH_BASE_URL", stub.url)
    monkeypatch.setenv("REQMESH_USERNAME", "dev")
    monkeypatch.setenv("REQMESH_PASSWORD", "dev-pass")
    monkeypatch.setenv("REQMESH_TOKEN", "")
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(tmp_path / "session.json"))
    monkeypatch.setenv("REQMESH_TIMEOUT", "10")
    set_runtime(None)

    app = create_server().streamable_http_app()
    server, thread, port = serve_app(app)
    try:
        base = URL(f"http://127.0.0.1:{port}/mcp")
        async with streamable_http_client(base) as (read, write, get_session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert len(names) == 39
                # 与 stdio/注册集合对账
                assert names == sorted(s.name for s in build_registry().all())
                specs = {s.name: s for s in build_registry().all()}
                for t in tools.tools:
                    level = specs[t.name].level
                    prefix = {"READ": "READ-ONLY", "DRAFT": "DRAFT", "MUTATE": "MUTATE", "ADMIN": "ADMIN"}[level]
                    assert t.description.startswith(prefix), t.name
                    assert bool(t.annotations.readOnlyHint) is (level == "READ"), t.name
                    assert t.meta == {"domain": specs[t.name].domain, "permission": specs[t.name].level}, t.name
                for _ in range(2):
                    result = await session.call_tool("list_requirements", {"project_id": "cessna-172"})
                    assert result.isError is False
                    payload = json.loads(result.content[0].text)
                    fixture = json.loads(
                        (HTTP_FIXTURES / "requirements_list.json").read_text(encoding="utf-8")
                    )
                    assert payload == fixture
    finally:
        stop_app(server, thread)

    counts = stub.method_counts()
    # stateless HTTP：每个请求作用域构建会话，但会话文件共享——仅首次登录
    assert counts.get("POST") == 1
    assert counts.get("GET") == 2
    methods = {m for m, _, _ in stub.requests}
    assert methods == {"GET", "POST"}
    post_paths = {path for m, path, _ in stub.requests if m == "POST"}
    assert post_paths == {"/api/auth/login"}


@pytest.mark.asyncio
async def test_streamable_http_protocol_error_response(stub, tmp_path, monkeypatch) -> None:
    """违规请求（缺必要参数）→ MCP 工具错误（合规响应），服务端不崩溃。"""
    monkeypatch.setenv("REQMESH_BASE_URL", stub.url)
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(tmp_path / "s3.json"))
    set_runtime(None)
    app = create_server().streamable_http_app()
    server, thread, port = serve_app(app)
    try:
        async with streamable_http_client(URL(f"http://127.0.0.1:{port}/mcp")) as (read, write, _sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.list_tools()
                result = await session.call_tool("get_requirement", {"project_id": "cessna-172"})
                assert result.isError is True
    finally:
        stop_app(server, thread)


def test_cli_transport_mapping() -> None:
    """CLI --transport http → FastMCP 的 streamable-http（用户友好别名）。"""
    from reqmesh_harness.server import MCP_TRANSPORT

    assert MCP_TRANSPORT == {"stdio": "stdio", "http": "streamable-http"}


def test_cli_args_parse() -> None:
    from reqmesh_harness.server import parse_args

    ns = parse_args(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"])
    assert (ns.transport, ns.host, ns.port) == ("http", "0.0.0.0", 9000)
    ns2 = parse_args([])
    assert (ns2.transport, ns2.host, ns2.port) == ("stdio", None, None)


def test_host_port_configurable() -> None:
    """host/port 可配（默认 127.0.0.1:8123，支持 --host/--port 与环境变量）。"""
    mcp = create_server(Settings(harness_host="0.0.0.0", harness_port=9999))
    assert mcp.settings.host == "0.0.0.0"
    assert mcp.settings.port == 9999
