"""候选检查内核：结构检查（不看取值）的语义专用测试。

本文件覆盖 ``checks/structural.py`` 的判定，以及 ``check_expressions`` 工具的
聚合行为。核心断言来自一次真实事故（见 ``test_str_constant_is_reported_although_unknown``）：
**求值器在引用缺值时返回 unknown，而 unknown 不能证明表达式合法**——
同一条非法表达式缺值时报 unknown、有值时报 ValueError，只有不看取值的结构检查
才能发现它。若本文件的这些断言失效，检查器就退化成"只会说 OK"的装饰品。
"""

from __future__ import annotations

import pytest

from reqmesh_harness.checks import check_expression, check_project

OWN = {"alc_flag", "r1", "r2", "amount", "待分摊金额", "x", "y", "z", "mtow", "useful_load"}


def codes(expr: str, own=OWN, bindings=None, param_index=None) -> list[str]:
    findings = check_expression(
        expr, owner="E1", field="t", own_params=own,
        bindings=bindings or {}, param_index=param_index if param_index is not None else {"E1": set(own)},
    )
    return [f["code"] for f in findings]


# ---------------------------------------------------------------- 核心事故回归
def test_str_constant_is_reported_although_unknown() -> None:
    """``alc_flag == 'N'`` 必须被报出——尽管求值器缺值时会先返回 unknown。

    实测对照（reqmesh 0.5.0 求值器）：缺值 → unknown；有值 → ValueError。
    结构检查不看取值，故两种情形下结论一致。
    """
    assert codes("alc_flag == 'N'") == ["unsupported_constant"]


def test_empty_string_compare_is_reported() -> None:
    assert codes("x != ''") == ["unsupported_constant"]


def test_set_membership_is_reported() -> None:
    """``in`` / ``not in`` 与集合字面量都不受支持（本仓库既有项目踩过）。"""
    got = codes("alc_flag not in {'S','Y'}")
    assert "unsupported_operator" in got
    assert "unsupported_node" in got


def test_bool_literal_is_reported() -> None:
    assert codes("x == True") == ["unsupported_constant"]


# ---------------------------------------------------------------- 假阳性回归
def test_rollup_string_args_are_not_constants_violations() -> None:
    """rollup 的两个字符串参数是**合法**的——扁平的 ast.walk 会误报，故用递归镜像。"""
    assert codes("rollup('C172', 'mass')") == []


def test_function_name_is_not_an_unbound_reference() -> None:
    assert codes("round(r1, 2)") == []
    assert codes("min(r1, r2)") == []


def test_attribute_base_name_is_not_an_unbound_reference() -> None:
    assert codes("mtow - E2.empty_mass", param_index={"E1": set(OWN), "E2": {"empty_mass"}}) == []


def test_chinese_parameter_names_are_accepted() -> None:
    assert codes("待分摊金额 * 30 / 100") == []


# ---------------------------------------------------------------- 语法与算子白名单
@pytest.mark.parametrize("expr", ["r1 @ r2", "r1 // r2", "r1 | r2"])
def test_unsupported_binop(expr: str) -> None:
    assert "unsupported_operator" in codes(expr)


@pytest.mark.parametrize("expr", ["[1,2]", "x if y else z", "{'a': 1}", "(x for x in [1])", "f'{x}'"])
def test_unsupported_node(expr: str) -> None:
    assert "unsupported_node" in codes(expr)


def test_allowed_operators_pass() -> None:
    for expr in ("r1 + r2 == 100", "r1 - r2", "r1 * r2", "r1 / r2", "r1 ** 2", "r1 % 1 == 0",
                 "r1 < r2 and r2 >= r1 or not (r1 == r2)"):
        assert codes(expr) == [], expr


def test_non_whitelisted_function() -> None:
    got = codes("sum(r1)")
    assert "unsupported_function" in got


def test_rollup_arity() -> None:
    assert codes("rollup('C172')") == ["rollup_bad_args"]
    assert codes("rollup('C172', 'mass', 'x')") == ["rollup_bad_args"]
    assert codes("rollup(mtow, 'mass')") == ["rollup_bad_args"]


def test_keyword_args_rejected() -> None:
    assert "keyword_args" in codes("round(r1, ndigits=2)")


# ---------------------------------------------------------------- 引用存在性
def test_unbound_reference() -> None:
    assert codes("notdeclared > 0") == ["unknown_reference"]


def test_cross_entity_reference_must_exist() -> None:
    assert codes("E2.empty_mass", param_index={"E1": set(OWN)}) == ["unknown_reference"]
    assert codes("E2.empty_mass", param_index={"E1": set(OWN), "E2": {"empty_mass"}}) == []


def test_calc_def_bindings_resolve_formals() -> None:
    """bindings 里的形式名合法（求值器 _eval 对 ast.Name 先查 env）。"""
    assert codes("actual <= limit", own=set(), bindings={"actual": "E1.x", "limit": "E1.y"}) == []


def test_syntax_error_and_empty() -> None:
    assert codes("r1 +") == ["syntax_error"]
    assert codes("   ") == ["empty_expr"]


# ---------------------------------------------------------------- 项目级聚合
def _req(rid, params=(), constraints=()):
    return {"id": rid, "parameters": list(params), "constraints": list(constraints)}


def test_project_reports_across_requirements_and_components() -> None:
    report = check_project(
        requirements=[
            _req("R1", [{"name": "a", "expr": "b + 1"}, {"name": "b", "value": 2}]),
            _req("R2", [{"name": "c", "value": 1}], constraints=[{"expr": "c == 'X'"}]),
        ],
        components=[_req("C1", constraints=[{"expr": "rollup('C1','m') > 0"}])],
    )
    assert report["summary"]["entities_checked"] == 3
    assert report["summary"]["expressions_checked"] == 3
    assert report["summary"]["errors"] == 1
    assert report["findings"][0]["code"] == "unsupported_constant"
    assert report["checked_against"] and report["source_of_truth"]


def test_project_covers_assume_and_definitions() -> None:
    report = check_project(
        requirements=[_req("R1",
                           [{"name": "v", "calc_def": "Calc1", "bindings": {"actual": "R1.v"}},
                            {"name": "s", "value": 1}],
                           [{"expr": "v > 0", "assume": "s == 'F'"},
                            {"constraint_def": "C1", "bindings": {"actual": "R1.v"}}])],
        definitions=[
            {"id": "Calc1", "expr": "actual * 2"},
            {"id": "C1", "expr": "actual >= 0"},
        ],
    )
    # parameters[0].calc_def + constraints[0].expr + constraints[0].assume + constraints[1].constraint_def
    assert report["summary"]["expressions_checked"] == 4
    assert [f["code"] for f in report["findings"]] == ["unsupported_constant"]


def test_undeclared_reference_and_constant_are_both_reported() -> None:
    """同一表达式可以同时有引用问题与常量问题——两类发现不得互相掩盖。"""
    report = check_project(requirements=[_req("R1", constraints=[{"expr": "nope == 'X'"}])])
    assert sorted(f["code"] for f in report["findings"]) == ["unknown_reference", "unsupported_constant"]


def test_missing_definition_is_reported() -> None:
    report = check_project(
        requirements=[_req("R1", [{"name": "v", "calc_def": "Nope", "bindings": {}}])],
    )
    assert [f["code"] for f in report["findings"]] == ["unknown_calc_def"]


def test_circular_parameter_derivation_is_reported() -> None:
    report = check_project(
        requirements=[_req("R1", [{"name": "a", "expr": "b + 1"}, {"name": "b", "expr": "a + 1"}])],
    )
    assert [f["code"] for f in report["findings"]] == ["circular_dependency"]


def test_no_cycle_for_linear_chain() -> None:
    report = check_project(
        requirements=[_req("R1", [{"name": "a", "expr": "b + 1"},
                                  {"name": "b", "expr": "c + 1"},
                                  {"name": "c", "value": 1}])],
    )
    assert report["findings"] == []


def test_rollup_is_not_a_cycle_edge() -> None:
    """rollup 的参数是标识符字符串，不得被当成参数引用参与环检测。"""
    report = check_project(
        requirements=[_req("R1", [{"name": "m", "expr": "rollup('C1','mass')"}])],
        components=[_req("C1", [{"name": "mass", "expr": "rollup('R1','m')"}])],
    )
    assert report["findings"] == []
