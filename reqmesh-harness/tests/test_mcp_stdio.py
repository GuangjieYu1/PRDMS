"""#9 MCP stdio：子进程启动 → list tools → 调用 list_requirements（打桩后端）。"""

from __future__ import annotations

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from reqmesh_harness.tools import build_registry
from tests.conftest import HTTP_FIXTURES
from tests.support.stub_server import StubServer

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
async def test_stdio_list_tools_and_call_requirement(stub, tmp_path) -> None:
    env = dict(os.environ)
    env.update(
        {
            "REQMESH_BASE_URL": stub.url,
            "REQMESH_USERNAME": "dev",
            "REQMESH_PASSWORD": "dev-pass",
            "REQMESH_TOKEN": "",
            "REQMESH_SESSION_FILE": str(tmp_path / "session.json"),
            "REQMESH_TIMEOUT": "10",
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "reqmesh_harness.server", "--transport", "stdio"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            assert len(names) == 25
            assert names == sorted(s.name for s in build_registry().all())
            specs = {s.name: s for s in build_registry().all()}
            for t in tools.tools:
                assert t.description.startswith("READ-ONLY"), t.name
                assert t.annotations.readOnlyHint is True, t.name
                # 分组/层级经 meta 随协议下发（对客户端可见），且与注册表同源
                assert t.meta == {"domain": specs[t.name].domain, "permission": specs[t.name].level}, t.name
            result = await session.call_tool("list_requirements", {"project_id": "cessna-172"})
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            fixture = json.loads((HTTP_FIXTURES / "requirements_list.json").read_text(encoding="utf-8"))
            assert payload == fixture
    counts = stub.method_counts()
    assert counts.get("POST") == 1  # 启动即登录一次
    assert counts.get("GET", 0) == 1  # list_requirements
    # 只读口径：除登录外全部为 GET
    methods = {m for m, _, _ in stub.requests}
    assert methods == {"GET", "POST"}
    post_paths = {path for m, path, _ in stub.requests if m == "POST"}
    assert post_paths == {"/api/auth/login"}


@pytest.mark.asyncio
async def test_stdio_missing_project_id_is_tool_error(stub, tmp_path) -> None:
    env = dict(os.environ)
    env.update(
        {
            "REQMESH_BASE_URL": stub.url,
            "REQMESH_USERNAME": "dev",
            "REQMESH_PASSWORD": "dev-pass",
            "REQMESH_TOKEN": "",
            "REQMESH_SESSION_FILE": str(tmp_path / "session2.json"),
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "reqmesh_harness.server", "--transport", "stdio"],
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.list_tools()
            result = await session.call_tool("list_requirements", {})
            assert result.isError is True
