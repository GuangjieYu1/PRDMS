"""#27/#28/#29 复合技能工具：draft_requirement 三终态 + 门/审计/409 + 弱词修正闭环；
get_requirement_quality 过滤与缺失两态；注册表/导出对账由既有测试套件覆盖（39 工具）。

全部离线（respx 打桩）；金样例文本来自 spec ⑥。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import respx
from httpx import Response
from mcp.server.fastmcp.tools.base import Tool

from reqmesh_harness.errors import ApprovalDeniedError, InputParseError, UpstreamError
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools import build_registry
from tests.conftest import HTTP_FIXTURES
from tests.test_tools import registry

G1 = "The aircraft shall achieve a range of at least 1185 km at maximum cruise power."
G5 = "If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s."


def _fixture(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


def _approve(monkeypatch, tmp_path, tool: str = "draft_requirement", project: str | None = None) -> None:
    WhitelistStore(Path(tmp_path) / "approvals.toml").append(WhitelistEntry(tool=tool, project=project))


def _audit(reqmesh_env) -> list[dict]:
    return AuditLog(Path(reqmesh_env["session_file"]).parent / "audit.jsonl").read_all()


def _mock_common(router, quality=True) -> None:
    """写前只读探访：/quality config + next-uid + 本地校验 GET 404（无引用冲突）。"""
    if quality:
        router.get("/api/projects/cessna-172/quality").mock(return_value=Response(200, json=_fixture("report_quality.json")))
    router.get("/api/projects/cessna-172/requirements/next-uid").mock(return_value=Response(200, json=_fixture("next_uid.json")))
    router.get(re.compile(r".*")).mock(return_value=Response(404, json={"detail": "nf"}))


# ------------------------------------------------------------------ 工具契约与三终态
def test_draft_requirement_dry_run_no_write(reqmesh_env, monkeypatch) -> None:
    """dry_run=true：过线后仍走审批门、返回 would_send（与映射模板一致）、零写请求。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        result = registry().call("draft_requirement", project_id="cessna-172", nl_text=G1, id="SMOKE-P3-001", dry_run=True)
    assert result["persisted"] is False and result["dry_run"] is True
    assert result["ears"] == {"template": "ubiquitous", "sentence": G1, "system": "aircraft"}
    assert result["lint"]["passed"] is True
    assert result["lint"]["score"] == 100
    assert result["lint"]["rounds"] == 1
    assert result["lint"]["config_source"] == "project"
    assert result["would_send"]["method"] == "POST"
    assert result["would_send"]["path"] == "/api/projects/cessna-172/requirements"
    assert result["would_send"]["body"] == {
        "id": "SMOKE-P3-001",
        "type": "functional",
        "name": "Achieve a range of at least 1185 km at maximum cruise power",
        "description": G1,
        "priority": "medium",
        "status": "proposed",
        "rationale": "自然语言建需求（draft_requirement）：" + G1,
        "source": "",
    }
    assert result["checks"] == []
    assert all(c.request.method == "GET" for c in router.calls)  # 零写请求


def test_draft_requirement_persisted(reqmesh_env, monkeypatch) -> None:
    """真实写：POST body 与映射模板一致；returns 201 实体；审计含 lint_score/lint_rounds。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    sent: dict = {}

    def capture(request) -> Response:
        sent.update(json.loads(request.content))
        return Response(201, json=sent)

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call("draft_requirement", project_id="cessna-172", nl_text=G1, id="SMOKE-P3-001")
    assert result["persisted"] is True
    assert result["requirement"]["id"] == "SMOKE-P3-001"
    assert result["lint"]["passed"] is True and result["lint"]["score"] == 100
    assert sent["description"] == G1  # 纯文本原样（sanitize 后冒烟另断言）
    assert sent["status"] == "proposed"
    row = _audit(reqmesh_env)[-1]
    assert row["tool"] == "draft_requirement"
    assert row["level"] == "DRAFT"
    # P2 摘要语义：标量摘要化为字符串（lint_score/lint_rounds 值仍为整数语义）
    assert row["params_summary"]["lint_score"] == "100"
    assert row["params_summary"]["lint_rounds"] == "1"
    assert row["upstream"] == {"method": "POST", "path": "/api/projects/cessna-172/requirements"}


def test_draft_requirement_denied_fail_closed(reqmesh_env, monkeypatch) -> None:
    """空白名单 fail-closed：ApprovalDeniedError + 审计 denied + 无写请求。"""
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        with pytest.raises(ApprovalDeniedError) as exc:
            registry().call("draft_requirement", project_id="cessna-172", nl_text=G1, dry_run=True)
        assert "approvals add draft_requirement" in str(exc.value)
        assert all(c.request.method == "GET" for c in router.calls)
    row = _audit(reqmesh_env)[-1]
    assert row["decision"] == "denied" and row["result"] == "blocked"


def test_draft_requirement_not_passed_no_audit_no_write(reqmesh_env, monkeypatch) -> None:
    """未过线（无可度量数字）：persisted=false + hint + would_send；不记审计、无写请求。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    before = len(_audit(reqmesh_env))
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall provide a user manual for the operator.", id="SMOKE-P3-X",
        )
    assert result["persisted"] is False
    assert result["lint"]["passed"] is False
    assert "untestable" in {f["rule"] for f in result["lint"]["findings"]}
    assert "require_measurable" in result["hint"]
    assert result["would_send"]["body"]["id"] == "SMOKE-P3-X"
    assert len(_audit(reqmesh_env)) == before  # 未达写路径：不记审计
    assert all(c.request.method == "GET" for c in router.calls)


def test_draft_requirement_placeholder_immediate_stop(reqmesh_env, monkeypatch) -> None:
    """placeholder（error）→ 立即终止（rounds==1、不尝试修正、不落库）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall support TBD configuration.", require_measurable=False,
        )
    assert result["persisted"] is False
    assert result["lint"]["rounds"] == 1
    assert any(f["rule"] == "placeholder" and f["severity"] == "error" for f in result["lint"]["findings"])
    assert "占位符" in result["hint"]
    assert all(c.request.method == "GET" for c in router.calls)


def test_draft_requirement_weak_word_fix_loop(reqmesh_env, monkeypatch) -> None:
    """弱词/冗余：≤N 轮确定性修正后过线（persisted 描述为修正后的 EARS 句）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    sent: dict = {}

    def capture(request) -> Response:
        sent.update(json.loads(request.content))
        return Response(201, json={**sent, "id": "SMOKE-P3-X"})

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall have the ability to warn the pilot.",
            id="SMOKE-P3-X", require_measurable=False,
        )
    assert result["persisted"] is True
    assert result["lint"]["rounds"] == 2  # 初始 1 轮 + 修正后 1 轮
    assert result["ears"]["sentence"] == "The aircraft shall warn the pilot."
    # 修正后的文本进入写面
    assert "superfluous_infinitive" not in {f["rule"] for f in result["lint"]["findings"]}
    assert sent["description"] == "The aircraft shall warn the pilot."


def test_draft_requirement_should_obligation_normalized(reqmesh_env, monkeypatch) -> None:
    """should 作义务位：解析接受（渲染归一为 shall），弱词修正后落库（spec ④ 闭环）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    sent: dict = {}

    def capture(request) -> Response:
        sent.update(json.loads(request.content))
        return Response(201, json={**sent, "id": "SMOKE-P3-X"})

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft should warn within 1 s.",
            id="SMOKE-P3-X", require_measurable=False,
        )
    assert result["persisted"] is True
    # 渲染归一 + 弱词修正 → 落库文本为 shall 句式
    assert sent["description"] == "The aircraft shall warn within 1 s."
    assert result["ears"]["sentence"] == "The aircraft shall warn within 1 s."


def test_draft_requirement_converged_not_passed(reqmesh_env, monkeypatch) -> None:
    """残余不可确定性修正（形容词类弱词）→ 收敛即终止：persisted=false + 收敛 hint。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall be a fast and robust platform.", id="SMOKE-P3-X",
            require_measurable=False,
        )
    assert result["persisted"] is False
    assert result["lint"]["passed"] is False
    assert "收敛" in result["hint"]
    assert all(c.request.method == "GET" for c in router.calls)  # 无写请求


def test_draft_requirement_max_rounds_exhausted(reqmesh_env, monkeypatch) -> None:
    """N 轮上限（REQMESH_LINT_MAX_ROUNDS=1）→ 未过线 persisted=false（终止语义）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    monkeypatch.setenv("REQMESH_LINT_MAX_ROUNDS", "1")
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall have the ability to warn the pilot.", id="SMOKE-P3-X",
            require_measurable=False,
        )
    assert result["persisted"] is False
    assert result["lint"]["rounds"] == 1
    assert result["lint"]["passed"] is False
    assert all(c.request.method == "GET" for c in router.calls)


def test_draft_requirement_unwanted_negation_residual_persists(reqmesh_env, monkeypatch) -> None:
    """unwanted 句式残余白名单（negation）：过线并落库（EARS 与 R16 张力不反转语义）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    sent: dict = {}

    def capture(request) -> Response:
        sent.update(json.loads(request.content))
        return Response(201, json={**sent, "id": "SMOKE-P3-X"})

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="If the engine fails, then the aircraft shall not start after 2 s.",
            id="SMOKE-P3-X",
        )
    assert result["persisted"] is True
    rules = {f["rule"] for f in result["lint"]["findings"]}
    assert "negation" in rules
    assert result["lint"]["residual_findings"] and result["lint"]["residual_findings"][0]["rule"] == "negation"
    assert sent["description"] == "IF the engine fails, THEN the aircraft shall not start after 2 s."


def test_draft_requirement_409_retries_next_uid(reqmesh_env, monkeypatch) -> None:
    """自动 id 的并发冲突：POST 409 → 重取 next-uid（递增）→ 重试一次（两次 POST）。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    posts: list[bytes] = []
    uid = {"n": 0}

    def next_uid(request) -> Response:
        uid["n"] += 1
        return Response(200, json={"prefix": "REQ", "next_id": f"REQ{uid['n']:04d}"})

    def capture(request) -> Response:
        posts.append(request.content)
        if len(posts) == 1:
            return Response(409, json={"detail": "id conflict"})
        return Response(201, json=json.loads(request.content))

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.get("/api/projects/cessna-172/requirements/next-uid").mock(side_effect=next_uid)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call("draft_requirement", project_id="cessna-172", nl_text=G1)
    assert result["persisted"] is True
    assert result["requirement"]["id"] == "REQ0002"  # 409 后重取一次
    assert len(posts) == 2
    assert json.loads(posts[0])["id"] == "REQ0001"
    assert json.loads(posts[1])["id"] == "REQ0002"
    # 审计两行（每次到达 write_request 一行）
    rows = _audit(reqmesh_env)
    assert rows[-1]["result"] == "ok" and rows[-2]["result"] == "upstream_error"


def test_draft_requirement_explicit_id_conflict_passthrough(reqmesh_env, monkeypatch) -> None:
    """显式 id 的 409：不重取（调用方意图），照 P2 透传 UpstreamError。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(
            return_value=Response(409, json={"detail": "exists"})
        )
        with pytest.raises(UpstreamError) as exc:
            registry().call("draft_requirement", project_id="cessna-172", nl_text=G1, id="SMOKE-P3-001")
    assert exc.value.status_code == 409


def test_draft_requirement_not_passed_next_uid_failure_graceful(reqmesh_env, monkeypatch) -> None:
    """未过线 + 自动 id 获取失败：返回未过线报告（would_send=None + hint），不抛上游错误。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        router.get("/api/projects/cessna-172/quality").mock(return_value=Response(200, json=_fixture("report_quality.json")))
        router.get(re.compile(r".*")).mock(return_value=Response(502, json={"detail": "boom"}))
        result = registry().call(
            "draft_requirement", project_id="cessna-172",
            nl_text="The aircraft shall provide a manual for the operator.",
        )
    assert result["persisted"] is False
    assert result["lint"]["passed"] is False
    assert result["would_send"] is None
    assert "id 预览不可用" in result["hint"]
    assert all(c.request.method == "GET" for c in router.calls)  # 无写请求


def test_draft_requirement_parse_failure_no_audit(reqmesh_env, monkeypatch) -> None:
    """中文输入 → InputParseError；不发写请求、不记审计。"""
    before = len(_audit(reqmesh_env))
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        with pytest.raises(InputParseError):
            registry().call("draft_requirement", project_id="cessna-172", nl_text="飞机应在 2 秒内显示告警")
        assert router.calls == []  # 解析失败即不触网
    assert len(_audit(reqmesh_env)) == before


def test_draft_requirement_bullet_overrides_and_param_precedence(reqmesh_env, monkeypatch) -> None:
    """要点行内覆盖（type/priority/parent/subject/name）+ 显式参数优先级。"""
    _approve(monkeypatch, reqmesh_env["session_file"].parent)
    sent: dict = {}

    def capture(request) -> Response:
        sent.update(json.loads(request.content))
        return Response(201, json=sent)

    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_common(router)
        router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
        result = registry().call(
            "draft_requirement",
            project_id="cessna-172",
            nl_text="if: the cabin door is unlatched\nresponse: display a door warning within 1 s\n"
                    "type: safety\npriority: high\nparent: ACFT0000\nsubject: cabin door\nname: Door warning",
            id="SMOKE-P3-001", priority="critical",
        )
    assert result["persisted"] is True
    assert sent["type"] == "safety" and sent["priority"] == "critical"  # 参数 > 要点
    assert sent["parent"] == "ACFT0000" and sent["subject"] == "cabin door"
    assert sent["name"] == "Door warning"
    assert result["ears"]["template"] == "unwanted"


def test_draft_requirement_invalid_bullet_enum_rejected(reqmesh_env, monkeypatch) -> None:
    """要点 type/priority 非法值 → InputParseError。"""
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        with pytest.raises(InputParseError):
            registry().call(
                "draft_requirement", project_id="cessna-172",
                nl_text="response: display a warning\ntype: bogus", dry_run=True,
            )
        assert router.calls == []


def test_draft_requirement_schema_contract() -> None:
    """工具 schema 与 spec 契约表一致（参数/枚举/默认值）。"""
    tool = Tool.from_function(
        registry().get("draft_requirement").fn, name="draft_requirement", description="x"
    )
    props = tool.parameters["properties"]
    assert props["template"]["enum"] == ["auto", "ubiquitous", "event", "unwanted", "state", "optional"]
    assert props["template"]["default"] == "auto"
    assert props["require_measurable"]["default"] is True
    assert props["dry_run"]["default"] is False
    assert props["nl_text"]["type"] == "string"
    assert set(tool.parameters.get("required", [])) == {"project_id", "nl_text"}


# ------------------------------------------------------------------ get_requirement_quality
def test_get_requirement_quality_found(reqmesh_env, monkeypatch) -> None:
    """服务端反馈：/quality 过滤出目标需求（含 findings）与项目上下文字段。"""
    fixture = _fixture("report_quality.json")
    target = next(r for r in fixture["per_requirement"] if r["id"] == "SAFE0004")
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        router.get("/api/projects/cessna-172/quality").mock(return_value=Response(200, json=fixture))
        result = registry().call("get_requirement_quality", project_id="cessna-172", req_id="SAFE0004")
    assert result == {
        "id": "SAFE0004",
        "name": target["name"],
        "score": target["score"],
        "findings": target["findings"],
        "average": fixture["average"],
        "total": fixture["total"],
    }


def test_get_requirement_quality_missing(reqmesh_env, monkeypatch) -> None:
    """目标不存在：相关字段为 null（average/total 上下文保留）。"""
    fixture = _fixture("report_quality.json")
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        router.get("/api/projects/cessna-172/quality").mock(return_value=Response(200, json=fixture))
        result = registry().call("get_requirement_quality", project_id="cessna-172", req_id="NO-SUCH")
    assert result["id"] == "NO-SUCH"
    assert result["name"] is None and result["score"] is None and result["findings"] is None
    assert result["average"] == fixture["average"] and result["total"] == fixture["total"]


def test_get_requirement_quality_description_prefix() -> None:
    """READ 工具 description 以 READ-ONLY 开头（ADR-0002 前缀惯例）。"""
    spec = registry().get("get_requirement_quality")
    assert spec.description.startswith("READ-ONLY")
