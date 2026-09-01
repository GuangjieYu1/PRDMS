"""P2 写工具组（12 个 = 6 DRAFT + 6 MUTATE，spec 映射表为契约）。

- 全部工具统一 `dry_run: bool = False`（批准后仍只返回 would_send 预览，不发写请求）；
- 全部 MUTATE 工具统一必填 `reason: str`（仅进审计日志，不进 reqmesh 数据）；
- create 类 `id` 由调用方给定（reqmesh 契约如此；next-uid 端点延后）；
- 请求体序列化：P1 生成模型 + `exclude_unset`（未提供不发送；显式 None 原样发送=清空）；
- 层级（DRAFT/MUTATE）由注册表记录（ADR-0002），本模块函数不解析工具名；
- 错误透传：上游两种错误形状归一化 `UpstreamError`；审批未命中/ADMIN 未开启为类型化错误。
"""

from __future__ import annotations

from typing import Any

from ._common import project_path
from ._write_common import (
    UNSET,
    as_list,
    create_checks,
    entity_checks,
    id_exists,
    provided,
    relation_checks,
    write_request,
)
from ...client.generated.models import (
    AllocationRequest,
    CommentCreate,
    ComponentCreate,
    ComponentUpdate,
    RequirementCreate,
    RequirementUpdate,
    ReviewRequest,
    RiskCreate,
    RunVerification,
    TraceMatrix,
    VerificationCaseCreate,
    VerificationCaseUpdate,
)
from ...client.generated.models import (
    AttributeValue,
    CaseType,
    ComponentType,
    Constraint,
    Parameter,
    Priority,
    Reference,
    Relation,
    RequirementStatus,
    RequirementType,
    TestStep,
)

# 评论/实体的 entity_kind → 集合路径（dry_run 前置校验用）
_ENTITY_COLLECTIONS = {
    "requirement": "requirements",
    "component": "components",
    "verification": "verification",
    "risk": "risks",
    "decision": "decisions",
    "analysis": "analysis",
    "specification": "specifications",
    "definition": "definitions",
}


# ------------------------------------------------------------------ DRAFT（1–6）
def create_requirement(
    project_id: str,
    id: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    type: RequirementType | None = UNSET,
    priority: Priority | None = UNSET,
    status: RequirementStatus | None = UNSET,
    parent: str | None = UNSET,
    attributes: list[AttributeValue] | None = UNSET,
    parameters: list[Parameter] | None = UNSET,
    constraints: list[Constraint] | None = UNSET,
    relations: list[Relation] | None = UNSET,
    verification_cases: list[str] | None = UNSET,
    cascade_from: str | None = UNSET,
    rationale: str | None = UNSET,
    source: str | None = UNSET,
    allocated_to: str | None = UNSET,
    baselines: list[str] | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """DRAFT 在项目下新建需求（只增不改；id 由调用方给定，与 reqmesh 契约一致）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = RequirementCreate.model_validate(
        provided(id=id, name=name, description=description, type=type, priority=priority,
                 status=status, parent=parent, attributes=attributes, parameters=parameters,
                 constraints=constraints, relations=relations, verification_cases=verification_cases,
                 cascade_from=cascade_from, rationale=rationale, source=source,
                 allocated_to=allocated_to, baselines=baselines)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="create_requirement", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, "/requirements"), body=body, dry_run=dry_run,
        reason="", params=params,
        checks=lambda: create_checks(
            project_id, "requirements", id,
            refs=[("parent", "requirements", as_list(parent)),
                  ("verification_cases", "verification", as_list(verification_cases))],
        ),
    )


def create_component(
    project_id: str,
    id: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    type: ComponentType | None = UNSET,
    parent: str | None = UNSET,
    part_number: str | None = UNSET,
    supplier: str | None = UNSET,
    quantity: int | None = UNSET,
    satisfies: list[str] | None = UNSET,
    verification_cases: list[str] | None = UNSET,
    relations: list[Relation] | None = UNSET,
    attributes: list[AttributeValue] | None = UNSET,
    parameters: list[Parameter] | None = UNSET,
    baselines: list[str] | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """DRAFT 在项目下新建组件（只增不改；id 由调用方给定）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = ComponentCreate.model_validate(
        provided(id=id, name=name, description=description, type=type, parent=parent,
                 part_number=part_number, supplier=supplier, quantity=quantity,
                 satisfies=satisfies, verification_cases=verification_cases,
                 relations=relations, attributes=attributes, parameters=parameters,
                 baselines=baselines)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="create_component", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, "/components"), body=body, dry_run=dry_run,
        reason="", params=params,
        checks=lambda: create_checks(
            project_id, "components", id,
            refs=[("parent", "components", as_list(parent)),
                  ("satisfies", "requirements", as_list(satisfies)),
                  ("verification_cases", "verification", as_list(verification_cases))],
        ),
    )


def create_verification_case(
    project_id: str,
    id: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    method: str | None = UNSET,
    case_type: CaseType | None = UNSET,
    environment: str | None = UNSET,
    decision_gate: str | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """DRAFT 在项目下新建验证用例（只增不改；id 由调用方给定）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = VerificationCaseCreate.model_validate(
        provided(id=id, name=name, description=description, method=method,
                 case_type=case_type, environment=environment, decision_gate=decision_gate)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="create_verification_case", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, "/verification"), body=body, dry_run=dry_run,
        reason="", params=params,
        checks=lambda: create_checks(project_id, "verification", id),
    )


def create_risk(
    project_id: str,
    id: str,
    title: str | None = UNSET,
    failure_mode: str | None = UNSET,
    effect: str | None = UNSET,
    cause: str | None = UNSET,
    severity: str | None = UNSET,
    likelihood: str | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """DRAFT 在项目下新建风险条目（只增不改；id 由调用方给定）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = RiskCreate.model_validate(
        provided(id=id, title=title, failure_mode=failure_mode, effect=effect,
                 cause=cause, severity=severity, likelihood=likelihood)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="create_risk", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, "/risks"), body=body, dry_run=dry_run,
        reason="", params=params,
        checks=lambda: create_checks(project_id, "risks", id),
    )


def create_comment(
    project_id: str,
    entity_kind: str,
    entity_id: str,
    text: str,
    dry_run: bool = False,
) -> Any:
    """DRAFT 给任一实体附加讨论评论（工具层强制校验 entity_kind/entity_id/text 必填——上游 schema 未标 required）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = CommentCreate(entity_kind=entity_kind, entity_id=entity_id, text=text).model_dump(exclude_unset=True)
    collection = _ENTITY_COLLECTIONS.get(entity_kind)

    def _checks() -> list[dict[str, Any]]:
        if collection is None:
            return [{"kind": "unknown_entity_kind", "id": entity_kind,
                     "hint": f"entity_kind={entity_kind} 未在已知集合映射（{sorted(_ENTITY_COLLECTIONS)}）"}]
        return entity_checks(project_id, collection, entity_id)

    return write_request(
        tool="create_comment", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, "/comments"), body=body, dry_run=dry_run,
        reason="", params=params, checks=_checks,
    )


def review_item(
    project_id: str,
    req_id: str,
    comment: str | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """DRAFT 提交对某需求的评审（评审后该需求不再出现在未评审列表）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = ReviewRequest.model_validate(provided(comment=comment)).model_dump(exclude_unset=True)
    return write_request(
        tool="review_item", level="DRAFT", project_id=project_id, method="POST",
        path=project_path(project_id, f"/requirements/{req_id}/review"), body=body,
        dry_run=dry_run, reason="", params=params,
        checks=lambda: entity_checks(project_id, "requirements", req_id),
    )


# ------------------------------------------------------------------ MUTATE（7–12）
def update_requirement(
    project_id: str,
    req_id: str,
    reason: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    type: RequirementType | None = UNSET,
    priority: Priority | None = UNSET,
    status: RequirementStatus | None = UNSET,
    parent: str | None = UNSET,
    attributes: list[AttributeValue] | None = UNSET,
    parameters: list[Parameter] | None = UNSET,
    constraints: list[Constraint] | None = UNSET,
    relations: list[Relation] | None = UNSET,
    verification_cases: list[str] | None = UNSET,
    cascade_from: str | None = UNSET,
    rationale: str | None = UNSET,
    source: str | None = UNSET,
    allocated_to: str | None = UNSET,
    baselines: list[str] | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """MUTATE 更新既有需求（PUT 部分更新：未提供字段不发送，显式 null 清空字段；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = RequirementUpdate.model_validate(
        provided(name=name, description=description, type=type, priority=priority,
                 status=status, parent=parent, attributes=attributes, parameters=parameters,
                 constraints=constraints, relations=relations, verification_cases=verification_cases,
                 cascade_from=cascade_from, rationale=rationale, source=source,
                 allocated_to=allocated_to, baselines=baselines)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="update_requirement", level="MUTATE", project_id=project_id, method="PUT",
        path=project_path(project_id, f"/requirements/{req_id}"), body=body,
        dry_run=dry_run, reason=reason, params=params,
        checks=lambda: entity_checks(project_id, "requirements", req_id),
    )


def set_relations(
    project_id: str,
    links: list[dict[str, str]] | list[Relation],
    reason: str,
    dry_run: bool = False,
) -> Any:
    """MUTATE 整体重写项目追踪矩阵（读-改-写回放：调用方先 get_traces 再追加链接写回；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = TraceMatrix.model_validate({"links": links}).model_dump(exclude_unset=True)
    return write_request(
        tool="set_relations", level="MUTATE", project_id=project_id, method="PUT",
        path=project_path(project_id, "/traces"), body=body, dry_run=dry_run,
        reason=reason, params=params, checks=lambda: relation_checks(project_id, links),
    )


def set_allocation(
    project_id: str,
    req_id: str,
    reason: str,
    row_id: str | None = UNSET,
    row_kind: str | None = UNSET,
    target_id: str | None = UNSET,
    component_id: str | None = UNSET,
    axis: str | None = UNSET,
    allocated: bool | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """MUTATE 设置需求分配（单条 allocation 变更；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = AllocationRequest.model_validate(
        provided(req_id=req_id, row_id=row_id, row_kind=row_kind, target_id=target_id,
                 component_id=component_id, axis=axis, allocated=allocated)
    ).model_dump(exclude_unset=True)

    def _checks() -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for field, collection, value in (
            ("req_id", "requirements", req_id),
            ("row_id", "requirements", row_id),
            ("target_id", "requirements", target_id),
            ("component_id", "components", component_id),
        ):
            if value is not UNSET and value and id_exists(project_id, collection, value) is False:
                checks.append({"kind": "missing_reference", "field": field, "id": value,
                               "hint": f"引用 id 不存在: {field}={value}"})
        return checks

    return write_request(
        tool="set_allocation", level="MUTATE", project_id=project_id, method="POST",
        path=project_path(project_id, "/allocation"), body=body, dry_run=dry_run,
        reason=reason, params=params, checks=_checks,
    )


def update_component(
    project_id: str,
    component_id: str,
    reason: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    type: ComponentType | None = UNSET,
    parent: str | None = UNSET,
    part_number: str | None = UNSET,
    supplier: str | None = UNSET,
    quantity: int | None = UNSET,
    satisfies: list[str] | None = UNSET,
    verification_cases: list[str] | None = UNSET,
    relations: list[Relation] | None = UNSET,
    attributes: list[AttributeValue] | None = UNSET,
    parameters: list[Parameter] | None = UNSET,
    baselines: list[str] | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """MUTATE 更新既有组件（PUT 部分更新：未提供字段不发送，显式 null 清空字段；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = ComponentUpdate.model_validate(
        provided(name=name, description=description, type=type, parent=parent,
                 part_number=part_number, supplier=supplier, quantity=quantity,
                 satisfies=satisfies, verification_cases=verification_cases,
                 relations=relations, attributes=attributes, parameters=parameters,
                 baselines=baselines)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="update_component", level="MUTATE", project_id=project_id, method="PUT",
        path=project_path(project_id, f"/components/{component_id}"), body=body,
        dry_run=dry_run, reason=reason, params=params,
        checks=lambda: entity_checks(project_id, "components", component_id),
    )


def update_verification_case(
    project_id: str,
    vc_id: str,
    reason: str,
    name: str | None = UNSET,
    description: str | None = UNSET,
    method: str | None = UNSET,
    status: str | None = UNSET,
    result: str | None = UNSET,
    verified_requirements: list[str] | None = UNSET,
    test_procedure: str | None = UNSET,
    steps: list[TestStep] | None = UNSET,
    case_type: CaseType | None = UNSET,
    environment: str | None = UNSET,
    decision_gate: str | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """MUTATE 更新既有验证用例（PUT 部分更新：未提供字段不发送，显式 null 清空字段；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = VerificationCaseUpdate.model_validate(
        provided(name=name, description=description, method=method, status=status,
                 result=result, verified_requirements=verified_requirements,
                 test_procedure=test_procedure, steps=steps, case_type=case_type,
                 environment=environment, decision_gate=decision_gate)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="update_verification_case", level="MUTATE", project_id=project_id, method="PUT",
        path=project_path(project_id, f"/verification/{vc_id}"), body=body,
        dry_run=dry_run, reason=reason, params=params,
        checks=lambda: entity_checks(project_id, "verification", vc_id),
    )


def run_verification(
    project_id: str,
    vc_id: str,
    status: str,
    reason: str,
    notes: str | None = UNSET,
    step_results: dict[str, str] | None = UNSET,
    dry_run: bool = False,
) -> Any:
    """MUTATE 记录一次验证执行（status 追加进用例 execution_history；reason 记入审计日志，不进 reqmesh 数据）。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。"""
    params = {k: v for k, v in locals().items() if v is not UNSET}
    body = RunVerification.model_validate(
        provided(status=status, notes=notes, step_results=step_results)
    ).model_dump(exclude_unset=True)
    return write_request(
        tool="run_verification", level="MUTATE", project_id=project_id, method="POST",
        path=project_path(project_id, f"/verification/{vc_id}/run"), body=body,
        dry_run=dry_run, reason=reason, params=params,
        checks=lambda: entity_checks(project_id, "verification", vc_id),
    )
