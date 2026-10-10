"""候选检查 READ 工具（1 个）。

- check_expressions：**不看取值**地遍历项目全部 ``expr`` / ``assume`` /
  被引用 Definition 的表达式，报告语法、原生支持性、参数引用存在性与循环依赖。
  纯客户端计算（AST 遍历在本地完成），**不调用任何求值端点**，也绝不接触写路径。

与既有能力的边界（重要）
------------------------
``get_project_report`` 是 reqmesh **服务端计算型报告**的 1:1 路由透传（validation /
evaluation / quality）。本工具**不扩展它的 report 枚举**——理由是 ADR-0002 P4 实现
注记确立的边界：客户端计算与透传是两种计算模型，必须独立成工具。

为什么需要它（本会话实测坐实）：求值器在引用缺值时返回 ``unknown``，而 ``unknown``
**不能**证明表达式合法。同一条非法表达式 ``alc_type == 'D'`` 缺值时只报 ``unknown``，
有值时才暴露 ``ValueError``。所以需要一次不依赖取值的结构检查。

版本绑定：白名单对应 ``reqmesh/backend/app/services/evaluation.py``（核实环境
reqmesh 0.5.0）。上游求值器变更后须重新核对——返回中的 ``checked_against``
字段显式声明这一绑定。
"""

from __future__ import annotations

from typing import Any

from ...checks import check_project
from ._common import project_path, read_json

#: 全量取数的页大小（reqmesh 上限 2000）。检查器必须看到**全部**表达式，
#: 因此这里自行翻页——不把"只检查了第一页"当成"全部通过"。
_PAGE = 2000
_MAX_PAGES = 50


def _fetch_all(project_id: str, collection: str) -> list[dict[str, Any]]:
    """按 offset 翻页取全量集合（fail-fast：上游错误直接透传）。"""
    out: list[dict[str, Any]] = []
    offset = 0
    for _ in range(_MAX_PAGES):
        payload = read_json(
            project_path(project_id, f"/{collection}"),
            {"offset": offset, "limit": _PAGE},
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            # 形状非法：不做部分报告，让调用方看到真实原因
            return out
        out.extend(items)
        total = payload.get("total")
        offset += len(items)
        if not items or not isinstance(total, int) or offset >= total:
            break
    return out


def check_expressions(project_id: str, limit: int = 200) -> Any:
    """READ-ONLY 静态结构检查：不看取值地遍历项目全部表达式，返回发现清单。

    覆盖：每个需求与组件的 ``parameters[].expr``、``constraints[].expr`` 与
    ``constraints[].assume``，以及被 ``calc_def`` / ``constraint_def`` 引用的
    Definition 表达式。检查语法、原生支持的语法节点与常量、函数白名单、
    参数引用是否存在（含 ENTITY.parameter 跨对象引用）、以及循环依赖。

    关键语义：**不依赖任何取值**，因此不会因 ``unknown``、条件短路或
    ``not_applicable`` 跳过任何表达式——这正是它与求值类报告的区别。
    返回含 ``checked_against`` 与 ``source_of_truth``，显式声明白名单绑定的
    reqmesh 求值器来源与核实版本；上游求值器变更后须重新核对。

    ``limit`` 仅限制返回的 findings 条数（默认 200），summary 始终为全量统计。
    """
    requirements = _fetch_all(project_id, "requirements")
    components = _fetch_all(project_id, "components")
    definitions = _fetch_all(project_id, "definitions")

    report = check_project(
        requirements=requirements,
        components=components,
        definitions=definitions,
    )
    findings = report["findings"]
    report["findings_truncated"] = len(findings) > limit
    report["findings"] = findings[:limit]
    return report


__all__ = ["check_expressions"]
