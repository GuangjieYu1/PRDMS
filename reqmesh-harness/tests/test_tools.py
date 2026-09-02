"""#9–#13 工具层契约测试：注册表对账、schema 与映射表一致、只读、envelope 透传。

测试助手（schema 对账 + 只读断言）面向后续工具组复用：任何新工具只需在
mapping.py 登记即可纳入校验。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

import pytest
import respx
from httpx import Response
from mcp.server.fastmcp.tools.base import Tool

from reqmesh_harness.client.reader import ReadOnlyClient
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.registry import ToolSpec
from tests.conftest import HTTP_FIXTURES
from tests.mapping import (
    EXPECTED_TOOL_COUNT,
    MISSING,
    READ_TOOL_COUNT,
    REPORT_ENUM,
    TOOLS,
    ToolMap,
    by_name,
    write_by_name,
)

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@lru_cache
def registry():
    return build_registry()


def _resolve_ref(schema: dict, defs: dict) -> dict:
    if "$ref" in schema:
        return defs.get(schema["$ref"].rsplit("/", 1)[-1], schema)
    return schema


def _schema_types(schema: dict, defs: dict | None = None) -> set[str] | None:
    """粗类型提取：支持 $defs/$ref（P2 写工具嵌套对象数组参数）与 anyOf 可空分支。"""
    defs = defs or {}
    if "enum" in schema:
        return {"enum"}
    if "$ref" in schema:
        return _schema_types(_resolve_ref(schema, defs), defs)
    if "anyOf" in schema:
        types: set[str] = set()
        for item in schema["anyOf"]:
            if item.get("type") == "null":
                continue  # 可选字段的 null 分支不算类型
            resolved = _resolve_ref(item, defs)
            types |= _schema_types(resolved, defs) or set()
        return types or None
    if "type" in schema:
        return {schema["type"]}
    return None


def assert_schema_matches_toolmap(spec: ToolSpec, toolmap: ToolMap) -> Tool:
    """schema 对账助手：FastMCP Tool.parameters 与映射表逐参数一致。"""
    tool = Tool.from_function(spec.fn, name=spec.name, description=spec.description)
    params = tool.parameters
    props = params.get("properties", {})
    defs = params.get("$defs", {})
    expected_names = [p.name for p in toolmap.params]
    assert list(props.keys()) == expected_names
    assert list(params.get("required", [])) == [p.name for p in toolmap.params if p.required]
    for p in toolmap.params:
        schema = props[p.name]
        types = _schema_types(schema, defs)
        if p.types == ("enum",):
            assert types == {"enum"}
            vals = schema.get("enum", [])
            if p.name == "report":
                assert vals == REPORT_ENUM
            elif p.name == "entity_kind":
                from reqmesh_harness.tools.groups.writes import COMMENT_ENTITY_KINDS

                assert set(vals) == set(COMMENT_ENTITY_KINDS), f"{spec.name}.{p.name} 枚举与上游词表不一致"
        else:
            assert types == set(p.types), f"{spec.name}.{p.name} 类型 {types} != {p.types}"
        if p.required:
            assert "default" not in schema
        elif p.default is MISSING:
            assert "default" not in schema, f"{spec.name}.{p.name} 应无 schema 默认值（UNSET 哨兵）"
        else:
            assert schema.get("default") == p.default
    return tool


# ------------------------------------------------------------------ 注册表
def test_registry_has_exactly_40_tools() -> None:
    """P4：27 READ + 13 写 = 40（25 READ + 12 写 + draft_requirement + get_requirement_quality + get_traceability_gap_report）。"""
    specs = registry().all()
    assert len(specs) == EXPECTED_TOOL_COUNT
    assert sum(1 for s in specs if s.level == "READ") == READ_TOOL_COUNT
    assert sum(1 for s in specs if s.level == "DRAFT") == 7
    assert sum(1 for s in specs if s.level == "MUTATE") == 6


def test_registry_names_domains_match_mapping() -> None:
    mapping = {**by_name(), **write_by_name()}
    for spec in registry().all():
        assert spec.name in mapping
        assert spec.domain == mapping[spec.name].domain
        assert spec.level == mapping[spec.name].level
        assert NAME_RE.match(spec.name), spec.name


def test_descriptions_start_with_level_prefix() -> None:
    """description 前缀按层级（ADR-0002：READ-ONLY 惯例；P2 起 DRAFT/MUTATE）。"""
    for spec in registry().all():
        prefix = {"READ": "READ-ONLY", "DRAFT": "DRAFT", "MUTATE": "MUTATE", "ADMIN": "ADMIN"}[spec.level]
        assert spec.description.startswith(prefix), spec.name


def test_description_single_source_is_docstring() -> None:
    """description 唯一来源 = 处理器 docstring；注册表与处理器之间不得存在第二份文本。"""
    for spec in registry().all():
        assert spec.description == (spec.fn.__doc__ or "").strip()


def test_readonly_client_structurally_exposes_only_get() -> None:
    public = [m for m in dir(ReadOnlyClient) if not m.startswith("_")]
    assert public == ["get"]


@pytest.mark.parametrize("toolmap", TOOLS, ids=lambda t: t.name)
def test_schema_matches_mapping(toolmap: ToolMap) -> None:
    spec = registry().get(toolmap.name)
    assert_schema_matches_toolmap(spec, toolmap)


# ------------------------------------------------------------------ 每个工具：路由 + 只读 + envelope
def _load_fixture(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "toolmap,case",
    [(t, c) for t in TOOLS for c in t.cases],
    ids=lambda tc: f"{tc[0].name}.{tc[1].name}" if isinstance(tc, tuple) else tc.name,
)
def test_case_passthrough_readonly(reqmesh_env, toolmap: ToolMap, case) -> None:
    if not toolmap.passthrough:
        pytest.skip("工具返回为加工投影（非逐字透传）——由专用测试覆盖")
    spec = registry().get(toolmap.name)
    fixture = _load_fixture(case.fixture)
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get(case.expect_path).mock(return_value=Response(200, json=fixture))
        result = spec.fn(**case.args)
        # envelope 透传：返回内容与上游响应逐字一致
        assert result == fixture
        # 只读护栏：会话内 HTTP 方法 ⊆ {GET}
        methods = [c.request.method for c in router.calls]
        assert set(methods) == {"GET"}, f"{spec.name}.{case.name} 非 GET 请求: {methods}"
        # 路由与参数透传
        calls = [c for c in router.calls if c.request.url.path == case.expect_path]
        assert len(calls) == 1
        if case.expect_query:
            actual = {k: v for k, v in calls[0].request.url.params.items()}
            expected = {k: str(v) for k, v in case.expect_query.items()}
            assert actual == expected
        else:
            assert dict(calls[0].request.url.params) == {}


def test_schema_rejects_invalid_values_at_call_boundary() -> None:
    """MCP 调用路径的校验 = 处理器函数的 arg model（FastMCP 在协议边界用它预解析）。
    非法值必须被拒绝（#13 AC2：report 枚举非法值被 schema 拒绝；#3 分页上限 2000）。"""
    from pydantic import ValidationError

    tool = Tool.from_function(
        registry().get("list_requirements").fn, name="list_requirements", description="x"
    )
    model = tool.fn_metadata.arg_model
    assert model.model_validate({"project_id": "cessna-172"})
    with pytest.raises(ValidationError):
        model.model_validate({"project_id": "cessna-172", "limit": 5000})
    with pytest.raises(ValidationError):
        model.model_validate({"project_id": "cessna-172", "offset": -1})

    report_tool = Tool.from_function(
        registry().get("get_project_report").fn, name="get_project_report", description="x"
    )
    report_model = report_tool.fn_metadata.arg_model
    with pytest.raises(ValidationError):
        report_model.model_validate({"project_id": "cessna-172", "report": "bogus"})
