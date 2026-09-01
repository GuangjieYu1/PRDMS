"""组件/基线/变更请求/报告域 READ 工具组（4 个）。"""

from __future__ import annotations

from typing import Any, Literal

from ..runtime import get_runtime
from ._common import PageLimit, PageOffset, get_params, paginate, project_path

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
    """READ-ONLY 列出组件（component_id 给出时返回单个；as_tree=true 返回组件树）。"""
    if component_id:
        return get_params(
            get_runtime().reader(), project_path(project_id, f"/components/{component_id}")
        )
    if as_tree:
        return get_params(get_runtime().reader(), project_path(project_id, "/components/tree"))
    params: dict[str, Any] = paginate(offset, limit)
    if search is not None:
        params["search"] = search
    if type is not None:
        params["type"] = type
    if satisfies is not None:
        params["satisfies"] = satisfies
    return get_params(get_runtime().reader(), project_path(project_id, "/components"), params)


def list_baselines(project_id: str) -> Any:
    """READ-ONLY 列出基线（里程碑）。"""
    return get_params(get_runtime().reader(), project_path(project_id, "/baselines"))


def list_change_requests(
    project_id: str,
    cr_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出变更请求（cr_id 给出时返回单个）。"""
    if cr_id:
        return get_params(
            get_runtime().reader(), project_path(project_id, f"/change-requests/{cr_id}")
        )
    return get_params(
        get_runtime().reader(), project_path(project_id, "/change-requests"), paginate(offset, limit)
    )


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
    return get_params(
        get_runtime().reader(), project_path(project_id, _REPORT_ROUTES[report])
    )
