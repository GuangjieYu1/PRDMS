"""追踪/覆盖缺口报告模块（P4，全 READ 层）。

- aggregate：六源聚合内核（纯函数、无网络副作用；失败快速整体报错，不产部分报告）；
- templates：12 类缺口维度 → 建议修复动作模板表（severity/action/tool_hint 契约；
  tool_hint 仅引用既有写工具名，报告绝不执行修复——spec ③ 硬约束）；
- 许可证边界：独立编写，仅消费公开 REST 响应形状与实测 fixture，不复制 reqmesh
  GPL 源码（spec 事实 5）。
"""

from .aggregate import build_report
from .templates import (
    DIMENSION_TYPES,
    SEVERITIES,
    SEVERITY_RANK,
    DimensionType,
    FixTemplate,
    TEMPLATE_ROWS,
    WRITE_TOOL_NAMES,
    render_action,
    severity_of,
    template_for,
    uncovered_type,
)

__all__ = [
    "DIMENSION_TYPES",
    "DimensionType",
    "FixTemplate",
    "SEVERITIES",
    "SEVERITY_RANK",
    "TEMPLATE_ROWS",
    "WRITE_TOOL_NAMES",
    "build_report",
    "render_action",
    "severity_of",
    "template_for",
    "uncovered_type",
]
