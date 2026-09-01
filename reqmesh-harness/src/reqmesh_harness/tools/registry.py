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
from typing import Any, Callable, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

Level = Literal["READ", "DRAFT", "MUTATE", "ADMIN"]


def annotations_for(level: str) -> ToolAnnotations:
    """权限层级 → MCP annotations（单向映射；对比 spec/ADR-0002）。

    - READ → readOnlyHint=True（P1 行为不变）；
    - DRAFT/MUTATE → readOnlyHint=False, destructiveHint=False（spec L173 字面语义）；
    - ADMIN → destructiveHint=True（危险操作标注；P2 预留，无 ADMIN 工具注册）。
    """
    if level == "READ":
        return ToolAnnotations(readOnlyHint=True)
    if level == "ADMIN":
        return ToolAnnotations(destructiveHint=True)
    return ToolAnnotations(readOnlyHint=False, destructiveHint=False)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    title: str
    domain: str
    level: Level
    fn: Callable[..., Any]

    @property
    def description(self) -> str:
        doc = (self.fn.__doc__ or "").strip()
        if not doc:
            raise ValueError(f"工具 {self.name} 缺 docstring（description 唯一来源）")
        return doc


class ToolRegistry:
    """工具注册表：唯一事实源（P1 只读 + P2 写 + ADMIN 显式开启分区）。

    - `add`：常规工具（READ/DRAFT/MUTATE），`install` 时全部安装；
    - `add_admin`：ADMIN 分区（P2 不注册任何 ADMIN 工具——分区机制先行，
      未来 phase 上线 = spec 映射表加行 + 本方法加行，审批门零改动）；
    - `all()` 只含**已安装**工具：ADMIN 行仅在 `REQMESH_ENABLE_ADMIN=1`
      （build_registry 依此传 `enable_admin`）时进入集合——未开启时 ADMIN
      工具不出现在 tools/list（协议层不存在，而非调用时才拒绝）。
    """

    def __init__(self, enable_admin: bool = False) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._admin_specs: dict[str, ToolSpec] = {}
        self._enable_admin = enable_admin

    def add(self, spec: ToolSpec) -> None:
        if spec.name in self._specs or spec.name in self._admin_specs:
            raise ValueError(f"重复注册的工具: {spec.name}")
        self._specs[spec.name] = spec

    def add_admin(self, spec: ToolSpec) -> None:
        if spec.name in self._specs or spec.name in self._admin_specs:
            raise ValueError(f"重复注册的工具: {spec.name}")
        if spec.level != "ADMIN":
            raise ValueError(f"add_admin 仅接受 level=ADMIN 的行: {spec.name}")
        self._admin_specs[spec.name] = spec

    def all(self) -> list[ToolSpec]:
        specs = dict(self._specs)
        if self._enable_admin:
            specs.update(self._admin_specs)
        return sorted(specs.values(), key=lambda s: s.name)

    def get(self, name: str) -> ToolSpec:
        if name in self._specs:
            return self._specs[name]
        if name in self._admin_specs and self._enable_admin:
            return self._admin_specs[name]
        raise KeyError(f"注册表无工具: {name}")

    @property
    def enable_admin(self) -> bool:
        return self._enable_admin

    def __len__(self) -> int:
        return len(self.all())

    def install(self, mcp: FastMCP) -> None:
        for spec in self.all():
            mcp.add_tool(
                spec.fn,
                name=spec.name,
                title=spec.title,
                description=spec.description,
                annotations=annotations_for(spec.level),
                meta={"domain": spec.domain, "permission": spec.level},
            )

    def call(self, name: str, **kwargs: Any) -> Any:
        """以注册表为入口调用工具（冒烟等外部方不再穿透到 fn 属性）。"""
        return self.get(name).fn(**kwargs)
