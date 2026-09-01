"""OpenAI function-calling JSON 导出（P1 #15；P2 扩展 $defs 内联）。

与 MCP 侧共用同一注册表与同一处理器函数推导的 schema（Tool.from_function），
再做 OpenAI JSON Schema 子集转换：递归移除 title/additionalProperties/$defs/
$schema，并把 `$ref` 依 `$defs` **内联**（P2 写工具含嵌套对象/数组参数——
`list[TraceLink]` 等经 schema 引用 $defs；OpenAI 消费侧不接受 dangling $ref）。
1:1 对账测试：导出集合与 MCP 注册集合逐名一致、参数语义一致。
"""

from __future__ import annotations

from typing import Any

from .registry import ToolRegistry

_STRIP_KEYS = ("title", "additionalProperties", "$defs", "$schema")
_SCHEMA_KEYWORDS = ("type", "properties", "items", "enum", "anyOf", "oneOf", "allOf", "$ref", "required")


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    """递归清理 + $defs 内联。

    仅当节点是 **schema 对象**（含 schema 关键字）时才剥离 title 等元数据键；
    `properties` 的键是参数名（如 `title`/`type`），永不剥离——只递归其值。
    """
    if isinstance(node, dict):
        if "$ref" in node:
            target = defs.get(node["$ref"].rsplit("/", 1)[-1])
            if target is None:
                return {k: v for k, v in node.items() if k != "$ref"}
            return _inline(target, defs)
        is_schema = any(k in node for k in _SCHEMA_KEYWORDS)
        out: dict[str, Any] = {}
        for key, value in node.items():
            if is_schema and key in _STRIP_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {pk: _inline(pv, defs) for pk, pv in value.items()}
            else:
                out[key] = _inline(value, defs)
        return out
    if isinstance(node, list):
        return [_inline(x, defs) for x in node]
    return node


def to_openai_schema(node: Any) -> Any:
    defs = node.get("$defs", {}) if isinstance(node, dict) else {}
    return _inline(node, defs)


def export_openai_functions(registry: ToolRegistry) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in registry.all():
        from mcp.server.fastmcp.tools.base import Tool

        tool = Tool.from_function(spec.fn, name=spec.name, description=spec.description)
        out.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": to_openai_schema(tool.parameters),
            }
        )
    return out
