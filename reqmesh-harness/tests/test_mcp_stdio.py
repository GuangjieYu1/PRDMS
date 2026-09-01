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
WRITE_ROUTES = {
    "POST /api/projects/cessna-172/requirements": "requirement_get.json",
}


@pytest.fixture
def stub():
    server = StubServer(HTTP_FIXTURES, routes=ROUTES, write_routes=WRITE_ROUTES)
    yield server
    server.stop()


@pytest.mark.asyncio
async def test_stdio_write_tool_via_mcp(stub, tmp_path) -> None:
    """#19 验收：create_requirement 经完整 MCP 路径可调用（审批门 → 审计 → 真实写）。"""
    approvals = tmp_path / "approvals.toml"
    approvals.write_text('[[approvals]]\ntool = "create_requirement"\nproject = "cessna-172"\n', encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "REQMESH_BASE_URL": stub.url,
            "REQMESH_USERNAME": "dev",
            "REQMESH_PASSWORD": "dev-pass",
            "REQMESH_TOKEN": "",
            "REQMESH_SESSION_FILE": str(tmp_path / "session.json"),
            "REQMESH_APPROVALS_FILE": str(approvals),
            "REQMESH_AUDIT_FILE": str(tmp_path / "audit.jsonl"),
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
            assert "create_requirement" in {t.name for t in tools.tools}
            result = await session.call_tool(
                "create_requirement", {"project_id": "cessna-172", "id": "SMOKE-P2-001", "name": "Fuel"}
            )
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            fixture = json.loads((HTTP_FIXTURES / "requirement_get.json").read_text(encoding="utf-8"))
            assert payload == fixture
    # 真实写请求：路径/方法/CSRF 头 + 审计一行
    writes = [r for r in stub.requests if r[1] == "/api/projects/cessna-172/requirements" and r[0] == "POST"]
    assert len(writes) == 1
    headers = stub.headers()[stub.requests.index(writes[0])]
    assert headers.get("X-CSRF-Token") == "csrf-body-token"
    bodies = [b for b in stub.bodies() if b"SMOKE-P2-001" in b]
    assert bodies and json.loads(bodies[0]) == {"id": "SMOKE-P2-001", "name": "Fuel"}
    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    row = json.loads(audit_lines[0])
    assert row["tool"] == "create_requirement"
    assert row["decision"] == "approved"
    assert row["result"] == "ok"
    assert row["upstream"] == {"method": "POST", "path": "/api/projects/cessna-172/requirements"}
    assert row["http_status"] == 200
    assert row["version"] == 1


@pytest.mark.asyncio
async def test_stdio_denied_write_is_tool_error(stub, tmp_path) -> None:
    """#18 验收：未批准写调用经 MCP 返回工具错误（fail-closed），不触达上游。"""
    empty_approvals = tmp_path / "approvals.toml"
    empty_approvals.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "REQMESH_BASE_URL": stub.url,
            "REQMESH_USERNAME": "dev",
            "REQMESH_PASSWORD": "dev-pass",
            "REQMESH_TOKEN": "",
            "REQMESH_SESSION_FILE": str(tmp_path / "session.json"),
            "REQMESH_APPROVALS_FILE": str(empty_approvals),
            "REQMESH_AUDIT_FILE": str(tmp_path / "audit.jsonl"),
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
            await session.list_tools()
            result = await session.call_tool(
                "create_requirement", {"project_id": "cessna-172", "id": "SMOKE-P2-001"}
            )
            assert result.isError is True
            assert "审批门拒绝" in result.content[0].text
    # 未触达任何写端点；审计记 denied
    assert [r for r in stub.requests if r[0] in ("POST", "PUT") and "/api/projects" in r[1]] == []
    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["decision"] == "denied"


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
            assert len(names) == 37
            assert names == sorted(s.name for s in build_registry().all())
            specs = {s.name: s for s in build_registry().all()}
            for t in tools.tools:
                level = specs[t.name].level
                prefix = {"READ": "READ-ONLY", "DRAFT": "DRAFT", "MUTATE": "MUTATE", "ADMIN": "ADMIN"}[level]
                assert t.description.startswith(prefix), t.name
                assert bool(t.annotations.readOnlyHint) is (level == "READ"), t.name
                assert bool(t.annotations.destructiveHint) is (level == "ADMIN"), t.name
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
