"""缺口维度 → 建议修复动作模板表（P4 #32，spec ③ 契约）。

12 类缺口维度（= 模板表 12 行）：每行固定 {dimension_type, severity, action, tool_hint}；
action 为中文模板（渲染时嵌入实体 id / need 类型等证据），tool_hint 仅引用**既有写工具名**
（review_item/update_requirement/set_relations/set_allocation/create_verification_case），
不 import、不调用——报告是纯建议，绝不执行修复（spec ③ 硬约束）。

维度类型词表（12 值，与模板行 1:1；`dimensions` 白名单 Literal 同源）：
`coverage.uncovered` 在 spec 模板表中按 need 分两行（need=design / need=verification_case，
严重度不同），故类型以 `coverage.uncovered:<need>` 形式区分——维度类型唯一值 = 12，
与「12 类缺口维度」逐值对应（实现注记：spec 表类型列背引号部分为 `coverage.uncovered`，
need 注记在单元格内；本实现把 need 并入类型值，保证 Literal 枚举 12 值 1:1）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Severity = Literal["high", "medium", "low", "info"]

SEVERITIES: tuple[Severity, ...] = ("high", "medium", "low", "info")
SEVERITY_RANK: dict[str, int] = {"high": 3, "medium": 2, "low": 1, "info": 0}

# 12 类维度类型值（Literal 词表；与 TEMPLATE_ROWS 逐行对应）
DimensionType = Literal[
    "coverage.uncovered:design",
    "coverage.uncovered:verification_case",
    "coverage.chain_broken",
    "coverage.unwanted",
    "content.no_description",
    "content.no_rationale",
    "content.no_source",
    "trace.unlinked",
    "trace.stale",
    "review.never",
    "review.stale",
    "allocation.missing",
]

DIMENSION_TYPES: tuple[str, ...] = (
    "coverage.uncovered:design",
    "coverage.uncovered:verification_case",
    "coverage.chain_broken",
    "coverage.unwanted",
    "content.no_description",
    "content.no_rationale",
    "content.no_source",
    "trace.unlinked",
    "trace.stale",
    "review.never",
    "review.stale",
    "allocation.missing",
)

# tool_hint 词表 = 既有写工具名（spec ③：仅引用，绝不调用）
WRITE_TOOL_NAMES = (
    "review_item",
    "update_requirement",
    "set_relations",
    "set_allocation",
    "create_verification_case",
)

# 上游 needs 词表的其他取值（cessna-172/fixture 未使用）：无专属模板行时按 design
# 变体处理（severity/action 模板同设计覆盖），evidence 保留实际 need_type（防御性）。
_UNCOVERED_FALLBACK = "coverage.uncovered:design"


@dataclass(frozen=True)
class FixTemplate:
    """一行模板（spec 表契约）：type/severity/action 模板/tool_hint。"""

    dimension_type: str
    severity: Severity
    action: str  # 含 {id}（必要）与 {need_type}（可选）占位符
    tool_hint: tuple[str, ...]  # ⊆ WRITE_TOOL_NAMES


# spec ③ 模板表（12 行；action 中文模板，渲染时嵌入实体 id/need 类型等证据）
TEMPLATE_ROWS: tuple[FixTemplate, ...] = (
    FixTemplate(
        "coverage.uncovered:design",
        "medium",
        "为需求 {id} 分配满足该需求的组件（design 覆盖）：从 list_components 选定组件后 "
        "set_allocation(allocated=true)，或让组件 satisfies 该需求；该缺口与 allocation.missing 同根。",
        ("set_allocation",),
    ),
    FixTemplate(
        "coverage.uncovered:verification_case",
        "high",
        "为需求 {id} 建立验证覆盖：create_verification_case 新建或复用既有验证用例，再经 "
        "set_relations / update_requirement(verification_cases) 关联。",
        ("create_verification_case", "set_relations"),
    ),
    FixTemplate(
        "coverage.chain_broken",
        "high",
        "修复覆盖链：为需求 {id} 补充子需求分解（refines/derives）并确保子需求自身 deep 覆盖；"
        "或直接补齐顶层缺失的覆盖类型。",
        ("update_requirement", "set_relations"),
    ),
    FixTemplate(
        "coverage.unwanted",
        "info",
        "核查需求 {id} 的多余覆盖来源并清理：移除不需要类型的链接/分配。",
        ("set_relations", "set_allocation"),
    ),
    FixTemplate(
        "content.no_description",
        "low",
        "补充需求 {id} 的描述文本（description）。",
        ("update_requirement",),
    ),
    FixTemplate(
        "content.no_rationale",
        "low",
        "补充需求 {id} 的理由（rationale，why）。",
        ("update_requirement",),
    ),
    FixTemplate(
        "content.no_source",
        "low",
        "补充需求 {id} 的来源（source，出处）。",
        ("update_requirement",),
    ),
    FixTemplate(
        "trace.unlinked",
        "high",
        "建立追踪链接：get_traces 读-改-写回放，经 set_relations 为需求 {id} 追加 "
        "refines/derives/verifies 链接。",
        ("set_relations",),
    ),
    FixTemplate(
        "trace.stale",
        "medium",
        "链接目标已变更：对目标需求 {id} review_item 重新评审刷新指纹；或经 set_relations "
        "移除并重建该链接。",
        ("review_item", "set_relations"),
    ),
    FixTemplate(
        "review.never",
        "medium",
        "提交评审：对需求 {id} 执行 review_item（从未评审）。",
        ("review_item",),
    ),
    FixTemplate(
        "review.stale",
        "medium",
        "内容变更后重新评审：对需求 {id} review_item 刷新指纹。",
        ("review_item",),
    ),
    FixTemplate(
        "allocation.missing",
        "medium",
        "为需求 {id} 分配组件：选定满足组件后 set_allocation(allocated=true)。",
        ("set_allocation",),
    ),
)

_TEMPLATE_BY_TYPE: dict[str, FixTemplate] = {t.dimension_type: t for t in TEMPLATE_ROWS}


def severity_of(dimension_type: str) -> Severity:
    """维度类型 → 严重度（模板表契约；未知类型抛 KeyError——词表封闭）。"""
    return _TEMPLATE_BY_TYPE[dimension_type].severity


def template_for(dimension_type: str) -> FixTemplate | None:
    """维度类型 → 模板行；未知（防御）返回 None。"""
    return _TEMPLATE_BY_TYPE.get(dimension_type)


def render_action(
    dimension_type: str, entity_id: str, need_type: str | None = None
) -> str:
    """渲染建议动作：实体 id 与（可选）need 类型嵌入模板（spec ③ 渲染语义）。"""
    row = _TEMPLATE_BY_TYPE[dimension_type]
    return row.action.format(
        id=entity_id, need_type=need_type if need_type is not None else ""
    )


def uncovered_type(need_type: str) -> str:
    """coverage 未覆盖的 need → 维度类型（design→:design、verification_case→:verification_case、
    其余上游词表值 → design 变体，防御性；evidence 保留实际 need_type）。"""
    if need_type == "verification_case":
        return "coverage.uncovered:verification_case"
    return _UNCOVERED_FALLBACK
