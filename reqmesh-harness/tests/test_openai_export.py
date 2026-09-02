"""#15 OpenAI function JSON 导出：全量、名称合规、schema 合法、1:1 对账、金样例（P3：39 工具）。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from mcp.server.fastmcp.tools.base import Tool

from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.export import export_openai_functions, to_openai_schema
from tests.mapping import EXPECTED_TOOL_COUNT, TOOLS, by_name, write_by_name

NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
PREFIX = {"READ": "READ-ONLY", "DRAFT": "DRAFT", "MUTATE": "MUTATE", "ADMIN": "ADMIN"}
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "openai_export.json"


@pytest.fixture
def exported():
    return export_openai_functions(build_registry())


def test_export_all_tools_with_valid_names(exported) -> None:
    assert len(exported) == EXPECTED_TOOL_COUNT
    names = [f["name"] for f in exported]
    assert len(set(names)) == len(names)
    specs = {s.name: s for s in build_registry().all()}
    for f in exported:
        assert NAME_RE.match(f["name"]), f["name"]
        assert f["description"].startswith(PREFIX[specs[f["name"]].level])


def test_parameters_are_valid_json_schema(exported) -> None:
    for f in exported:
        Draft202012Validator.check_schema(f["parameters"])
        assert f["parameters"].get("type") == "object"


def test_parameters_validate_known_instances(exported) -> None:
    """已知样例（来自 spec 映射表的 Case 参数）可被导出 schema 校验通过。"""
    mapping = {**by_name(), **write_by_name()}
    for f in exported:
        instance = dict(mapping[f["name"]].cases[0].args)
        Draft202012Validator(f["parameters"]).validate(instance)


def test_export_has_no_dangling_refs(exported) -> None:
    """write 工具的嵌套对象参数（TraceLink/AttributeValue 等）经 $defs 内联——无 $ref 残留。"""
    for f in exported:
        assert "$ref" not in json.dumps(f["parameters"]), f["name"]
        assert "$defs" not in json.dumps(f["parameters"]), f["name"]


def test_enum_rejected_by_exported_schema(exported) -> None:
    report = next(f for f in exported if f["name"] == "get_project_report")
    with pytest.raises(ValidationError):
        Draft202012Validator(report["parameters"]).validate({"project_id": "cessna-172", "report": "bogus"})


def test_parity_mcp_openai(exported) -> None:
    """MCP ↔ OpenAI 1:1 对账：无丢失、无多余，参数语义一致。"""
    registry = build_registry()
    mcp_names = {s.name for s in registry.all()}
    openai_names = {f["name"] for f in exported}
    assert mcp_names == openai_names
    for f in exported:
        spec = registry.get(f["name"])
        mcp_params = Tool.from_function(spec.fn, name=spec.name, description=spec.description).parameters
        clean = to_openai_schema(mcp_params)
        assert f["parameters"] == clean
        # 语义对账：属性集合、必需集合、默认值一致
        assert set(f["parameters"].get("properties", {})) == set(mcp_params.get("properties", {}))
        assert f["parameters"].get("required", []) == mcp_params.get("required", [])
        for name, prop in mcp_params.get("properties", {}).items():
            if "default" in prop:
                assert f["parameters"]["properties"][name].get("default") == prop["default"]


def test_golden_snapshot(exported) -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert exported == golden


def test_converter_strips_non_openai_keys() -> None:
    """子集转换定向测试：title/\$defs/additionalProperties 被剥离，其余保留。"""
    schema = {
        "title": "T",
        "type": "object",
        "properties": {"a": {"title": "A", "type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
        "$defs": {"X": {"type": "string"}},
    }
    out = to_openai_schema(schema)
    assert "title" not in out
    assert "$defs" not in out
    assert "additionalProperties" not in out
    assert out["properties"]["a"] == {"type": "string"}
    assert out["required"] == ["a"]


def test_golden_is_fresh_and_deterministic(exported) -> None:
    """导出结果确定性：两次导出字节一致。"""
    again = export_openai_functions(build_registry())
    assert json.dumps(exported, ensure_ascii=False, sort_keys=True) == json.dumps(
        again, ensure_ascii=False, sort_keys=True
    )
