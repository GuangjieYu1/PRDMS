"""工具组公共设施。"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

# 分页：透传 reqmesh 分页（默认 500 / 上限 2000），不自动翻页（P3/P4 复合技能负责）
PageOffset = Annotated[int, Field(ge=0, description="偏移量（从 0 开始）")]
PageLimit = Annotated[int, Field(ge=1, le=2000, description="每页条数，最大 2000，默认 500")]

PROJECT_PATH = "/api/projects"


def project_path(project_id: str, suffix: str = "") -> str:
    return f"{PROJECT_PATH}/{project_id}{suffix}"


def paginate(offset: int, limit: int) -> dict[str, int]:
    return {"offset": offset, "limit": limit}


def get_params(client: Any, path: str, params: dict[str, Any] | None = None) -> Any:
    """统一 GET 入口：只读视图（结构上仅 get()）。"""
    return client.get(path, params)
