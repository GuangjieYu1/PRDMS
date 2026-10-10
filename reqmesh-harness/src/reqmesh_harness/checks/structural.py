"""静态结构检查内核：**不看取值**地遍历全部表达式。

存在理由（本会话实测坐实）：reqmesh 的求值器在引用缺值时返回 ``unknown``，而
``unknown`` **不能**证明表达式合法。同一条非法表达式 ``alc_type == 'D'``：

- 缺值时 → ``unknown``（掩盖问题）
- 有值时 → ``ValueError``（暴露 str 字面量不受支持）

所以需要一次**不依赖任何取值**的检查，遍历每个 ``expr`` / ``assume`` /
被引用 Definition 的表达式，判断：语法、原生支持的语法节点与常量、函数白名单、
参数引用是否存在、以及循环依赖。

实现方式：**递归遍历，逐条镜像** ``evaluation.Evaluator._eval`` 的分支结构。
不用扁平的 ``ast.walk``——那会把上下文相关的节点误判为普通引用，产生假阳性：

- ``rollup('C172', 'mass')`` 的两个字符串参数是合法的（求值器显式接受）；
- 调用名 ``round``、属性基名 ``amt``（``amt.x`` 中的 ``amt``）都不是裸参数引用。

检查器的价值全在"可信"上：报出假阳性等于让使用者学会忽略它。

真源与版本绑定
--------------
本模块的白名单**逐条对应** ``reqmesh/backend/app/services/evaluation.py`` 的
``ALLOWED_FUNCS`` / ``_BIN_OPS`` / ``_CMP_OPS`` / ``Evaluator._eval``。核实环境：
reqmesh 0.5.0（本地 ``reqmesh/backend``）。**上游求值器变更后本模块必须重新核对**
——检查器与实际求值器不一致时，报告的是"我以为的支持范围"，不是"真实的支持范围"。
``check_project`` 的返回里带 ``checked_against`` 字段，用于显式声明这一绑定。

纯函数：不发起任何网络请求，不读写文件，不接触写路径。
"""

from __future__ import annotations

import ast
from typing import Any, Iterable

#: 白名单的核实来源（版本绑定的显式声明）。
SOURCE_OF_TRUTH = "reqmesh/backend/app/services/evaluation.py"
CHECKED_AGAINST = "reqmesh 0.5.0"

#: ``evaluation.ALLOWED_FUNCS`` 的镜像（``rollup`` 是特例，单独处理）。
ALLOWED_FUNCS: frozenset[str] = frozenset(
    {"min", "max", "abs", "sqrt", "floor", "ceil", "round"}
)

#: ``rollup(comp_id, name)``：两个**字符串常量**参数，只聚合组件子树。
ROLLUP = "rollup"

#: ``evaluation._BIN_OPS`` 的镜像。
_ALLOWED_BIN_OPS: frozenset[type[ast.operator]] = frozenset(
    {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod}
)

#: ``evaluation._CMP_OPS`` 的镜像。
_ALLOWED_CMP_OPS: frozenset[type[ast.cmpop]] = frozenset(
    {ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq}
)

#: ``evaluation._eval`` 显式接受的节点类型；不在其中即 ``disallowed syntax``。
ALLOWED_NODE_TYPES: tuple[type[ast.AST], ...] = (
    ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp, ast.Call,
    ast.Name, ast.Attribute, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
)


def _finding(severity: str, code: str, entity: str, field: str, expr: str, detail: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "entity": entity,
        "field": field,
        "expr": expr,
        "detail": detail,
    }


class _Checker:
    """单条表达式的递归检查器（镜像 ``Evaluator._eval`` 的分支与判定）。"""

    def __init__(
        self,
        *,
        owner: str,
        field: str,
        expr: str,
        own_params: set[str],
        bindings: dict[str, str],
        param_index: dict[str, set[str]],
    ) -> None:
        self.owner = owner
        self.field = field
        self.expr = expr
        self.own_params = own_params
        self.bindings = bindings
        self.param_index = param_index
        self.findings: list[dict[str, Any]] = []

    def _err(self, code: str, detail: str) -> None:
        self.findings.append(_finding("error", code, self.owner, self.field, self.expr, detail))

    def check(self, node: ast.AST) -> None:
        if isinstance(node, ast.Constant):
            # 求值器：bool 与非 int/float 一律拒绝
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                self._err(
                    "unsupported_constant",
                    f"不支持的常量类型: {node.value!r} ({type(node.value).__name__})"
                    " —— 求值器只接受数值字面量",
                )
            return

        if isinstance(node, ast.Name):
            # 裸名 = 本对象参数，或 calc_def 绑定的形式名（_eval 先查 env）
            if node.id in self.bindings or node.id in self.own_params:
                return
            self._err("unknown_reference", f"引用了不存在的本对象参数: {self.owner}.{node.id}")
            return

        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name):
                self._err("bad_attribute_target", "只允许 ENTITY.parameter 形式的跨对象引用")
                return
            ent, attr = node.value.id, node.attr
            if self.param_index and attr not in self.param_index.get(ent, set()):
                self._err("unknown_reference", f"引用了不存在的参数: {ent}.{attr}")
            return

        if isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BIN_OPS:
                self._err("unsupported_operator", f"不支持的运算符: {type(node.op).__name__}")
            self.check(node.left)
            self.check(node.right)
            return

        if isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
                self._err("unsupported_operator", f"不支持的一元运算符: {type(node.op).__name__}")
            self.check(node.operand)
            return

        if isinstance(node, ast.Compare):
            for op in node.ops:
                if type(op) not in _ALLOWED_CMP_OPS:
                    self._err("unsupported_operator", f"不支持的比较运算符: {type(op).__name__}")
            self.check(node.left)
            for comparator in node.comparators:
                self.check(comparator)
            return

        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                self._err("unsupported_operator", f"不支持的逻辑运算符: {type(node.op).__name__}")
            for value in node.values:
                self.check(value)
            return

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                self._err("unsupported_call_target", "只允许对白名单函数的普通调用")
                return
            if node.keywords:
                self._err("keyword_args", "不支持关键字参数")
            fname = node.func.id
            if fname == ROLLUP:
                ok = (
                    len(node.args) == 2
                    and all(
                        isinstance(a, ast.Constant) and isinstance(a.value, str)
                        for a in node.args
                    )
                )
                if not ok:
                    self._err("rollup_bad_args", "rollup 必须接收两个字符串常量: rollup('COMP', 'param')")
                # rollup 的两个参数是标识符字符串，**不递归**（否则误报 str 常量）
                return
            if fname not in ALLOWED_FUNCS:
                self._err(
                    "unsupported_function",
                    f"非白名单函数: {fname}（允许: {sorted(ALLOWED_FUNCS | {ROLLUP})}）",
                )
            # 非白名单函数也继续递归参数，让调用方一次看到全部问题
            for arg in node.args:
                self.check(arg)
            return

        self._err("unsupported_node", f"不支持的语法节点: {type(node).__name__}")


def _collect_refs(node: ast.AST, owner: str, own_params: set[str], out: set[tuple[str, str]]) -> None:
    """递归收集 (entity, param) 引用，用于循环依赖检测（与检查器同源，避免假引用）。"""
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name):
            out.add((node.value.id, node.attr))
        return
    if isinstance(node, ast.Name):
        if node.id in own_params:
            out.add((owner, node.id))
        return
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == ROLLUP:
            return
        for arg in node.args:
            _collect_refs(arg, owner, own_params, out)
        return
    for child in ast.iter_child_nodes(node):
        _collect_refs(child, owner, own_params, out)


def check_expression(
    expr: str,
    *,
    owner: str,
    field: str,
    own_params: Iterable[str] = (),
    bindings: dict[str, str] | None = None,
    param_index: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """检查单条表达式的结构与引用；返回发现列表（空列表 = 未发现问题）。

    ``own_params``：本对象（需求/组件）的参数名集合——``ast.Name`` 解析为
    ``f"{owner}.{name}"``，故裸名必须是本对象的参数。
    ``bindings``：使用 ``calc_def`` 时，形式参数名 → 实际参数引用的映射；
    ``_eval`` 对 ``ast.Name`` 先查 env，故被绑定的形式名合法。
    ``param_index``：``{entity_id: {param_name}}``——``ENTITY.param`` 形式的
    跨对象引用据此校验存在性。
    """
    if not isinstance(expr, str) or not expr.strip():
        return [_finding("error", "empty_expr", owner, field, expr, "表达式为空")]

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        return [_finding("error", "syntax_error", owner, field, expr, f"语法错误: {exc.msg}")]

    checker = _Checker(
        owner=owner,
        field=field,
        expr=expr,
        own_params=set(own_params),
        bindings=bindings or {},
        param_index=param_index or {},
    )
    checker.check(tree.body)
    return checker.findings


def check_project(
    *,
    requirements: list[dict[str, Any]],
    components: list[dict[str, Any]] | None = None,
    definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """检查一个项目的全部表达式，返回结构化报告（**不评估取值**）。

    遍历范围：每个需求/组件的 ``parameters[].expr``、``constraints[].expr``、
    ``constraints[].assume``，以及被 ``calc_def`` / ``constraint_def`` 引用的
    Definition 表达式。
    """
    entities: list[dict[str, Any]] = list(requirements) + list(components or [])
    defs_by_id = {d.get("id"): d for d in (definitions or []) if d.get("id")}

    # 全局参数索引：{entity_id: {param_name}}
    param_index: dict[str, set[str]] = {}
    for ent in entities:
        eid = ent.get("id") or ""
        names = {p.get("name") for p in (ent.get("parameters") or []) if p.get("name")}
        if names:
            param_index.setdefault(eid, set()).update(names)

    findings: list[dict[str, Any]] = []
    expr_total = 0
    per_entity: dict[str, int] = {}

    def _record(ent: dict[str, Any], field: str, expr: str, own: set[str], bindings: dict[str, str]) -> None:
        nonlocal expr_total
        expr_total += 1
        eid = ent.get("id") or ""
        per_entity[eid] = per_entity.get(eid, 0) + 1
        findings.extend(check_expression(
            expr, owner=eid, field=field, own_params=own, bindings=bindings,
            param_index=param_index,
        ))

    for ent in entities:
        eid = ent.get("id") or ""
        own = param_index.get(eid, set())

        for i, p in enumerate(ent.get("parameters") or []):
            expr = p.get("expr")
            if isinstance(expr, str) and expr.strip():
                _record(ent, f"parameters[{i}].expr", expr, own, p.get("bindings") or {})
            calc_def = p.get("calc_def")
            if calc_def:
                definition = defs_by_id.get(calc_def)
                if definition is None:
                    findings.append(_finding(
                        "error", "unknown_calc_def", eid, f"parameters[{i}].calc_def",
                        calc_def, f"引用了不存在的计算定义: {calc_def}",
                    ))
                else:
                    _record(ent, f"parameters[{i}].calc_def:{calc_def}",
                            definition.get("expr", ""), own, p.get("bindings") or {})

        for i, c in enumerate(ent.get("constraints") or []):
            for key in ("expr", "assume"):
                expr = c.get(key)
                if isinstance(expr, str) and expr.strip():
                    _record(ent, f"constraints[{i}].{key}", expr, own, c.get("bindings") or {})
            cdef = c.get("constraint_def")
            if cdef:
                definition = defs_by_id.get(cdef)
                if definition is None:
                    findings.append(_finding(
                        "error", "unknown_constraint_def", eid, f"constraints[{i}].constraint_def",
                        cdef, f"引用了不存在的约束定义: {cdef}",
                    ))
                else:
                    _record(ent, f"constraints[{i}].constraint_def:{cdef}",
                            definition.get("expr", ""), own, c.get("bindings") or {})

    # 循环依赖检测（参数级：参数 expr 互相引用）
    graph: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for ent in entities:
        eid = ent.get("id") or ""
        own = param_index.get(eid, set())
        for p in ent.get("parameters") or []:
            expr = p.get("expr")
            if isinstance(expr, str) and expr.strip() and p.get("name"):
                refs: set[tuple[str, str]] = set()
                try:
                    tree = ast.parse(expr, mode="eval")
                except SyntaxError:
                    graph[(eid, p["name"])] = set()
                    continue
                _collect_refs(tree.body, eid, own, refs)
                graph[(eid, p["name"])] = refs

    cycles: list[list[str]] = []
    state: dict[tuple[str, str], int] = {}

    def _dfs(node: tuple[str, str], stack: list[tuple[str, str]]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            if node in stack:
                cycles.append(
                    [f"{e}.{n}" for e, n in stack[stack.index(node):]] + [f"{node[0]}.{node[1]}"]
                )
            return
        state[node] = 1
        for nxt in graph.get(node, set()):
            if nxt in graph:
                _dfs(nxt, stack + [node])
        state[node] = 2

    for node in graph:
        _dfs(node, [])

    for cyc in cycles:
        findings.append(_finding(
            "error", "circular_dependency", cyc[0].split(".")[0], "parameters", "",
            "循环参数推导: " + " → ".join(cyc),
        ))

    errors = [f for f in findings if f["severity"] == "error"]
    return {
        "checked_against": CHECKED_AGAINST,
        "source_of_truth": SOURCE_OF_TRUTH,
        "note": "结构检查不看取值：不依赖任何参数是否有值、前提是否成立。"
                "因此它不因 unknown / not_applicable 而跳过任何表达式。",
        "summary": {
            "entities_checked": len(entities),
            "expressions_checked": expr_total,
            "findings": len(findings),
            "errors": len(errors),
            "definitions_available": len(defs_by_id),
        },
        "findings": findings,
        "expressions_per_entity": per_entity,
    }


__all__ = [
    "ALLOWED_FUNCS",
    "ALLOWED_NODE_TYPES",
    "CHECKED_AGAINST",
    "SOURCE_OF_TRUTH",
    "check_expression",
    "check_project",
]
