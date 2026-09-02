"""P4 #32 建议修复动作模板表：12 行契约逐行校验 + 渲染确定性 + 纯建议边界。

- 12 行 template 逐行命中（dimension_type/severity/action/tool_hint 与 spec ③ 表一致）；
- tool_hint 词表 ⊆ 既有写工具名（review_item/update_requirement/set_relations/
  set_allocation/create_verification_case）；
- action 渲染（嵌入实体 id/need 类型）确定性；维度类型词表 12 值 1:1（spec Literal 契约）。
"""

from __future__ import annotations

import pytest

from reqmesh_harness.report import (
    DIMENSION_TYPES,
    SEVERITIES,
    SEVERITY_RANK,
    TEMPLATE_ROWS,
    WRITE_TOOL_NAMES,
    render_action,
    severity_of,
    template_for,
    uncovered_type,
)


def test_twelve_rows_exactly() -> None:
    assert len(TEMPLATE_ROWS) == 12
    assert len({t.dimension_type for t in TEMPLATE_ROWS}) == 12  # 无重复（12 类 1:1）


def test_dimension_types_are_the_twelve_template_types() -> None:
    assert len(DIMENSION_TYPES) == 12
    assert len(set(DIMENSION_TYPES)) == 12
    assert set(DIMENSION_TYPES) == {t.dimension_type for t in TEMPLATE_ROWS}
    assert DIMENSION_TYPES == tuple(
        t.dimension_type for t in TEMPLATE_ROWS
    )  # 顺序稳定（文档序）


def test_severity_vocabulary_fixed_four_levels() -> None:
    assert SEVERITIES == ("high", "medium", "low", "info")
    assert set(SEVERITY_RANK) == set(SEVERITIES)
    # 排序契约：high > medium > low > info
    assert [k for k, _ in sorted(SEVERITY_RANK.items(), key=lambda kv: -kv[1])] == [
        "high",
        "medium",
        "low",
        "info",
    ]


def test_tool_hint_subset_of_existing_write_tools() -> None:
    registry_names = set(WRITE_TOOL_NAMES)
    from reqmesh_harness.tools import build_registry

    actual_write = {
        s.name for s in build_registry().all() if s.level in ("DRAFT", "MUTATE")
    }
    assert registry_names <= actual_write  # 模板词表全部是既有注册写工具
    for row in TEMPLATE_ROWS:
        assert row.tool_hint, row.dimension_type
        assert set(row.tool_hint) <= actual_write, row.dimension_type


@pytest.mark.parametrize("row", TEMPLATE_ROWS, ids=lambda r: r.dimension_type)
def test_row_contract(row) -> None:
    assert row.severity in SEVERITIES
    assert "{id}" in row.action, f"{row.dimension_type} action 模板必须含 {{id}} 占位符"
    assert isinstance(row.tool_hint, tuple)


def test_severity_of_and_template_for_agree() -> None:
    for row in TEMPLATE_ROWS:
        assert severity_of(row.dimension_type) == row.severity
        assert template_for(row.dimension_type) == row
    assert template_for("bogus.type") is None


def test_render_action_embedding_id_and_need() -> None:
    rendered = render_action("coverage.uncovered:design", "AFRM0000", "design")
    assert "AFRM0000" in rendered and "design" in rendered

    rendered_vc = render_action(
        "coverage.uncovered:verification_case", "AFRM0004", "verification_case"
    )
    assert rendered_vc != rendered
    assert "AFRM0004" in rendered_vc

    # 无 need 的维度：渲染成功且 id 嵌入
    plain = render_action("trace.unlinked", "ACFT0000")
    assert "ACFT0000" in plain and "{id}" not in plain


def test_render_action_deterministic() -> None:
    a = render_action("allocation.missing", "OVERVIEW01")
    b = render_action("allocation.missing", "OVERVIEW01")
    assert a == b


def test_uncovered_type_mapping() -> None:
    # spec ③ 表两行：design→medium、verification_case→high（need 并入类型值）
    assert uncovered_type("design") == "coverage.uncovered:design"
    assert uncovered_type("verification_case") == "coverage.uncovered:verification_case"
    # 上游 needs 词表其余值：defensive（无专属模板行 → design 变体）
    for need in ("analysis_case", "child_requirement", "reference"):
        t = uncovered_type(need)
        assert t == "coverage.uncovered:design"
        assert t in DIMENSION_TYPES


def test_uncovered_severity_differs_by_need() -> None:
    assert severity_of("coverage.uncovered:design") == "medium"
    assert severity_of("coverage.uncovered:verification_case") == "high"


def test_chain_broken_template_semantics() -> None:
    """shallow=true 且 deep=false → high（spec ③ 行 3；口径：broken_chain=shallow∧¬deep）。"""
    row = template_for("coverage.chain_broken")
    assert row is not None and row.severity == "high"
    assert row.tool_hint == ("update_requirement", "set_relations")
