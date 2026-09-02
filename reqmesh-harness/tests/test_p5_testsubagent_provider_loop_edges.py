"""P5 测试子代理补充用例（provider 契约 / loop 内核 / FakeProvider 边缘）：验收 1/2/6/7 的未覆盖分支。

- assemble_request：max_rounds=None → 兜底 8；history=None → 空列表；
- ToolStep 参数默认（args 空 dict / expect_ok True / expect_text None）；
- executor：UpstreamError → 工具错误文本（ok=False），与 ApprovalDeniedError 同形态（spec ⑦）。

全部离线（respx + 注入）；不改动既有测试与 src/。
"""

from __future__ import annotations

import respx
from httpx import Response

from reqmesh_harness.runtime.fake import ToolStep
from reqmesh_harness.runtime.loop import ToolExecutor, assemble_request
from reqmesh_harness.runtime.provider import ProjectContext
from reqmesh_harness.tools import build_registry

CTX = ProjectContext(project_id="cessna-172", base_url="http://reqmesh.test", created_at="2026-01-01T00:00:00Z")


def test_assemble_request_max_rounds_defaults_when_none() -> None:
    req = assemble_request("t", project_context=None, history=None,
                           registry=build_registry(), max_rounds=None)
    assert req.max_rounds == 8  # MAX_ROUNDS_DEFAULT 兜底（spec ③）


def test_assemble_request_history_none_becomes_empty_list() -> None:
    req = assemble_request("t", project_context=None, history=None,
                           registry=build_registry())
    assert req.history == []


def test_tool_step_args_and_expect_defaults() -> None:
    step = ToolStep("whoami")
    assert step.args == {}
    assert step.expect_ok is True
    assert step.expect_text is None


def test_executor_upstream_error_maps_to_tool_error_text(reqmesh_env, monkeypatch) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/auth/whoami").mock(return_value=Response(500, json={"detail": "boom"}))
        ex = ToolExecutor(registry=build_registry())
        result = ex("whoami", {}, None)
    assert result.ok is False
    assert "UpstreamError" in result.text
    assert "500" in result.text
