"""需求域 READ 工具组（7 个）。"""

from __future__ import annotations

from typing import Any

from ..runtime import get_runtime
from ._common import PageLimit, PageOffset, get_params, paginate, project_path


def list_requirements(
    project_id: str,
    search: str | None = None,
    type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 按过滤器列出需求（search/type/status/priority；分页 offset/limit 透传，默认 limit=500）。"""
    params: dict[str, Any] = paginate(offset, limit)
    if search is not None:
        params["search"] = search
    if type is not None:
        params["type"] = type
    if status is not None:
        params["status"] = status
    if priority is not None:
        params["priority"] = priority
    return get_params(get_runtime().reader(), project_path(project_id, "/requirements"), params)


def get_requirement(project_id: str, req_id: str) -> Any:
    """READ-ONLY 按 id 返回单个需求完整内容。"""
    return get_params(get_runtime().reader(), project_path(project_id, f"/requirements/{req_id}"))


def search_requirements(project_id: str, q: str, kind: str | None = None) -> Any:
    """READ-ONLY 项目内全文搜索（可限定 kind）。"""
    params: dict[str, Any] = {"q": q}
    if kind is not None:
        params["kind"] = kind
    return get_params(get_runtime().reader(), project_path(project_id, "/search"), params)


def get_requirement_tree(project_id: str) -> Any:
    """READ-ONLY 返回需求树（父子结构）。"""
    return get_params(get_runtime().reader(), project_path(project_id, "/requirements/tree"))


def get_item_history(project_id: str, item_id: str) -> Any:
    """READ-ONLY 返回任一实体项的变更历史。"""
    return get_params(get_runtime().reader(), project_path(project_id, f"/history/{item_id}"))


def list_comments(
    project_id: str,
    entity_kind: str | None = None,
    entity_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出实体评论（可按 entity_kind/entity_id 过滤）。"""
    params: dict[str, Any] = paginate(offset, limit)
    if entity_kind is not None:
        params["entity_kind"] = entity_kind
    if entity_id is not None:
        params["entity_id"] = entity_id
    return get_params(get_runtime().reader(), project_path(project_id, "/comments"), params)


def get_unreviewed_requirements(project_id: str) -> Any:
    """READ-ONLY 列出未评审需求。"""
    return get_params(get_runtime().reader(), project_path(project_id, "/unreviewed"))
