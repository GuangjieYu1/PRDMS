"""spec 映射表（Implementation Decisions 表格）的可执行版本：注册契约。

每个工具声明：name（ADR-0002）、domain、参数（名称/粗类型/必需/默认值）、
以及若干调用分支 Case（样例参数 → 期望路径/查询串/响应 fixture）。
测试用本表对注册表做逐项对账（schema 校验 + 路由 + 只读 + envelope 透传）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

MISSING = object()


@dataclass(frozen=True)
class Param:
    name: str
    types: tuple[str, ...]  # 粗类型：string/integer/boolean
    required: bool = False
    default: object = MISSING


@dataclass(frozen=True)
class Case:
    name: str
    args: dict
    expect_path: str
    expect_query: dict | None
    fixture: str
    method: str = "GET"
    expect_body: dict | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ToolMap:
    name: str
    domain: str
    params: tuple[Param, ...]
    cases: tuple[Case, ...] = field(default_factory=tuple)
    level: str = "READ"


S = ("string",)
I = ("integer",)
B = ("boolean",)

TOOLS: tuple[ToolMap, ...] = (
    ToolMap(
        name="whoami",
        domain="认证/项目",
        params=(),
        cases=(
            Case("baseline", {}, "/api/auth/whoami", None, "whoami.json"),
        ),
    ),
    ToolMap(
        name="list_projects",
        domain="认证/项目",
        params=(Param("project_id", S, required=False, default=None),),
        cases=(
            Case("list", {}, "/api/projects", None, "projects_list.json"),
            Case("detail", {"project_id": "cessna-172"}, "/api/projects/cessna-172", None, "project_detail.json"),
        ),
    ),
    ToolMap(
        name="list_requirements",
        domain="需求",
        params=(
            Param("project_id", S, required=True),
            Param("search", S, required=False, default=None),
            Param("type", S, required=False, default=None),
            Param("status", S, required=False, default=None),
            Param("priority", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("filtered", {"project_id": "cessna-172", "search": "fuel", "status": "verified", "priority": "high", "offset": 10, "limit": 3},
                 "/api/projects/cessna-172/requirements",
                 {"search": "fuel", "status": "verified", "priority": "high", "offset": 10, "limit": 3},
                 "requirements_list.json"),
            Case("defaults", {"project_id": "cessna-172"},
                 "/api/projects/cessna-172/requirements", {"offset": 0, "limit": 500}, "requirements_list.json"),
        ),
    ),
    ToolMap(
        name="get_requirement",
        domain="需求",
        params=(Param("project_id", S, required=True), Param("req_id", S, required=True)),
        cases=(
            Case("by_id", {"project_id": "cessna-172", "req_id": "ACFT0000"},
                 "/api/projects/cessna-172/requirements/ACFT0000", None, "requirement_get.json"),
        ),
    ),
    ToolMap(
        name="search_requirements",
        domain="需求",
        params=(Param("project_id", S, required=True), Param("q", S, required=True), Param("kind", S, required=False, default=None)),
        cases=(
            Case("with_kind", {"project_id": "cessna-172", "q": "fuel", "kind": "requirement"},
                 "/api/projects/cessna-172/search", {"q": "fuel", "kind": "requirement"}, "search_results.json"),
            Case("bare", {"project_id": "cessna-172", "q": "fuel"},
                 "/api/projects/cessna-172/search", {"q": "fuel"}, "search_results.json"),
        ),
    ),
    ToolMap(
        name="get_requirement_tree",
        domain="需求",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("tree", {"project_id": "cessna-172"}, "/api/projects/cessna-172/requirements/tree", None, "requirement_tree.json"),
        ),
    ),
    ToolMap(
        name="get_item_history",
        domain="需求",
        params=(Param("project_id", S, required=True), Param("item_id", S, required=True)),
        cases=(
            Case("by_item", {"project_id": "cessna-172", "item_id": "ACFT0000"},
                 "/api/projects/cessna-172/history/ACFT0000", None, "item_history.json"),
        ),
    ),
    ToolMap(
        name="list_comments",
        domain="需求",
        params=(
            Param("project_id", S, required=True),
            Param("entity_kind", S, required=False, default=None),
            Param("entity_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("all", {"project_id": "cessna-172"},
                 "/api/projects/cessna-172/comments", {"offset": 0, "limit": 500}, "comments_list.json"),
            Case("entity_filter", {"project_id": "cessna-172", "entity_kind": "requirement", "entity_id": "ACFT0000"},
                 "/api/projects/cessna-172/comments",
                 {"entity_kind": "requirement", "entity_id": "ACFT0000", "offset": 0, "limit": 500},
                 "comments_list.json"),
        ),
    ),
    ToolMap(
        name="get_unreviewed_requirements",
        domain="需求",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("unreviewed", {"project_id": "cessna-172"}, "/api/projects/cessna-172/unreviewed", None, "unreviewed.json"),
        ),
    ),
    ToolMap(
        name="get_traces",
        domain="追踪/覆盖",
        params=(
            Param("project_id", S, required=True),
            Param("entity_id", S, required=False, default=None),
            Param("collection", S, required=False, default=None),
        ),
        cases=(
            Case("matrix", {"project_id": "cessna-172"}, "/api/projects/cessna-172/traces", None, "traces.json"),
            Case("backlinks", {"project_id": "cessna-172", "entity_id": "ACFT0000"},
                 "/api/projects/cessna-172/entities/ACFT0000/backlinks", None, "backlinks.json"),
            Case("backlinks_collection", {"project_id": "cessna-172", "entity_id": "ACFT0000", "collection": "requirement"},
                 "/api/projects/cessna-172/entities/ACFT0000/backlinks", {"collection": "requirement"}, "backlinks.json"),
        ),
    ),
    ToolMap(
        name="get_coverage",
        domain="追踪/覆盖",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("coverage", {"project_id": "cessna-172"}, "/api/projects/cessna-172/coverage", None, "coverage.json"),
        ),
    ),
    ToolMap(
        name="get_gap_analysis",
        domain="追踪/覆盖",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("gaps", {"project_id": "cessna-172"}, "/api/projects/cessna-172/gap-analysis", None, "gap_analysis.json"),
        ),
    ),
    ToolMap(
        name="get_allocation_matrix",
        domain="追踪/覆盖",
        params=(
            Param("project_id", S, required=True),
            Param("axis", S, required=False, default=None),
            Param("rows", S, required=False, default=None),
            Param("search", S, required=False, default=None),
            Param("filter_type", S, required=False, default=None),
        ),
        cases=(
            Case("all", {"project_id": "cessna-172", "axis": "requirements", "rows": "components", "search": "fuel", "filter_type": "direct"},
                 "/api/projects/cessna-172/allocation-matrix",
                 {"axis": "requirements", "rows": "components", "search": "fuel", "filter_type": "direct"},
                 "allocation_matrix.json"),
            Case("bare", {"project_id": "cessna-172"}, "/api/projects/cessna-172/allocation-matrix", None, "allocation_matrix.json"),
        ),
    ),
    ToolMap(
        name="get_suspect_links",
        domain="追踪/覆盖",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("suspect", {"project_id": "cessna-172"}, "/api/projects/cessna-172/suspect-links", None, "suspect_links.json"),
        ),
    ),
    ToolMap(
        name="list_risks",
        domain="风险/决策",
        params=(
            Param("project_id", S, required=True),
            Param("risk_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/risks", {"offset": 0, "limit": 500}, "risks_list.json"),
            Case("single", {"project_id": "cessna-172", "risk_id": "RSK00006"}, "/api/projects/cessna-172/risks/RSK00006", None, "risk_get.json"),
        ),
    ),
    ToolMap(
        name="get_risk_matrix",
        domain="风险/决策",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("matrix", {"project_id": "cessna-172"}, "/api/projects/cessna-172/risk-matrix", None, "risk_matrix.json"),
        ),
    ),
    ToolMap(
        name="list_decisions",
        domain="风险/决策",
        params=(
            Param("project_id", S, required=True),
            Param("dec_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/decisions", {"offset": 0, "limit": 500}, "decisions_list.json"),
            Case("single", {"project_id": "cessna-172", "dec_id": "DEC0008"}, "/api/projects/cessna-172/decisions/DEC0008", None, "decision_get.json"),
        ),
    ),
    ToolMap(
        name="list_verification_cases",
        domain="验证/分析/规格/定义",
        params=(
            Param("project_id", S, required=True),
            Param("vc_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/verification", {"offset": 0, "limit": 500}, "verification_list.json"),
            Case("single", {"project_id": "cessna-172", "vc_id": "VCAF0001"}, "/api/projects/cessna-172/verification/VCAF0001", None, "verification_get.json"),
        ),
    ),
    ToolMap(
        name="list_analysis_cases",
        domain="验证/分析/规格/定义",
        params=(
            Param("project_id", S, required=True),
            Param("case_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/analysis", {"offset": 0, "limit": 500}, "analysis_list.json"),
            Case("single", {"project_id": "cessna-172", "case_id": "avionics-upgrade"}, "/api/projects/cessna-172/analysis/avionics-upgrade", None, "analysis_get.json"),
        ),
    ),
    ToolMap(
        name="list_specifications",
        domain="验证/分析/规格/定义",
        params=(
            Param("project_id", S, required=True),
            Param("spec_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/specifications", {"offset": 0, "limit": 500}, "specifications_list.json"),
            Case("single", {"project_id": "cessna-172", "spec_id": "SPEC-AVIO"}, "/api/projects/cessna-172/specifications/SPEC-AVIO", None, "specification_get.json"),
        ),
    ),
    ToolMap(
        name="list_definitions",
        domain="验证/分析/规格/定义",
        params=(
            Param("project_id", S, required=True),
            Param("def_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/definitions", {"offset": 0, "limit": 500}, "definitions_list.json"),
            Case("single", {"project_id": "cessna-172", "def_id": "MassBudget"}, "/api/projects/cessna-172/definitions/MassBudget", None, "definition_get.json"),
        ),
    ),
    ToolMap(
        name="list_components",
        domain="组件/基线/变更请求",
        params=(
            Param("project_id", S, required=True),
            Param("component_id", S, required=False, default=None),
            Param("search", S, required=False, default=None),
            Param("type", S, required=False, default=None),
            Param("satisfies", S, required=False, default=None),
            Param("as_tree", B, required=False, default=False),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/components", {"offset": 0, "limit": 500}, "components_list.json"),
            Case("filters", {"project_id": "cessna-172", "search": "wing", "type": "system", "satisfies": "ACFT0000"},
                 "/api/projects/cessna-172/components",
                 {"search": "wing", "type": "system", "satisfies": "ACFT0000", "offset": 0, "limit": 500},
                 "components_list.json"),
            Case("tree", {"project_id": "cessna-172", "as_tree": True}, "/api/projects/cessna-172/components/tree", None, "components_tree.json"),
            Case("single", {"project_id": "cessna-172", "component_id": "AILR01"}, "/api/projects/cessna-172/components/AILR01", None, "component_get.json"),
        ),
    ),
    ToolMap(
        name="list_baselines",
        domain="组件/基线/变更请求",
        params=(Param("project_id", S, required=True),),
        cases=(
            Case("baselines", {"project_id": "cessna-172"}, "/api/projects/cessna-172/baselines", None, "baselines_list.json"),
        ),
    ),
    ToolMap(
        name="list_change_requests",
        domain="组件/基线/变更请求",
        params=(
            Param("project_id", S, required=True),
            Param("cr_id", S, required=False, default=None),
            Param("offset", I, required=False, default=0),
            Param("limit", I, required=False, default=500),
        ),
        cases=(
            Case("list", {"project_id": "cessna-172"}, "/api/projects/cessna-172/change-requests", {"offset": 0, "limit": 500}, "change_requests_list.json"),
            Case("single", {"project_id": "cessna-172", "cr_id": "CR000004"}, "/api/projects/cessna-172/change-requests/CR000004", None, "change_request_get.json"),
        ),
    ),
    ToolMap(
        name="get_project_report",
        domain="报告",
        params=(Param("project_id", S, required=True), Param("report", ("enum",), required=True)),
        cases=(
            Case("quality", {"project_id": "cessna-172", "report": "quality"}, "/api/projects/cessna-172/quality", None, "report_quality.json"),
            Case("compliance", {"project_id": "cessna-172", "report": "compliance"}, "/api/projects/cessna-172/compliance", None, "report_compliance.json"),
            Case("metrics", {"project_id": "cessna-172", "report": "metrics"}, "/api/projects/cessna-172/metrics", None, "report_metrics.json"),
            Case("evaluation", {"project_id": "cessna-172", "report": "evaluation"}, "/api/projects/cessna-172/evaluation", None, "report_evaluation.json"),
            Case("validation", {"project_id": "cessna-172", "report": "validation"}, "/api/projects/cessna-172/validate", None, "report_validate.json"),
            Case("workflow", {"project_id": "cessna-172", "report": "workflow"}, "/api/projects/cessna-172/workflow", None, "report_workflow.json"),
        ),
    ),
)


def write_by_name() -> dict[str, ToolMap]:
    return {t.name: t for t in WRITE_TOOLS}


# ------------------------------------------------------------------ P2 写工具（spec 映射表契约；method/body/reason/dry_run）
A = ("array",)
O = ("object",)
E = ("enum",)

WRITE_TOOLS: tuple[ToolMap, ...] = (
    ToolMap(
        name="create_requirement",
        domain="需求",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("id", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("type", E),
            Param("priority", E),
            Param("status", E),
            Param("parent", S),
            Param("attributes", A),
            Param("parameters", A),
            Param("constraints", A),
            Param("relations", A),
            Param("verification_cases", A),
            Param("cascade_from", S),
            Param("rationale", S),
            Param("source", S),
            Param("allocated_to", S),
            Param("baselines", A),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("dry_run", {"project_id": "cessna-172", "id": "SMOKE-P2-001", "name": "Fuel", "dry_run": True},
                 "/api/projects/cessna-172/requirements", None, "requirement_get.json",
                 method="POST", expect_body={"id": "SMOKE-P2-001", "name": "Fuel"}, dry_run=True),
            Case("real", {"project_id": "cessna-172", "id": "SMOKE-P2-001", "name": "Fuel"},
                 "/api/projects/cessna-172/requirements", None, "requirement_get.json",
                 method="POST", expect_body={"id": "SMOKE-P2-001", "name": "Fuel"}),
        ),
    ),
    ToolMap(
        name="create_component",
        domain="组件/基线/变更请求",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("id", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("type", E),
            Param("parent", S),
            Param("part_number", S),
            Param("supplier", S),
            Param("quantity", I),
            Param("satisfies", A),
            Param("verification_cases", A),
            Param("relations", A),
            Param("attributes", A),
            Param("parameters", A),
            Param("baselines", A),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "id": "SMOKE-P2-C01", "name": "SMOKE Wing"},
                 "/api/projects/cessna-172/components", None, "component_get.json",
                 method="POST", expect_body={"id": "SMOKE-P2-C01", "name": "SMOKE Wing"}),
        ),
    ),
    ToolMap(
        name="create_verification_case",
        domain="验证/分析/规格/定义",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("id", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("method", S),
            Param("case_type", E),
            Param("environment", S),
            Param("decision_gate", S),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "id": "SMOKE-P2-V01", "name": "SMOKE VCase"},
                 "/api/projects/cessna-172/verification", None, "verification_get.json",
                 method="POST", expect_body={"id": "SMOKE-P2-V01", "name": "SMOKE VCase"}),
        ),
    ),
    ToolMap(
        name="create_risk",
        domain="风险/决策",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("id", S, required=True),
            Param("title", S),
            Param("failure_mode", S),
            Param("effect", S),
            Param("cause", S),
            Param("severity", S),
            Param("likelihood", S),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "id": "SMOKE-P2-R01", "title": "SMOKE Risk"},
                 "/api/projects/cessna-172/risks", None, "risk_get.json",
                 method="POST", expect_body={"id": "SMOKE-P2-R01", "title": "SMOKE Risk"}),
        ),
    ),
    ToolMap(
        name="create_comment",
        domain="需求",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("entity_kind", S, required=True),
            Param("entity_id", S, required=True),
            Param("text", S, required=True),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "entity_kind": "requirement", "entity_id": "ACFT0000", "text": "SMOKE comment"},
                 "/api/projects/cessna-172/comments", None, "comments_list.json",
                 method="POST", expect_body={"entity_kind": "requirement", "entity_id": "ACFT0000", "text": "SMOKE comment"}),
        ),
    ),
    ToolMap(
        name="review_item",
        domain="需求",
        level="DRAFT",
        params=(
            Param("project_id", S, required=True),
            Param("req_id", S, required=True),
            Param("comment", S),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "req_id": "ACFT0000", "comment": "LGTM"},
                 "/api/projects/cessna-172/requirements/ACFT0000/review", None, "requirement_get.json",
                 method="POST", expect_body={"comment": "LGTM"}),
        ),
    ),
    ToolMap(
        name="update_requirement",
        domain="需求",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("req_id", S, required=True),
            Param("reason", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("type", E),
            Param("priority", E),
            Param("status", E),
            Param("parent", S),
            Param("attributes", A),
            Param("parameters", A),
            Param("constraints", A),
            Param("relations", A),
            Param("verification_cases", A),
            Param("cascade_from", S),
            Param("rationale", S),
            Param("source", S),
            Param("allocated_to", S),
            Param("baselines", A),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("partial", {"project_id": "cessna-172", "req_id": "ACFT0000", "reason": "SMOKE 更新", "description": "updated"},
                 "/api/projects/cessna-172/requirements/ACFT0000", None, "requirement_get.json",
                 method="PUT", expect_body={"description": "updated"}),
            Case("null_clears", {"project_id": "cessna-172", "req_id": "ACFT0000", "reason": "SMOKE 清空", "description": None},
                 "/api/projects/cessna-172/requirements/ACFT0000", None, "requirement_get.json",
                 method="PUT", expect_body={"description": None}),
        ),
    ),
    ToolMap(
        name="set_relations",
        domain="追踪/覆盖",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("links", A, required=True),
            Param("reason", S, required=True),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("rewrite", {"project_id": "cessna-172", "reason": "SMOKE 追加", "links": [{"source": "ACFT0000", "target": "AFRM0000", "type": "refines"}]},
                 "/api/projects/cessna-172/traces", None, "traces.json",
                 method="PUT", expect_body={"links": [{"source": "ACFT0000", "target": "AFRM0000", "type": "refines"}]}),
        ),
    ),
    ToolMap(
        name="set_allocation",
        domain="追踪/覆盖",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("req_id", S, required=True),
            Param("reason", S, required=True),
            Param("row_id", S),
            Param("row_kind", S),
            Param("target_id", S),
            Param("component_id", S),
            Param("axis", S),
            Param("allocated", B),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "req_id": "ACFT0000", "reason": "SMOKE 分配", "allocated": True},
                 "/api/projects/cessna-172/allocation", None, "allocation_matrix.json",
                 method="POST", expect_body={"req_id": "ACFT0000", "allocated": True}),
        ),
    ),
    ToolMap(
        name="update_component",
        domain="组件/基线/变更请求",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("component_id", S, required=True),
            Param("reason", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("type", E),
            Param("parent", S),
            Param("part_number", S),
            Param("supplier", S),
            Param("quantity", I),
            Param("satisfies", A),
            Param("verification_cases", A),
            Param("relations", A),
            Param("attributes", A),
            Param("parameters", A),
            Param("baselines", A),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "component_id": "AILR01", "reason": "SMOKE 更新", "description": "updated"},
                 "/api/projects/cessna-172/components/AILR01", None, "component_get.json",
                 method="PUT", expect_body={"description": "updated"}),
        ),
    ),
    ToolMap(
        name="update_verification_case",
        domain="验证/分析/规格/定义",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("vc_id", S, required=True),
            Param("reason", S, required=True),
            Param("name", S),
            Param("description", S),
            Param("method", S),
            Param("status", S),
            Param("result", S),
            Param("verified_requirements", A),
            Param("test_procedure", S),
            Param("steps", A),
            Param("case_type", E),
            Param("environment", S),
            Param("decision_gate", S),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "vc_id": "VCAF0001", "reason": "SMOKE 更新", "status": "passed"},
                 "/api/projects/cessna-172/verification/VCAF0001", None, "verification_get.json",
                 method="PUT", expect_body={"status": "passed"}),
        ),
    ),
    ToolMap(
        name="run_verification",
        domain="验证/分析/规格/定义",
        level="MUTATE",
        params=(
            Param("project_id", S, required=True),
            Param("vc_id", S, required=True),
            Param("status", S, required=True),
            Param("reason", S, required=True),
            Param("notes", S),
            Param("step_results", O),
            Param("dry_run", B, default=False),
        ),
        cases=(
            Case("real", {"project_id": "cessna-172", "vc_id": "VCAF0001", "status": "passed", "reason": "SMOKE 执行", "notes": "ok"},
                 "/api/projects/cessna-172/verification/VCAF0001/run", None, "verification_get.json",
                 method="POST", expect_body={"status": "passed", "notes": "ok"}),
        ),
    ),
)


def by_name() -> dict[str, ToolMap]:
    return {t.name: t for t in TOOLS}


READ_TOOL_COUNT = 25
WRITE_TOOL_COUNT = 12
EXPECTED_TOOL_COUNT = READ_TOOL_COUNT + WRITE_TOOL_COUNT
REPORT_ENUM = ["quality", "compliance", "metrics", "evaluation", "validation", "workflow"]
