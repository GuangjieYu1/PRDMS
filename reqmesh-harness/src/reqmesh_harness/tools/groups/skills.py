"""P3 复合技能工具组（2 个）：自然语言建需求（EARS + quality lint 闭环）+ 需求级 quality 反馈。

- draft_requirement：单个 MCP 工具 = 完整 NL→EARS→本地 lint 迭代→落库闭环（DRAFT 层）；
  编排全部在工具处理器内部同步完成（P5 前无 agent 运行时，design D5）；
- get_requirement_quality：需求级 quality 反馈——GET /quality 一次后客户端按 id 过滤
  （服务端无独立需求级端点，spec 事实 1）；
- 落库复用 P2 写路径 _write_common.write_request（审批门/审计/dry-run 零修改，
  仅 import）；白名单条目按工具名 draft_requirement 独立裁决；
- 审计边界（spec ⑤）：到达 write_request 才记审计行（params_summary 附加
  lint_score/lint_rounds 标量）；InputParseError 与 lint 未过线不记审计。
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from ._common import project_path, read_json
from ._write_common import create_checks, write_request
from ..runtime import get_runtime
from ...client.generated.models import Priority, RequirementCreate, RequirementType
from ...ears import AUTO, derive_name, parse_nl
from ...errors import HarnessError, InputParseError, UpstreamError
from ...lint import (
    DEFAULT_CONFIG,
    RESIDUAL_WHITELIST,
    apply_fixes,
    check_passed,
    config_from_project,
    lint_text,
)

_Template = Literal["auto", "ubiquitous", "event", "unwanted", "state", "optional"]

_RATIONALE_PREFIX = "自然语言建需求（draft_requirement）："
_NL_MAX = 2000
_RATIONALE_MAX = 200


def draft_requirement(
    project_id: str,
    nl_text: str,
    template: _Template = AUTO,
    system: str | None = None,
    name: str | None = None,
    type: RequirementType | None = None,
    priority: Priority | None = None,
    parent: str | None = None,
    subject: str | None = None,
    id: str | None = None,
    require_measurable: bool = True,
    dry_run: bool = False,
) -> Any:
    """DRAFT 从自然语言（一句话或要点）生成符合 EARS 句式的需求并落库：模板渲染 → 本地 quality lint 迭代修正（≤REQMESH_LINT_MAX_ROUNDS 轮，确定性修正表 6 类）→ 过线（零 error + score ≥ REQMESH_LINT_MIN_SCORE（默认 90）+ 残余白名单）后经审批门 POST /requirements。dry_run=true 只返回 would_send 与本地校验，不写库、不产生 git 提交；未获审批门白名单批准将被拒绝。仅接受英文槽位（中文输入报 InputParseError——翻译是 P5 agent loop 的职责）；不编造内容（占位符/不可度量数字一律拒绝）。"""
    settings = get_runtime().settings
    parsed = parse_nl(nl_text, template=template, system=system)
    bullets = parsed.slots

    def _pick(param_value: Any, key: str) -> Any:
        """参数 > 要点行内覆盖 > None。"""
        return param_value if param_value is not None else bullets.get(key)

    # 字段映射（spec ②）
    req_type = _pick(type, "type")
    req_priority = _pick(priority, "priority")
    if req_type is not None:
        req_type = _validate_enum(RequirementType, req_type, "type")
    if req_priority is not None:
        req_priority = _validate_enum(Priority, req_priority, "priority")
    req_parent = _pick(parent, "parent")
    req_subject = _pick(subject, "subject")
    explicit_name = _pick(name, "name")

    sentence = parsed.sentence
    current_name = explicit_name or derive_name(parsed.response)

    # 项目 config（GET /quality 一次；失败回落默认并标注 config_source）
    config, config_source = _load_lint_config(project_id)

    # 确定性问题修循环（≤N 轮：修正 → 重派生 name → 重打分；收敛检测防空转）
    rounds = 0
    converged = False
    report = None
    passed = False
    reasons: list[str] = []
    while True:
        rounds += 1
        report = lint_text(f"{current_name}\n{sentence}", config)
        passed, reasons = check_passed(
            report, template=parsed.template,
            require_measurable=require_measurable, min_score=settings.lint_min_score,
        )
        if passed:
            break
        if any(f.severity == "error" for f in report.findings):
            break  # 占位符等：立即终止，不尝试修复（绝不编造内容）
        if rounds >= settings.lint_max_rounds:
            break
        fixed = _fix_sentence_only(f"{current_name}\n{sentence}", report)
        if fixed == sentence:
            converged = True
            break
        sentence = fixed
        if explicit_name is None:
            try:
                re_parsed = parse_nl(sentence, template=parsed.template, system=parsed.system)
                current_name = derive_name(re_parsed.response)
            except InputParseError:
                pass  # 修正后结构异常时保留原 name（防御性；修正表不改变 EARS 结构）

    allowed = set(RESIDUAL_WHITELIST.get(parsed.template, frozenset()))
    if not require_measurable:
        allowed.add("untestable")
    lint_out: dict[str, Any] = {
        "score": report.score,
        "passed": passed,
        "rounds": rounds,
        "findings": [asdict(f) for f in report.findings],
        "residual_findings": [
            asdict(f) for f in report.findings
            if f.severity in ("warning", "info") and f.rule in allowed
        ],
        "min_score": settings.lint_min_score,
        "config_source": config_source,
        "config": report.config,
    }
    ears_out = {"template": parsed.template, "sentence": sentence, "system": parsed.system}

    # 逐级解析 id：参数 → 要点 → next-uid（spec ②；工具内部直连，不新增公开工具）
    req_id = _pick(id, "id")
    auto_id = req_id is None
    id_error: HarnessError | None = None
    if req_id is None:
        try:
            req_id = _next_uid(project_id)
        except HarnessError as exc:
            id_error = exc  # lint 未过线时 id 预览失败不阻断报告（仅写路径需要真切 id）

    rationale = _RATIONALE_PREFIX + nl_text[:_RATIONALE_MAX]

    def _build_body(req_id_value: str) -> dict[str, Any]:
        body_fields: dict[str, Any] = {
            "id": req_id_value,
            "name": current_name,
            "description": sentence,
            "type": req_type or "functional",
            "priority": req_priority or "medium",
            "status": "proposed",  # 新需求不做评审（spec ②）
            "rationale": rationale,
            "source": "",
        }
        if req_parent is not None:
            body_fields["parent"] = req_parent
        if req_subject is not None:
            body_fields["subject"] = req_subject
        return RequirementCreate.model_validate(body_fields).model_dump(exclude_unset=True)

    def _would_send(req_id_value: str) -> dict[str, Any]:
        return {"method": "POST", "path": project_path(project_id, "/requirements"),
                "body": _build_body(req_id_value)}

    if not passed:
        hint = _build_hint(reasons, converged, rounds, settings.lint_max_rounds,
                           require_measurable, report)
        if id_error is not None or req_id is None:
            hint += f"（id 预览不可用：next-uid 获取失败——{id_error}；过线后可重试。）"
            return {
                "persisted": False,
                "ears": ears_out,
                "lint": lint_out,
                "would_send": None,
                "hint": hint,
            }
        return {
            "persisted": False,
            "ears": ears_out,
            "lint": lint_out,
            "would_send": _would_send(req_id),
            "hint": hint,
        }

    if id_error is not None or req_id is None:
        raise id_error or HarnessError("next-uid 获取失败（写路径需要真实 id）")
    body = _build_body(req_id)
    would_send = _would_send(req_id)

    audit_params: dict[str, Any] = {
        "project_id": project_id,
        "nl_text": nl_text,
        "template": template,
        "require_measurable": require_measurable,
        "lint_score": report.score,
        "lint_rounds": rounds,
    }
    for key, value in (("system", system), ("name", name), ("type", req_type),
                       ("priority", req_priority), ("parent", req_parent),
                       ("subject", req_subject), ("id", req_id), ("dry_run", dry_run)):
        if value is not None:
            audit_params[key] = value

    def _checks() -> list[dict[str, Any]]:
        return create_checks(
            project_id, "requirements", req_id,
            refs=[("parent", "requirements", [req_parent])] if req_parent else None,
        )

    def _invoke() -> Any:
        return write_request(
            tool="draft_requirement", level="DRAFT", project_id=project_id,
            method="POST", path=project_path(project_id, "/requirements"),
            body=body, dry_run=dry_run, reason="", params=audit_params, checks=_checks,
        )

    try:
        result = _invoke()
    except UpstreamError as exc:
        # 自动 id 的并发冲突（409）：重取一次后重试一次；再冲突透传报错
        if auto_id and exc.status_code == 409:
            req_id = _next_uid(project_id)
            audit_params["id"] = req_id
            body["id"] = req_id
            result = _invoke()
        else:
            raise

    if dry_run:
        return {
            "persisted": False,
            "dry_run": True,
            "ears": ears_out,
            "lint": lint_out,
            "would_send": result["would_send"],
            "checks": result["checks"],
        }

    return {
        "persisted": True,
        "requirement": result,
        "ears": ears_out,
        "lint": lint_out,
    }


def get_requirement_quality(project_id: str, req_id: str) -> Any:
    """READ-ONLY 返回单个需求的品质反馈：score/findings + 项目 average/total 上下文。服务端无需求级端点（一次 GET /api/projects/{project_id}/quality 后按 id 过滤；rate limit 20 次/60 秒——description 注明）；目标需求无记录时相关字段为 null。"""
    report = read_json(project_path(project_id, "/quality"))
    if not isinstance(report, dict):
        raise UpstreamError(502, f"/quality 响应形状未知: {type(report).__name__}")
    average = report.get("average")
    total = report.get("total")
    items = report.get("per_requirement") or []
    target = next((r for r in items if isinstance(r, dict) and r.get("id") == req_id), None)
    if target is None:
        return {
            "id": req_id,
            "name": None,
            "score": None,
            "findings": None,
            "average": average,
            "total": total,
        }
    return {
        "id": target.get("id"),
        "name": target.get("name"),
        "score": target.get("score"),
        "findings": target.get("findings"),
        "average": average,
        "total": total,
    }


# ------------------------------------------------------------------ 内部
def _validate_enum(model: type, value: Any, field: str) -> Any:
    """要点行内覆盖的枚举校验（非法值 → InputParseError）。

    返回 RootModel 的根值（字符串）——审计/请求体均以纯字符串呈现。
    """
    try:
        validated = model.model_validate(value)
    except Exception as exc:  # pydantic ValidationError（枚举词表）
        raise InputParseError(
            f"要点 {field!r} 取值非法: {value!r} —— 支持值见工具参数枚举。"
        ) from exc
    return validated.root if hasattr(validated, "root") else validated


def _load_lint_config(project_id: str):
    """项目 config：GET /quality 一次（失败回落默认 config 并标注 config_source）。"""
    try:
        report = read_json(project_path(project_id, "/quality"))
        config = config_from_project(report.get("config") if isinstance(report, dict) else None)
        return config, "project"
    except HarnessError:
        return DEFAULT_CONFIG, "default"


def _fix_sentence_only(text: str, report) -> str:
    """确定性修正仅作用于描述部分（lint 文本 = name\nsentence；name 区域不动）。"""
    parts = text.split("\n", 1)
    if len(parts) == 1:
        return apply_fixes(parts[0])
    return apply_fixes(parts[1])


def _next_uid(project_id: str) -> str:
    """内部取 id：GET /requirements/next-uid（P1/P2 延后端点，P3 内部启用）。"""
    data = read_json(project_path(project_id, "/requirements/next-uid"))
    next_id = data.get("next_id") if isinstance(data, dict) else None
    if not isinstance(next_id, str) or not next_id:
        raise HarnessError(f"next-uid 响应缺少 next_id 字段: {data!r}")
    return next_id


def _build_hint(reasons: list[str], converged: bool, rounds: int, max_rounds: int,
                require_measurable: bool, report) -> str:
    """未过线 hint：按失败类别给出精确建议（spec ④ 终止语义）。"""
    parts: list[str] = [f"lint 未过线（rounds={rounds}/{max_rounds}）: " + "; ".join(reasons)]
    rules = {f.rule for f in report.findings}
    if "placeholder" in rules:
        parts.append("占位符（placeholder，error 级）不可自动修复——工具绝不编造内容，请补充内容后重试。")
    if "untestable" in rules and require_measurable:
        parts.append("需求未含可度量数字+单位（untestable）：请补充如 '1185 km'、'2.5 m/s'、'1 s' 的量化标准，"
                     "或对无需量化的条目显式传 require_measurable=false。")
    if converged:
        parts.append("确定性修正已收敛（6 类修正表不再改动文本）：剩余 finding 需要语义性改写（P5 agent loop 职责），"
                     "本工具不代做质量决策——可用 create_requirement 自行落库。")
    else:
        parts.append("可调整输入措辞后重试；或按上方原因修正后经 create_requirement 自行落库。")
    return " ".join(parts)


__all__ = ["draft_requirement", "get_requirement_quality"]
