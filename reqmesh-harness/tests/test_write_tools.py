"""#19/#20/#21 写工具：schema 与映射表对账、请求 method/path/body、拒绝/批准/dry_run 三态、
MUTATE reason 必填且不进请求体、PUT 部分更新（exclude_unset + 显式 null）、dry_run 本地 checks。"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response
from mcp.server.fastmcp.tools.base import Tool

from reqmesh_harness.errors import ApprovalDeniedError, UpstreamError
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.groups import writes
from tests.conftest import HTTP_FIXTURES
from tests.mapping import WRITE_TOOLS, ToolMap, by_name, write_by_name
from tests.test_tools import assert_schema_matches_toolmap, registry


def _fixture(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


def _approve(monkeypatch, tmp_path, tool: str, project: str = "cessna-172") -> None:
    WhitelistStore(tmp_path / "approvals.toml").append(WhitelistEntry(tool=tool, project=project))


@pytest.mark.parametrize("toolmap", WRITE_TOOLS, ids=lambda t: t.name)
def test_write_schema_matches_mapping(toolmap: ToolMap) -> None:
    spec = registry().get(toolmap.name)
    assert_schema_matches_toolmap(spec, toolmap)


@pytest.mark.parametrize("toolmap", WRITE_TOOLS, ids=lambda t: t.name)
def test_write_case_method_path_body(toolmap: ToolMap, reqmesh_env, monkeypatch) -> None:
    """真实写：method/path/body 与映射表一致；CSRF 头；结果=上游响应透传。"""
    spec = registry().get(toolmap.name)
    case = next(c for c in toolmap.cases if not c.dry_run)
    fixture = _fixture(case.fixture)
    _approve(monkeypatch, reqmesh_env["session_file"].parent, toolmap.name)
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.route(method=case.method, path=case.expect_path).mock(return_value=Response(200, json=fixture))
        result = spec.fn(**case.args)
        assert result == fixture
        calls = [c for c in router.calls if c.request.url.path == case.expect_path]
        assert len(calls) == 1
        assert calls[0].request.method == case.method
        if case.expect_body is not None:
            assert json.loads(calls[0].request.content) == case.expect_body
        assert calls[0].request.headers.get("x-csrf-token") == "csrf-body-token"


@pytest.mark.parametrize("toolmap", WRITE_TOOLS, ids=lambda t: t.name)
def test_write_dry_run_no_real_request(toolmap: ToolMap, reqmesh_env, monkeypatch) -> None:
    """dry_run=true：批准后不发写请求，返回 {dry_run, would_send, checks} 包裹。"""
    import re

    spec = registry().get(toolmap.name)
    case = toolmap.cases[0]
    args = {**case.args, "dry_run": True}
    _approve(monkeypatch, reqmesh_env["session_file"].parent, toolmap.name)
    with respx.mock(base_url="http://reqmesh.test") as router:
        # 本地前置校验的 GET 一律 404（无引用冲突）
        router.get(re.compile(r".*")).mock(return_value=Response(404, json={"detail": "nf"}))
        result = spec.fn(**args)
    assert result["dry_run"] is True
    assert result["would_send"] == {
        "method": case.method,
        "path": case.expect_path,
        "body": case.expect_body,
    }
    assert isinstance(result["checks"], list)
    # 只发 GET（本地校验），未发出任何写请求
    assert all(c.request.method == "GET" for c in router.calls)


def test_write_denied_without_whitelist(reqmesh_env, monkeypatch) -> None:
    """fail-closed：无白名单 → ApprovalDeniedError，错误含修复建议，不发任何请求。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        with pytest.raises(ApprovalDeniedError) as exc:
            writes.create_requirement(project_id="cessna-172", id="SMOKE-P2-001")
        assert "approvals add create_requirement" in str(exc.value)
        assert router.calls == []  # 未批准即不触网


def test_mutate_reason_required_by_schema() -> None:
    """MUTATE 工具统一必填 reason（schema 层强制）。"""
    from pydantic import ValidationError

    tool = Tool.from_function(
        registry().get("update_requirement").fn, name="update_requirement", description="x"
    )
    model = tool.fn_metadata.arg_model
    with pytest.raises(ValidationError):
        model.model_validate({"project_id": "cessna-172", "req_id": "ACFT0000"})
    model.model_validate({"project_id": "cessna-172", "req_id": "ACFT0000", "reason": "r"})


def test_put_partial_update_exclude_unset_null_clears(reqmesh_env, monkeypatch) -> None:
    """PUT 部分更新：未提供字段不发送；显式 None 原样发送（清空语义）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent, "update_requirement")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.put("/api/projects/cessna-172/requirements/ACFT0000").mock(return_value=Response(200, json={}))
        writes.update_requirement(project_id="cessna-172", req_id="ACFT0000", reason="r", description=None)
        body = json.loads(router.calls[0].request.content)
    assert body == {"description": None}


def test_mutate_reason_never_in_request_body(reqmesh_env, monkeypatch) -> None:
    _approve(monkeypatch, reqmesh_env["session_file"].parent, "run_verification")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/verification/VCAF0001/run").mock(return_value=Response(200, json={}))
        writes.run_verification(project_id="cessna-172", vc_id="VCAF0001", status="passed", reason="机密理由X")
        body = json.loads(router.calls[0].request.content)
    assert "机密理由X" not in json.dumps(body, ensure_ascii=False)
    assert body == {"status": "passed"}


def test_dry_run_checks_conflict_and_missing_refs(reqmesh_env, monkeypatch) -> None:
    """create 类 dry_run 本地 checks：目标 id 已存在 → 冲突提示；引用 id 不存在 → 提示。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent, "create_requirement")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172/requirements/SMOKE-P2-001").mock(return_value=Response(200, json={}))
        router.get("/api/projects/cessna-172/requirements/nope-parent").mock(return_value=Response(404, json={"detail": "nf"}))
        router.get("/api/projects/cessna-172/verification/VCAF0001").mock(return_value=Response(200, json={}))
        result = writes.create_requirement(
            project_id="cessna-172", id="SMOKE-P2-001", parent="nope-parent",
            verification_cases=["VCAF0001"], dry_run=True,
        )
    kinds = {c["kind"] for c in result["checks"]}
    assert "id_conflict" in kinds
    assert "missing_reference" in kinds
    # 全部为 GET（本地校验不写库）
    assert all(c.request.method == "GET" for c in router.calls)
    assert result["checks"] != []


def test_dry_run_checks_missing_target(reqmesh_env, monkeypatch) -> None:
    """MUTATE 类 dry_run：目标实体不存在 → 提示；check 不阻断预览。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent, "update_requirement")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172/requirements/NO-SUCH").mock(return_value=Response(404, json={"detail": "nf"}))
        result = writes.update_requirement(
            project_id="cessna-172", req_id="NO-SUCH", reason="r", description="d", dry_run=True
        )
    assert result["checks"][0]["kind"] == "missing_target"
    assert result["checks"][0]["id"] == "NO-SUCH"


def test_dry_run_is_not_approval_bypass(reqmesh_env, monkeypatch) -> None:
    """dry-run 不是绕过审批的后门：未批准照样阻断（fail-closed）。"""
    with pytest.raises(ApprovalDeniedError):
        writes.create_requirement(project_id="cessna-172", id="SMOKE-P2-001", dry_run=True)


def test_upstream_error_passthrough(reqmesh_env, monkeypatch) -> None:
    """上游错误（envelope 形状）归一化为 UpstreamError 并透传。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent, "create_risk")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/risks").mock(
            return_value=Response(400, json={"error": "validation_error", "message": "bad id"})
        )
        with pytest.raises(UpstreamError) as exc:
            writes.create_risk(project_id="cessna-172", id="X")
    assert exc.value.status_code == 400
    assert "validation_error: bad id" in str(exc.value)


def test_create_comment_requires_fields_at_tool_layer() -> None:
    """上游 schema 未标 required，工具层强制 entity_kind/entity_id/text 必填。"""
    from pydantic import ValidationError

    tool = Tool.from_function(
        registry().get("create_comment").fn, name="create_comment", description="x"
    )
    model = tool.fn_metadata.arg_model
    with pytest.raises(ValidationError):
        model.model_validate({"project_id": "cessna-172"})
    model.model_validate({"project_id": "cessna-172", "entity_kind": "requirement",
                          "entity_id": "ACFT0000", "text": "hi"})
