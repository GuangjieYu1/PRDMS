"""P4 #33 工具层：get_traceability_gap_report 契约 + 只读断言 + fail-fast + 过滤（MCP 路径）。

- schema 与 spec 契约表一致（project_id*、dimensions 可选 Literal 12 值枚举）；
- 只读：一次调用内部恰好 6 个 GET（六源），HTTP 方法 ⊆ {GET}，无其他请求；
- fail-fast：单源 500/404 → UpstreamError 透传（无部分报告）；
- G1 对账：summary == 同次运行的六源工具返回值；G2 缺口并集；G4 排序。
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response
from mcp.server.fastmcp.tools.base import Tool

from reqmesh_harness.errors import UpstreamError
from reqmesh_harness.report import DIMENSION_TYPES
from reqmesh_harness.tools import build_registry
from tests.conftest import HTTP_FIXTURES
from tests.test_tools import registry

SIX_SOURCES = {
    "/api/projects/cessna-172/coverage": "coverage.json",
    "/api/projects/cessna-172/gap-analysis": "gap_analysis.json",
    "/api/projects/cessna-172/traces": "traces.json",
    "/api/projects/cessna-172/suspect-links": "suspect_links.json",
    "/api/projects/cessna-172/unreviewed": "unreviewed.json",
    "/api/projects/cessna-172/allocation-matrix": "allocation_matrix.json",
}


def _fixture(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


def _mock_six(router) -> None:
    for path, fixture in SIX_SOURCES.items():
        router.get(path).mock(return_value=Response(200, json=_fixture(fixture)))


# ------------------------------------------------------------------ 注册表/schema
def test_registry_row() -> None:
    spec = registry().get("get_traceability_gap_report")
    assert spec.level == "READ"
    assert spec.domain == "复合技能"
    assert spec.description.startswith("READ-ONLY")  # ADR-0002 前缀惯例
    assert spec.title == "追踪/覆盖缺口报告"


def test_schema_contract() -> None:
    tool = Tool.from_function(
        registry().get("get_traceability_gap_report").fn,
        name="get_traceability_gap_report",
        description="x",
    )
    params = tool.parameters
    props = params["properties"]
    assert list(props.keys()) == ["project_id", "dimensions"]
    assert params["required"] == ["project_id"]
    assert props["project_id"]["type"] == "string"
    # dimensions: 可选 list[Literal[12 类维度]]（默认 None；nullable → anyOf[array|null]）
    dims = props["dimensions"]
    array_branch = next(b for b in dims["anyOf"] if b.get("type") == "array")
    assert array_branch["items"]["enum"] == list(DIMENSION_TYPES)
    assert dims.get("default") is None


def test_schema_rejects_bogus_dimension_at_call_boundary() -> None:
    from pydantic import ValidationError

    tool = Tool.from_function(
        registry().get("get_traceability_gap_report").fn,
        name="get_traceability_gap_report",
        description="x",
    )
    model = tool.fn_metadata.arg_model
    with pytest.raises(ValidationError):
        model.model_validate(
            {"project_id": "cessna-172", "dimensions": ["bogus.dimension"]}
        )


# ------------------------------------------------------------------ 只读 + 六源路由
def test_only_six_gets_inside_single_call(reqmesh_env) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        result = registry().call("get_traceability_gap_report", project_id="cessna-172")
        calls = list(router.calls)  # respx 在 mock 退出时清空 calls——须在块内采集
    assert result["project_id"] == "cessna-172"
    assert result["generated_at"]
    assert len(calls) == 6  # 恰好六源，无其他请求
    assert {c.request.url.path for c in calls} == set(SIX_SOURCES)
    assert {c.request.method for c in calls} == {"GET"}  # 只读断言
    # 六源之外零请求：无 list_requirements / quality / 任何写端点
    for c in calls:
        assert c.request.url.path in SIX_SOURCES


def test_summary_matches_source_tools_same_run(reqmesh_env) -> None:
    """G1：报告 summary == 同次运行六源工具返回值（跨源自洽，恒真抗漂移）。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        tools = build_registry()
        cov = tools.call("get_coverage", project_id="cessna-172")
        gap = tools.call("get_gap_analysis", project_id="cessna-172")
        trc = tools.call("get_traces", project_id="cessna-172")
        sus = tools.call("get_suspect_links", project_id="cessna-172")
        unrev = tools.call("get_unreviewed_requirements", project_id="cessna-172")
        alloc = tools.call("get_allocation_matrix", project_id="cessna-172")
        report = tools.call("get_traceability_gap_report", project_id="cessna-172")
    s = report["summary"]
    assert s["requirements_total"] == gap["total"]
    assert (
        s["coverage"]["total"],
        s["coverage"]["shallow_covered"],
        s["coverage"]["deep_covered"],
        s["coverage"]["coverage_pct"],
        s["coverage"]["deep_pct"],
    ) == (
        cov["total"],
        cov["shallow_covered"],
        cov["deep_covered"],
        cov["coverage_pct"],
        cov["deep_pct"],
    )
    assert s["gap_analysis"] == {"total": gap["total"], "gaps": gap["gaps"]}
    assert s["traces"]["links"] == len(trc["links"])
    assert s["suspect_links"]["count"] == sus["count"]
    assert s["unreviewed"]["count"] == len(unrev["items"])
    assert s["unreviewed"]["never"] == sum(
        1 for i in unrev["items"] if i.get("reviewed") is None
    )
    assert s["unreviewed"]["stale"] == sum(
        1
        for i in unrev["items"]
        if i.get("reviewed") is not None
        and i.get("reviewed") != i.get("current_fingerprint")
    )
    assert s["allocation"]["rows"] == len(alloc["rows"])
    assert s["allocation"]["unallocated"] == sum(
        1 for r in alloc["rows"] if not r.get("allocated_to")
    )


def test_master_gap_ids_union(reqmesh_env) -> None:
    """G2：master gaps id 集合 == 六源缺口 id 并集（无丢失、无编造）。"""
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        tools = build_registry()
        cov = tools.call("get_coverage", project_id="cessna-172")
        gap = tools.call("get_gap_analysis", project_id="cessna-172")
        sus = tools.call("get_suspect_links", project_id="cessna-172")
        unrev = tools.call("get_unreviewed_requirements", project_id="cessna-172")
        alloc = tools.call("get_allocation_matrix", project_id="cessna-172")
        report = tools.call("get_traceability_gap_report", project_id="cessna-172")
    ids: set[str] = set()
    for item in cov["items"]:
        if (
            item.get("uncovered_types")
            or item.get("broken_chain")
            or item.get("unwanted_coverage")
        ):
            ids.add(item["id"])
    ids.update(i["id"] for i in gap["items"])
    ids.update(l["target"] for l in sus["links"])
    ids.update(i["id"] for i in unrev["items"])
    ids.update(
        r.get("req_id") or r.get("row_id")
        for r in alloc["rows"]
        if not r.get("allocated_to")
    )
    assert {g["id"] for g in report["gaps"]} == ids
    # 排序：三重键（G4）
    from reqmesh_harness.report import SEVERITY_RANK

    gaps = report["gaps"]
    for prev, cur in zip(gaps, gaps[1:]):
        key = lambda g: (
            -SEVERITY_RANK[g["max_severity"]],
            -len(g["dimensions"]),
            g["id"],
        )
        assert key(prev) <= key(cur)


def test_dimensions_filter_gaps_and_chapters_summary_full(reqmesh_env) -> None:
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        tools = build_registry()
        full = tools.call("get_traceability_gap_report", project_id="cessna-172")
        filtered = tools.call(
            "get_traceability_gap_report",
            project_id="cessna-172",
            dimensions=["review.never", "review.stale"],
        )
    assert filtered["summary"] == full["summary"]  # summary 全量
    assert filtered["meta"]["filters"] == {
        "dimensions": ["review.never", "review.stale"]
    }
    for g in filtered["gaps"]:
        assert {d["type"] for d in g["dimensions"]} <= {"review.never", "review.stale"}
    # 全部 gaps 仅剩 review 维度条目
    assert all(g["max_severity"] == "medium" for g in filtered["gaps"])
    assert filtered["chapters"]["coverage"]["items"] == []
    assert (
        filtered["chapters"]["traces"]["items"] == full["chapters"]["traces"]["items"]
    )


# ------------------------------------------------------------------ fail-fast
@pytest.mark.parametrize("status", [500, 404])
def test_fail_fast_upstream_error(reqmesh_env, status) -> None:
    # assert_all_called=False：fail-fast 在 suspect-links 即整体报错，后两源本就不应被调用
    with respx.mock(base_url="http://reqmesh.test", assert_all_called=False) as router:
        _mock_six(router)
        router.get("/api/projects/cessna-172/suspect-links").mock(
            return_value=Response(status, json={"detail": "boom"})
        )
        with pytest.raises(UpstreamError) as exc:
            registry().call("get_traceability_gap_report", project_id="cessna-172")
    assert exc.value.status_code == status


def test_readonly_client_still_only_get(reqmesh_env) -> None:
    """结构只读（P1 资产回归）：ReadOnlyClient 仅有 get——报告工具只经它取数。"""
    from reqmesh_harness.client.reader import ReadOnlyClient

    public = [m for m in dir(ReadOnlyClient) if not m.startswith("_")]
    assert public == ["get"]


def test_mapping_row_registered(reqmesh_env) -> None:
    from tests.mapping import by_name

    tm = by_name()["get_traceability_gap_report"]
    assert tm.domain == "复合技能" and tm.level == "READ"
    assert [p.name for p in tm.params] == ["project_id", "dimensions"]
