"""工具注册表：P1 的唯一事实源。

每个 READ 工具在注册表声明：name（ADR-0002 verb_entity）、title、domain（实体域
分组）、权限层级（level，P2 审批门从这里映射，绝不解析名字）与处理器函数。
description 的唯一来源是处理器的 docstring（注册表经 `ToolSpec.description`
属性读取），注册表与处理器之间不存在第二份描述文本。
注册表统一驱动：

- FastMCP 工具注册（name/description/annotations(readOnlyHint)/meta(domain,level)）；
- OpenAI function JSON 导出（同一处理器函数经 Tool.from_function 推导同一份参数 schema）；
- schema/只读对账测试（与 spec 映射表逐项比对）。

实现注记（对照 ADR-0002 的 tags）：MCP 协议低层 Tool 类型没有 tags 字段
（mcp 0.5.0 与 1.x 均无），实体域分组经 meta.domain 呈现——已回写 ADR-0002。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

ANNOTATIONS_READ = ToolAnnotations(readOnlyHint=True)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    domain: str
    level: str
    fn: Callable[..., Any]

    @property
    def description(self) -> str:
        doc = (self.fn.__doc__ or "").strip()
        if not doc:
            raise ValueError(f"工具 {self.name} 缺 docstring（description 唯一来源）")
        return doc


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
                meta={"domain": spec.domain, "permission": spec.level},
            )
