"""组件/基线/变更请求/报告域 READ 工具组（4 个）。"""

from __future__ import annotations

from typing import Any, Literal

from ._common import PageLimit, PageOffset, merged_list_or_get, project_path, read_json

_Report = Literal["quality", "compliance", "metrics", "evaluation", "validation", "workflow"]


def list_components(
    project_id: str,
    component_id: str | None = None,
    search: str | None = None,
    type: str | None = None,
    satisfies: str | None = None,
    as_tree: bool = False,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出组件（component_id 给出时返回单个；as_tree=true 返回组件树；search/type/satisfies 过滤）。"""
    if component_id:
        return read_json(project_path(project_id, f"/components/{component_id}"))
    if as_tree:
        return read_json(project_path(project_id, "/components/tree"))
    params: dict[str, Any] = {"offset": offset, "limit": limit}
    for name, value in (("search", search), ("type", type), ("satisfies", satisfies)):
        if value is not None:
            params[name] = value
    return read_json(project_path(project_id, "/components"), params)


def list_baselines(project_id: str) -> Any:
    """READ-ONLY 列出基线（里程碑）。"""
    return read_json(project_path(project_id, "/baselines"))


def list_change_requests(
    project_id: str,
    cr_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出变更请求（cr_id 给出时返回单个）。"""
    return merged_list_or_get(project_id, "change-requests", cr_id, offset, limit)


_REPORT_ROUTES: dict[str, str] = {
    "quality": "/quality",
    "compliance": "/compliance",
    "metrics": "/metrics",
    "evaluation": "/evaluation",
    "validation": "/validate",
    "workflow": "/workflow",
}


def get_project_report(project_id: str, report: _Report) -> Any:
    """READ-ONLY 返回计算型项目报告（report: quality/compliance/metrics/evaluation/validation/workflow）。"""
    return read_json(project_path(project_id, _REPORT_ROUTES[report]))
