"""工具层：注册表（唯一事实源）+ 25 个 READ 工具。

全部工具按 ADR-0002 命名（verb_entity、无权限前缀）；description 以 READ-ONLY
开头、中文书写（唯一来源 = 处理器 docstring）；权限层级 READ 记录在注册表
（level 字段）与 MCP annotations.readOnlyHint。
"""

from .registry import ToolRegistry, ToolSpec
from .groups import auth_project, requirements, tracking, risk_decision, components_report

__all__ = ["ToolRegistry", "ToolSpec", "build_registry"]


def _spec(name: str, title: str, domain: str, fn) -> ToolSpec:
    return ToolSpec(name=name, title=title, domain=domain, level="READ", fn=fn)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
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
    return registry
