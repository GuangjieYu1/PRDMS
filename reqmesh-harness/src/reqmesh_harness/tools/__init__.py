"""工具层：注册表（唯一事实源）+ 27 个 READ 工具 + 13 个写工具（含 P3/P4 复合技能）。

全部工具按 ADR-0002 命名（verb_entity、无权限前缀）；description 唯一来源 =
处理器 docstring：READ 层以 READ-ONLY 开头、写层以 DRAFT/MUTATE 开头（中文书写）；
权限层级记录在注册表（level 字段）并经 `annotations_for` 映射 MCP annotations。
ADMIN 分区（P2 不注册任何 ADMIN 工具）：`add_admin` + `REQMESH_ENABLE_ADMIN=1`
显式开启后才安装（未开启时不出现在 tools/list）。审批门（guardrails）从注册表
映射层级，绝不解析工具名。
"""

from .registry import ToolRegistry, ToolSpec, annotations_for
from .groups import auth_project, requirements, tracking, risk_decision, components_report
from .groups import writes, skills, reporting

__all__ = ["ToolRegistry", "ToolSpec", "annotations_for", "build_registry"]


def _spec(name: str, title: str, domain: str, fn) -> ToolSpec:
    return ToolSpec(name=name, title=title, domain=domain, level="READ", fn=fn)


def _write_spec(name: str, title: str, domain: str, level: str, fn) -> ToolSpec:
    return ToolSpec(name=name, title=title, domain=domain, level=level, fn=fn)


# ADMIN 分区（P2 预留：不注册任何 ADMIN 工具——见 spec「显式开启预留设计」；
# 未来 phase 上线 = 本元组加行 + spec 映射表加行，审批门零改动）
ADMIN_TOOL_SPECS: tuple[ToolSpec, ...] = ()


def build_registry(enable_admin: bool | None = None) -> ToolRegistry:
    """构建注册表（唯一事实源）。

    `enable_admin`：None 时按 `REQMESH_ENABLE_ADMIN` 环境变量决定（默认关闭）——
    关闭时 ADMIN 分区不安装（tools/list 不含 ADMIN 工具，协议层不存在）。
    """
    if enable_admin is None:
        from ..config import get_settings

        enable_admin = get_settings().enable_admin
    registry = ToolRegistry(enable_admin=enable_admin)
    registry.add(_spec("whoami", "当前用户", "认证/项目", auth_project.whoami))
    registry.add(_spec("list_projects", "列出项目", "认证/项目", auth_project.list_projects))
    registry.add(_spec("list_requirements", "列出需求", "需求", requirements.list_requirements))
    registry.add(_spec("get_requirement", "获取需求", "需求", requirements.get_requirement))
    registry.add(_spec("search_requirements", "搜索项目", "需求", requirements.search_requirements))
    registry.add(_spec("get_requirement_tree", "需求树", "需求", requirements.get_requirement_tree))
    registry.add(_spec("get_item_history", "实体历史", "需求", requirements.get_item_history))
    registry.add(_spec("list_comments", "列出评论", "需求", requirements.list_comments))
    registry.add(_spec("get_unreviewed_requirements", "未评审需求", "需求", requirements.get_unreviewed_requirements))
    registry.add(_spec("get_traces", "追踪矩阵", "追踪/覆盖", tracking.get_traces))
    registry.add(_spec("get_coverage", "覆盖率分析", "追踪/覆盖", tracking.get_coverage))
    registry.add(_spec("get_gap_analysis", "缺口分析", "追踪/覆盖", tracking.get_gap_analysis))
    registry.add(_spec("get_allocation_matrix", "分配矩阵", "追踪/覆盖", tracking.get_allocation_matrix))
    registry.add(_spec("get_suspect_links", "可疑追踪链接", "追踪/覆盖", tracking.get_suspect_links))
    registry.add(_spec("list_risks", "列出风险", "风险/决策", risk_decision.list_risks))
    registry.add(_spec("get_risk_matrix", "风险矩阵", "风险/决策", risk_decision.get_risk_matrix))
    registry.add(_spec("list_decisions", "列出决策", "风险/决策", risk_decision.list_decisions))
    registry.add(_spec("list_verification_cases", "列出验证用例", "验证/分析/规格/定义", risk_decision.list_verification_cases))
    registry.add(_spec("list_analysis_cases", "列出分析案例", "验证/分析/规格/定义", risk_decision.list_analysis_cases))
    registry.add(_spec("list_specifications", "列出规格文档", "验证/分析/规格/定义", risk_decision.list_specifications))
    registry.add(_spec("list_definitions", "列出定义", "验证/分析/规格/定义", risk_decision.list_definitions))
    registry.add(_spec("list_components", "列出组件", "组件/基线/变更请求", components_report.list_components))
    registry.add(_spec("list_baselines", "列出基线", "组件/基线/变更请求", components_report.list_baselines))
    registry.add(_spec("list_change_requests", "列出变更请求", "组件/基线/变更请求", components_report.list_change_requests))
    registry.add(_spec("get_project_report", "项目报告", "报告", components_report.get_project_report))

    # P2 写工具（6 DRAFT + 6 MUTATE，spec 映射表为契约）
    registry.add(_write_spec("create_requirement", "新建需求", "需求", "DRAFT", writes.create_requirement))
    registry.add(_write_spec("create_component", "新建组件", "组件/基线/变更请求", "DRAFT", writes.create_component))
    registry.add(_write_spec("create_verification_case", "新建验证用例", "验证/分析/规格/定义", "DRAFT", writes.create_verification_case))
    registry.add(_write_spec("create_risk", "新建风险", "风险/决策", "DRAFT", writes.create_risk))
    registry.add(_write_spec("create_comment", "新建评论", "需求", "DRAFT", writes.create_comment))
    registry.add(_write_spec("review_item", "提交评审", "需求", "DRAFT", writes.review_item))
    registry.add(_write_spec("update_requirement", "更新需求", "需求", "MUTATE", writes.update_requirement))
    registry.add(_write_spec("set_relations", "设置追踪矩阵", "追踪/覆盖", "MUTATE", writes.set_relations))
    registry.add(_write_spec("set_allocation", "设置分配", "追踪/覆盖", "MUTATE", writes.set_allocation))
    registry.add(_write_spec("update_component", "更新组件", "组件/基线/变更请求", "MUTATE", writes.update_component))
    registry.add(_write_spec("update_verification_case", "更新验证用例", "验证/分析/规格/定义", "MUTATE", writes.update_verification_case))
    registry.add(_write_spec("run_verification", "执行验证", "验证/分析/规格/定义", "MUTATE", writes.run_verification))

    # P3 复合技能①：自然语言建需求（DRAFT 层；domain=复合技能，P2/P3 预告 P4 复合技能②并入）
    registry.add(_write_spec("draft_requirement", "自然语言建需求", "复合技能", "DRAFT", skills.draft_requirement))
    registry.add(_spec("get_requirement_quality", "需求品质反馈", "需求", skills.get_requirement_quality))

    # P4 复合技能②：追踪/覆盖缺口报告（READ 层；客户端六源聚合，独立工具——
    # 不扩展 get_project_report 的 report 枚举，见 ADR-0002 P4 实现注记与 spec ④）
    registry.add(_spec("get_traceability_gap_report", "追踪/覆盖缺口报告", "复合技能", reporting.get_traceability_gap_report))

    for spec in ADMIN_TOOL_SPECS:
        registry.add_admin(spec)
    return registry
