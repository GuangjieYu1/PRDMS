"""写工具公共设施（P2）：UNSET 哨兵 + 审批门/审计/dry-run 编排 + 前置校验助手。

- `UNSET`：区分「未提供」与「显式 null」——PUT 部分更新（exclude_unset）语义的根基
  （FastMCP 的 arg model 会把缺省参数以默认值填充进函数调用，哨兵让工具层可还原
  「调用方是否提供」的事实；None 仍表示「显式清空」）；
- `write_request`：统一编排 审批门裁决 → 审计记录 → dry_run 预览（含本地 checks）
  / 真实写请求（写视图经 GateToken 取得）；全部失败路径类型化并记审计；
- checks：dry_run 的本地前置校验（不写库）；仅提示，不阻断、不吞异常影响真实写。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ...errors import (
    AdminDisabledError,
    ApprovalConfigError,
    ApprovalDeniedError,
    HarnessError,
    TransportError,
    UpstreamError,
)
from ...guardrails.audit import AuditLog, summarize_params
from ...guardrails.gate import ApprovalGate
from ..runtime import get_runtime
from ._common import project_path


class _Unset:
    """「未提供」哨兵（repr 简洁；明确位于写工具契约，避免与 None 混淆）。"""

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()

# 写方法 → 写视图回调（PATCH/DELETE 已由客户端实现，未来工具按此扩展）
_METHODS = {
    "POST": lambda client, path, body: client.post(path, json=body),
    "PUT": lambda client, path, body: client.put(path, json=body),
    "PATCH": lambda client, path, body: client.patch(path, json=body),
    "DELETE": lambda client, path, body: client.delete(path),
}


def provided(**kwargs: Any) -> dict[str, Any]:
    """只保留「已提供」的参数（显式 None 保留——清空语义；UNSET 丢弃）。"""
    return {k: v for k, v in kwargs.items() if v is not UNSET}


def as_list(value: Any) -> list[Any]:
    """UNSET/None → 空列表；标量 → 单元素列表；列表原样。checks 引用名单防哨兵泄漏。"""
    if value is UNSET or value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def write_request(
    *,
    tool: str,
    level: str,
    project_id: str,
    method: str,
    path: str,
    body: dict[str, Any],
    dry_run: bool,
    reason: str,
    params: dict[str, Any],
    checks: Callable[[], list[dict[str, Any]]] | None = None,
) -> Any:
    """统一写编排（每个写工具一行调用 → 一条审计记录；含 denied/dry_run/错误路径）。"""
    settings = get_runtime().settings
    start = time.perf_counter()
    gate = ApprovalGate(settings)
    audit = AuditLog(settings.resolved_audit_file())
    summary = summarize_params(params)
    upstream = {"method": method, "path": path}

    def _ms() -> int:
        return int((time.perf_counter() - start) * 1000)

    def _log(decision: str, approved_by: str | None, deny_reason: str | None,
             result: str, status: int | None = None, send_to: dict | None = upstream) -> None:
        audit.record(
            tool=tool, level=level, project_id=project_id, dry_run=dry_run,
            params_summary=summary, reason=reason, decision=decision,
            approved_by=approved_by, deny_reason=deny_reason, upstream=send_to,
            http_status=status, result=result, duration_ms=_ms(),
        )

    try:
        decision = gate.decide(tool, project_id, dry_run, level)
    except ApprovalConfigError as exc:
        _log("denied", None, str(exc), "blocked", send_to=None)
        raise
    if decision.status == "admin_disabled":
        _log("admin_disabled", None, decision.deny_reason, "blocked", send_to=None)
        raise AdminDisabledError(
            f"{tool} 属 ADMIN 层且未显式开启（REQMESH_ENABLE_ADMIN=1 后才安装该层工具）: {decision.deny_reason}"
        )
    if not decision.approved:
        _log("denied", None, decision.deny_reason, "blocked", send_to=None)
        raise ApprovalDeniedError(f"审批门拒绝 {tool}: {decision.deny_reason}\n{decision.fix_hint}")

    if dry_run:
        payload = {
            "dry_run": True,
            "would_send": upstream | {"body": body},
            "checks": _run_checks(checks) if checks else [],
        }
        _log("approved", decision.entry, None, "ok")
        return payload

    try:
        client = get_runtime().writer(decision.token)
        result = _METHODS[method.upper()](client, path, body)
        _log("approved", decision.entry, None, "ok", status=client.last_status)
        return result
    except UpstreamError as exc:
        _log("approved", decision.entry, None, "upstream_error", status=exc.status_code)
        raise
    except TransportError as exc:
        _log("approved", decision.entry, None, "transport_error")
        raise
    except HarnessError as exc:
        # 登录/会话失效等认证侧失败（ensure_ready 期间）——环境侧失败路径同样记审计
        # （结果枚举无认证类目，按「未抵达上游/环境失败」归入 transport_error）
        _log("approved", decision.entry, None, "transport_error", deny_reason=f"认证/会话失败: {exc}")
        raise


def _run_checks(checks: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """dry_run 前置校验：仅提示，**绝不阻断预览**（异常降级为一条 check 提示）。"""
    try:
        return checks()
    except Exception as exc:  # noqa: BLE001 - 校验是信息性动作，任何异常都不应中断 dry_run
        return [{"kind": "check_error", "hint": f"本地校验失败（仅提示，不影响预览）: {exc}"}]


# ------------------------------------------------------------------ dry-run 前置校验（本地，不写库）
def id_exists(project_id: str, collection: str, entity_id: str) -> bool | None:
    """`GET /{collection}/{id}` 单条：200→存在；404→不存在；其他/不可达→None（无法确认）。"""
    try:
        get_runtime().reader().get(project_path(project_id, f"/{collection}/{entity_id}"))
        return True
    except UpstreamError as exc:
        if exc.status_code == 404:
            return False
        return None
    except HarnessError:
        return None


def create_checks(
    project_id: str,
    collection: str,
    entity_id: str,
    refs: list[tuple[str, str, list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """create 类通用检查：目标 id 冲突 + 引用 id 不存在（每条独立提示）。"""
    checks: list[dict[str, Any]] = []
    exists = id_exists(project_id, collection, entity_id)
    if exists is True:
        checks.append(
            {
                "kind": "id_conflict",
                "collection": collection,
                "id": entity_id,
                "hint": f"id 已存在（{collection}/{entity_id}），创建将被上游拒绝（fail-fast 提示）",
            }
        )
    for field, ref_collection, ids in refs or []:
        for ref_id in ids:
            if id_exists(project_id, ref_collection, ref_id) is False:
                checks.append(
                    {
                        "kind": "missing_reference",
                        "field": field,
                        "id": ref_id,
                        "hint": f"引用 id 不存在: {field}={ref_id}",
                    }
                )
    return checks


def entity_checks(project_id: str, collection: str, entity_id: str) -> list[dict[str, Any]]:
    """MUTATE/评审类通用检查：目标实体不存在 → 提示（影响面：请求会 404）。"""
    if id_exists(project_id, collection, entity_id) is False:
        return [
            {
                "kind": "missing_target",
                "collection": collection,
                "id": entity_id,
                "hint": f"目标实体不存在: {collection}/{entity_id}，请求将 404",
            }
        ]
    return []


def relation_checks(project_id: str, links: list[Any]) -> list[dict[str, Any]]:
    """追踪链接检查：source 必须存在（requirements）；target 在 requirements/components 任一存在。"""
    checks: list[dict[str, Any]] = []
    for link in links or []:
        source = getattr(link, "source", None) or (link.get("source") if isinstance(link, dict) else None)
        target = getattr(link, "target", None) or (link.get("target") if isinstance(link, dict) else None)
        if source and id_exists(project_id, "requirements", source) is False:
            checks.append(
                {
                    "kind": "missing_reference",
                    "field": "links.source",
                    "id": source,
                    "hint": f"追踪链接 source 不存在: {source}",
                }
            )
        if target:
            if id_exists(project_id, "requirements", target) is False and id_exists(
                project_id, "components", target
            ) is False:
                checks.append(
                    {
                        "kind": "missing_reference",
                        "field": "links.target",
                        "id": target,
                        "hint": f"追踪链接 target 不存在（requirements/components 均未命中）: {target}",
                    }
                )
    return checks
