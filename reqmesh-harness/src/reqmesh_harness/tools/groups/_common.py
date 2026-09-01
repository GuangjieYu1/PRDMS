"""工具组公共设施。"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from ..runtime import get_runtime

# 分页：透传 reqmesh 分页（默认 500 / 上限 2000），不自动翻页（P3/P4 复合技能负责）
PageOffset = Annotated[int, Field(ge=0, description="偏移量（从 0 开始）")]
PageLimit = Annotated[int, Field(ge=1, le=2000, description="每页条数，最大 2000，默认 500")]

PROJECT_PATH = "/api/projects"


def project_path(project_id: str, suffix: str = "") -> str:
    return f"{PROJECT_PATH}/{project_id}{suffix}"


def read_json(path: str, params: dict[str, Any] | None = None) -> Any:
    """只读请求唯一入口（结构上仅 get()）；处理器从这里取得客户端。"""
    return get_runtime().reader().get(path, params)


def merged_list_or_get(
    project_id: str,
    collection: str,
    item_id: str | None,
    offset: int,
    limit: int,
) -> Any:
    """合并模式（ADR-0002）：省略 <entity>_id 返回分页集合，给出则路由到单条端点。"""
    if item_id:
        return read_json(project_path(project_id, f"/{collection}/{item_id}"))
    return read_json(project_path(project_id, f"/{collection}"), {"offset": offset, "limit": limit})
