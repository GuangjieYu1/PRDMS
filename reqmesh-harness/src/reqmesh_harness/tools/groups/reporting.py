"""P4 复合技能②：追踪/覆盖缺口报告 READ 工具（1 个）。

- get_traceability_gap_report：单次调用 = 6 个 GET（coverage/gap-analysis/traces/
  suspect-links/unreviewed/allocation-matrix），复用同名 READ 处理器（tracking/
  requirements，不重复实现路由），聚合全部在工具处理器内部同步完成（P5 前无
  agent 运行时，design D5）——不拆分（READ 层无审批门/状态机复杂度，拆分只会把
  跨源拼接责任推回调用方）；
- 纯建议硬约束：绝不调用任何写工具/写端点（不 import writes 层、不触碰
  _write_common/审批门/审计）；tool_hint 仅引用既有写工具名；
- fail-fast：任一源 4xx/5xx → UpstreamError 透传（工具错误，无部分报告）；形状
  非法 → HarnessError（P3 get_requirement_quality 同款防御）；
- 与 get_project_report 的边界（spec ④）：独立工具，不扩展 report 枚举——
  get_project_report = 服务端计算型报告端点 1:1 路由透传；本报告 = 客户端多源聚合。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...report import DimensionType, build_report
from . import requirements, tracking


def get_traceability_gap_report(
    project_id: str,
    dimensions: list[DimensionType] | None = None,
) -> Any:
    """READ-ONLY 返回项目级追踪/覆盖缺口报告：一次调用聚合 coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix 六源（仅 GET），输出 summary/chapters/gaps/meta 结构化报告；每条缺口带规则驱动的建议修复动作（仅建议，绝不执行——tool_hint 只引用既有写工具名，caller 自行决定是否经审批门执行）。任一源失败整体报错（fail-fast，无部分报告）；dimensions 白名单（12 类维度类型）过滤 chapters/gaps，summary 保持全量。"""
    # 六源采集（复用同名 READ 处理器；全部 GET，无任何写调用）
    cov = tracking.get_coverage(project_id)
    gap = tracking.get_gap_analysis(project_id)
    trc = tracking.get_traces(project_id)
    sus = tracking.get_suspect_links(project_id)
    unrev = requirements.get_unreviewed_requirements(project_id)
    alloc = tracking.get_allocation_matrix(project_id)
    return build_report(
        project_id=project_id,
        coverage=cov,
        gap_analysis=gap,
        traces=trc,
        suspect_links=sus,
        unreviewed=unrev,
        allocation=alloc,
        dimensions=dimensions,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = ["get_traceability_gap_report"]
