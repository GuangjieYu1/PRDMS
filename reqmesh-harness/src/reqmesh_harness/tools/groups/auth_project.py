"""认证/项目域 READ 工具：whoami、list_projects。"""

from __future__ import annotations

from typing import Any

from ._common import PROJECT_PATH, read_json


def whoami() -> Any:
    """READ-ONLY 返回当前登录用户与角色（身份核验）。"""
    return read_json("/api/auth/whoami")


def list_projects(project_id: str | None = None) -> Any:
    """READ-ONLY 列出项目；给出 project_id 时返回单个项目详情。"""
    if project_id:
        return read_json(f"{PROJECT_PATH}/{project_id}")
    return read_json(PROJECT_PATH)
