"""工具注册表：P1 的唯一事实源。

每个 READ 工具在注册表声明：name（ADR-0002 verb_entity）、title、description
（READ-ONLY 开头、中文）、domain（实体域分组）、处理器函数（显式参数签名）。
注册表统一驱动三处：

- FastMCP 工具注册（name/description/annotations(readOnlyHint)/meta(domain)）；
- OpenAI function JSON 导出（同一处理器函数经 Tool.from_function 推导同一份 schema）；
- schema/只读对账测试（与 spec 映射表逐项比对）。

MCP 协议的低层 Tool 类型没有 tags 字段（0.5.0 及 1.x 均无），实体域分组经
`meta.domain` 呈现（对客户端可见），与注册表、OpenAI 导出保持同一来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from mcp.types import ToolAnnotations

ANNOTATIONS_READ = ToolAnnotations(readOnlyHint=True)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    description: str
    domain: str
    fn: Callable[..., Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"重复注册的工具: {spec.name}")
        self._specs[spec.name] = spec

    def all(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.name)

    def get(self, name: str) -> ToolSpec:
        return self._specs[name]

    def __len__(self) -> int:
        return len(self._specs)

    def install(self, mcp: FastMCP) -> None:
        for spec in self.all():
            mcp.add_tool(
                spec.fn,
                name=spec.name,
                title=spec.title,
                description=spec.description,
                annotations=ANNOTATIONS_READ,
                meta={"domain": spec.domain, "permission": "READ"},
            )

    def openai_tools(self) -> list[dict[str, Any]]:
        """导出 OpenAI function-calling JSON：与 MCP 注册共用同一处理器函数，
        经 Tool.from_function 推导与 MCP 侧逐字一致的 parameters。"""
        out: list[dict[str, Any]] = []
        for spec in self.all():
            tool = Tool.from_function(spec.fn, name=spec.name, description=spec.description)
            out.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": tool.parameters,
                }
            )
        return out

    def mcp_tools(self) -> list[Tool]:
        return [
            Tool.from_function(spec.fn, name=spec.name, description=spec.description)
            for spec in self.all()
        ]
