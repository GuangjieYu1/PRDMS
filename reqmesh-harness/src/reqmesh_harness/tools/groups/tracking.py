"""追踪/覆盖域 READ 工具组（5 个）。"""

from __future__ import annotations

from typing import Any

from ._common import project_path, read_json


def get_traces(
    project_id: str,
    entity_id: str | None = None,
    collection: str | None = None,
) -> Any:
    """READ-ONLY 返回追踪矩阵；给出 entity_id 时返回该实体的回链（backlinks）。"""
    if entity_id:
        params: dict[str, Any] = {}
        if collection is not None:
            params["collection"] = collection
        return read_json(project_path(project_id, f"/entities/{entity_id}/backlinks"), params or None)
    return read_json(project_path(project_id, "/traces"))


def get_coverage(project_id: str) -> Any:
    """READ-ONLY 返回覆盖率分析（需求-验证/分析覆盖）。"""
    return read_json(project_path(project_id, "/coverage"))


def get_gap_analysis(project_id: str) -> Any:
    """READ-ONLY 返回覆盖缺口分析（未覆盖/欠覆盖集）。"""
    return read_json(project_path(project_id, "/gap-analysis"))


def get_allocation_matrix(
    project_id: str,
    axis: str | None = None,
    rows: str | None = None,
    search: str | None = None,
    filter_type: str | None = None,
) -> Any:
    """READ-ONLY 返回分配矩阵（axis/rows/search/filter_type 过滤）。"""
    params: dict[str, Any] = {}
    if axis is not None:
        params["axis"] = axis
    if rows is not None:
        params["rows"] = rows
    if search is not None:
        params["search"] = search
    if filter_type is not None:
        params["filter_type"] = filter_type
    return read_json(project_path(project_id, "/allocation-matrix"), params or None)


def get_suspect_links(project_id: str) -> Any:
    """READ-ONLY 返回可疑追踪链接（编辑后失配）。"""
    return read_json(project_path(project_id, "/suspect-links"))
