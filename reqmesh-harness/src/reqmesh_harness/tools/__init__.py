"""工具层：注册表（唯一事实源）+ 25 个 READ 工具。

全部工具按 ADR-0002 命名（verb_entity、无权限前缀）；description 以 READ-ONLY
开头、中文书写；权限层级 READ 记录在注册表 + MCP annotations.readOnlyHint。
"""

from .registry import ToolRegistry, ToolSpec
from .groups import auth_project, requirements, tracking, risk_decision, components_report

__all__ = ["ToolRegistry", "ToolSpec", "build_registry"]


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.add(
        ToolSpec(
            name="whoami",
            title="当前用户",
            description="READ-ONLY 返回当前登录用户与角色（身份核验）。",
            domain="认证/项目",
            fn=auth_project.whoami,
        )
    )
    registry.add(
        ToolSpec(
            name="list_projects",
            title="列出项目",
            description="READ-ONLY 列出项目；给出 project_id 时返回单个项目详情。",
            domain="认证/项目",
            fn=auth_project.list_projects,
        )
    )
    registry.add(
        ToolSpec(
            name="list_requirements",
            title="列出需求",
            description="READ-ONLY 按过滤器列出需求（search/type/status/priority；分页 offset/limit 透传，默认 limit=500）。",
            domain="需求",
            fn=requirements.list_requirements,
        )
    )
    registry.add(
        ToolSpec(
            name="get_requirement",
            title="获取需求",
            description="READ-ONLY 按 id 返回单个需求完整内容。",
            domain="需求",
            fn=requirements.get_requirement,
        )
    )
    registry.add(
        ToolSpec(
            name="search_requirements",
            title="搜索项目",
            description="READ-ONLY 项目内全文搜索（可限定 kind）。",
            domain="需求",
            fn=requirements.search_requirements,
        )
    )
    registry.add(
        ToolSpec(
            name="get_requirement_tree",
            title="需求树",
            description="READ-ONLY 返回需求树（父子结构）。",
            domain="需求",
            fn=requirements.get_requirement_tree,
        )
    )
    registry.add(
        ToolSpec(
            name="get_item_history",
            title="实体历史",
            description="READ-ONLY 返回任一实体项的变更历史。",
            domain="需求",
            fn=requirements.get_item_history,
        )
    )
    registry.add(
        ToolSpec(
            name="list_comments",
            title="列出评论",
            description="READ-ONLY 列出实体评论（可按 entity_kind/entity_id 过滤）。",
            domain="需求",
            fn=requirements.list_comments,
        )
    )
    registry.add(
        ToolSpec(
            name="get_unreviewed_requirements",
            title="未评审需求",
            description="READ-ONLY 列出未评审需求。",
            domain="需求",
            fn=requirements.get_unreviewed_requirements,
        )
    )
    registry.add(
        ToolSpec(
            name="get_traces",
            title="追踪矩阵",
            description="READ-ONLY 返回追踪矩阵；给出 entity_id 时返回该实体的回链（backlinks）。",
            domain="追踪/覆盖",
            fn=tracking.get_traces,
        )
    )
    registry.add(
        ToolSpec(
            name="get_coverage",
            title="覆盖率分析",
            description="READ-ONLY 返回覆盖率分析（需求-验证/分析覆盖）。",
            domain="追踪/覆盖",
            fn=tracking.get_coverage,
        )
    )
    registry.add(
        ToolSpec(
            name="get_gap_analysis",
            title="缺口分析",
            description="READ-ONLY 返回覆盖缺口分析（未覆盖/欠覆盖集）。",
            domain="追踪/覆盖",
            fn=tracking.get_gap_analysis,
        )
    )
    registry.add(
        ToolSpec(
            name="get_allocation_matrix",
            title="分配矩阵",
            description="READ-ONLY 返回分配矩阵（axis/rows/search/filter_type 过滤）。",
            domain="追踪/覆盖",
            fn=tracking.get_allocation_matrix,
        )
    )
    registry.add(
        ToolSpec(
            name="get_suspect_links",
            title="可疑追踪链接",
            description="READ-ONLY 返回可疑追踪链接（编辑后失配）。",
            domain="追踪/覆盖",
            fn=tracking.get_suspect_links,
        )
    )
    registry.add(
        ToolSpec(
            name="list_risks",
            title="列出风险",
            description="READ-ONLY 列出风险（risk_id 给出时返回单个风险）。",
            domain="风险/决策",
            fn=risk_decision.list_risks,
        )
    )
    registry.add(
        ToolSpec(
            name="get_risk_matrix",
            title="风险矩阵",
            description="READ-ONLY 返回风险矩阵（可能性×严重度）。",
            domain="风险/决策",
            fn=risk_decision.get_risk_matrix,
        )
    )
    registry.add(
        ToolSpec(
            name="list_decisions",
            title="列出决策",
            description="READ-ONLY 列出决策记录（dec_id 给出时返回单条）。",
            domain="风险/决策",
            fn=risk_decision.list_decisions,
        )
    )
    registry.add(
        ToolSpec(
            name="list_verification_cases",
            title="列出验证用例",
            description="READ-ONLY 列出验证用例（vc_id 给出时返回单个）。",
            domain="验证/分析/规格/定义",
            fn=risk_decision.list_verification_cases,
        )
    )
    registry.add(
        ToolSpec(
            name="list_analysis_cases",
            title="列出分析案例",
            description="READ-ONLY 列出分析案例（case_id 给出时返回单个）。",
            domain="验证/分析/规格/定义",
            fn=risk_decision.list_analysis_cases,
        )
    )
    registry.add(
        ToolSpec(
            name="list_specifications",
            title="列出规格文档",
            description="READ-ONLY 列出规格文档（spec_id 给出时返回单个）。",
            domain="验证/分析/规格/定义",
            fn=risk_decision.list_specifications,
        )
    )
    registry.add(
        ToolSpec(
            name="list_definitions",
            title="列出定义",
            description="READ-ONLY 列出定义/术语（def_id 给出时返回单个）。",
            domain="验证/分析/规格/定义",
            fn=risk_decision.list_definitions,
        )
    )
    registry.add(
        ToolSpec(
            name="list_components",
            title="列出组件",
            description="READ-ONLY 列出组件（component_id 给出时返回单个；as_tree=true 返回组件树；search/type/satisfies 过滤）。",
            domain="组件/基线/变更请求",
            fn=components_report.list_components,
        )
    )
    registry.add(
        ToolSpec(
            name="list_baselines",
            title="列出基线",
            description="READ-ONLY 列出基线（里程碑）。",
            domain="组件/基线/变更请求",
            fn=components_report.list_baselines,
        )
    )
    registry.add(
        ToolSpec(
            name="list_change_requests",
            title="列出变更请求",
            description="READ-ONLY 列出变更请求（cr_id 给出时返回单个）。",
            domain="组件/基线/变更请求",
            fn=components_report.list_change_requests,
        )
    )
    registry.add(
        ToolSpec(
            name="get_project_report",
            title="项目报告",
            description="READ-ONLY 返回计算型项目报告（report: quality/compliance/metrics/evaluation/validation/workflow）。",
            domain="报告",
            fn=components_report.get_project_report,
        )
    )
    return registry
