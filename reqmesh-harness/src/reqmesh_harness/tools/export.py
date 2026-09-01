"""OpenAI function-calling JSON 导出（P1 #15）。

与 MCP 侧共用同一注册表与同一处理器函数推导的 schema（Tool.from_function），
再做 OpenAI JSON Schema 子集转换：递归移除 title/additionalProperties/$defs/
$schema（其余关键字 type/description/enum/required/properties/items/anyOf/
minimum/maximum/default 均属于 OpenAI 兼容子集）。
1:1 对账测试：导出集合与 MCP 注册集合逐名一致、参数语义一致。
"""

from __future__ import annotations

from typing import Any

from .registry import ToolRegistry

_STRIP_KEYS = ("title", "additionalProperties", "$defs", "$schema")


def to_openai_schema(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: to_openai_schema(v)
            for k, v in node.items()
            if k not in _STRIP_KEYS
        }
    if isinstance(node, list):
        return [to_openai_schema(x) for x in node]
    return node


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
