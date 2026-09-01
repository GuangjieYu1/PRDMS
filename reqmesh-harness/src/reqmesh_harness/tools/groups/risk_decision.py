"""风险/决策/验证/分析/规格/定义域 READ 工具组（7 个）。"""

from __future__ import annotations

from typing import Any

from ..runtime import get_runtime
from ._common import PageLimit, PageOffset, get_params, paginate, project_path


def list_risks(
    project_id: str,
    risk_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出风险（risk_id 给出时返回单个风险）。"""
    if risk_id:
        return get_params(get_runtime().reader(), project_path(project_id, f"/risks/{risk_id}"))
    return get_params(
        get_runtime().reader(), project_path(project_id, "/risks"), paginate(offset, limit)
    )


def get_risk_matrix(project_id: str) -> Any:
    """READ-ONLY 返回风险矩阵（可能性×严重度）。"""
    return get_params(get_runtime().reader(), project_path(project_id, "/risk-matrix"))


def list_decisions(
    project_id: str,
    dec_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出决策记录（dec_id 给出时返回单条）。"""
    if dec_id:
        return get_params(get_runtime().reader(), project_path(project_id, f"/decisions/{dec_id}"))
    return get_params(
        get_runtime().reader(), project_path(project_id, "/decisions"), paginate(offset, limit)
    )


def list_verification_cases(
    project_id: str,
    vc_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出验证用例（vc_id 给出时返回单个）。"""
    if vc_id:
        return get_params(get_runtime().reader(), project_path(project_id, f"/verification/{vc_id}"))
    return get_params(
        get_runtime().reader(), project_path(project_id, "/verification"), paginate(offset, limit)
    )


def list_analysis_cases(
    project_id: str,
    case_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出分析案例（case_id 给出时返回单个）。"""
    if case_id:
        return get_params(get_runtime().reader(), project_path(project_id, f"/analysis/{case_id}"))
    return get_params(
        get_runtime().reader(), project_path(project_id, "/analysis"), paginate(offset, limit)
    )


def list_specifications(
    project_id: str,
    spec_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出规格文档（spec_id 给出时返回单个）。"""
    if spec_id:
        return get_params(
            get_runtime().reader(), project_path(project_id, f"/specifications/{spec_id}")
        )
    return get_params(
        get_runtime().reader(), project_path(project_id, "/specifications"), paginate(offset, limit)
    )


def list_definitions(
    project_id: str,
    def_id: str | None = None,
    offset: PageOffset = 0,
    limit: PageLimit = 500,
) -> Any:
    """READ-ONLY 列出定义/术语（def_id 给出时返回单个）。"""
    if def_id:
        return get_params(get_runtime().reader(), project_path(project_id, f"/definitions/{def_id}"))
    return get_params(
        get_runtime().reader(), project_path(project_id, "/definitions"), paginate(offset, limit)
    )
