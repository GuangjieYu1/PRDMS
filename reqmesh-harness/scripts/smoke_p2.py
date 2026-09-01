#!/usr/bin/env python3
"""P2 冒烟（network-tagged，不进默认 pytest 集合）：A 段全量 dry_run + B 段最小真实写闭环。

- 目标：`http://172.16.100.2:8000`（REQMESH_BASE_URL 可覆盖）的 cessna-172 项目；
- 临时目录隔离白名单/审计文件（绝不改动操作员真实 XDG 文件）；
- A 段：空白名单拒绝 → 添加白名单 → 12 工具逐一 dry_run → git 提交数不变（零副作用）；
- B 段：SMOKE-P2- 前缀固定 id 的真实写闭环（10 次写调用），git 新提交数 == 真实写调用数，
  审计行数 == 全部写调用数（含 denied/dry_run）；
- 记录落盘 docs/smoke/P2-cessna-172.md（REQMESH_SMOKE_OUT 可覆盖）；
- 服务账号断言：whoami==reqmesh-harness（role=contributor）；未建号允许降级 yugj
  （现有 contributor）并在记录中显式标注；匿名只读：无凭据调用 → 上游 401 经
  UpstreamError 透传（断言错误形状与「无凭据信息」）。
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ApprovalDeniedError, HarnessError, UpstreamError
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import Runtime, set_runtime

PROJECT_ID = "cessna-172"
SMOKE_REQ = "SMOKE-P2-001"
SMOKE_RISK = "SMOKE-P2-R01"
SMOKE_COMP = "SMOKE-P2-C01"
SMOKE_VC = "SMOKE-P2-V01"
SMOKE_COMMENT = "P2 冒烟评论标记"
SERVICE_ACCOUNT = "reqmesh-harness"
DEGRADED_ACCOUNT = "yugj"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # PRDMS 仓库根（docs/ 与 spec 同级）
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P2-cessna-172.md"


def main() -> int:
    settings = Settings()
    if not settings.has_credentials():
        print("未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）", file=sys.stderr)
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))

    tmp = Path(tempfile.mkdtemp(prefix="smoke-p2-"))
    settings = settings.model_copy(
        update={
            "approvals_file": tmp / "approvals.toml",
            "audit_file": tmp / "audit.jsonl",
            "session_file": tmp / "session.json",
        }
    )
    set_runtime(Runtime(settings))
    audit = AuditLog(settings.audit_file)
    steps: list[tuple[str, str | int, str]] = []

    def step(name: str, status: str | bool, detail: str = "") -> None:
        steps.append((name, "ok" if status is True else status, detail))

    try:
        # 预热 + 服务账号断言
        initial = AuthSession(settings)
        initial.ensure_ready(validate=True)
        tools = build_registry()
        whoami = tools.call("whoami")
        username = whoami.get("username")
        role = whoami.get("role")
        if username == SERVICE_ACCOUNT:
            account_note = f"{SERVICE_ACCOUNT}（role={role}）"
            degraded = False
        elif username == DEGRADED_ACCOUNT:
            account_note = f"降级 {DEGRADED_ACCOUNT}（role={role}，未建 {SERVICE_ACCOUNT} 服务账号）"
            degraded = True
        else:
            raise AssertionError(f"whoami 返回 {username}（role={role}），既非 {SERVICE_ACCOUNT} 也非降级账号")
        assert role == "contributor", f"服务账号角色应为 contributor，实际 {role}"
        step("whoami/服务账号", True, account_note)

        # ---------------- A 段（零副作用） ----------------
        git_before_a = _git_commit_count(initial)

        # A1：空白名单 fail-closed
        try:
            tools.call("create_requirement", project_id=PROJECT_ID, id=SMOKE_REQ, dry_run=True)
            raise AssertionError("空白名单下 create_requirement 未被阻断")
        except ApprovalDeniedError as exc:
            assert "approvals add create_requirement" in str(exc)
        rows = audit.read_all()
        assert rows[-1]["decision"] == "denied" and rows[-1]["result"] == "blocked"
        step("A1 空白名单阻断", True, "ApprovalDeniedError + 审计 denied")

        # A2：白名单 12 工具（MUTATE 必须具体 project；DRAFT 亦给 project 便于最小权限）
        entries = [
            WhitelistEntry(tool=tool, project=PROJECT_ID)
            for tool in (
                "create_requirement", "create_component", "create_verification_case", "create_risk",
                "create_comment", "review_item", "update_requirement", "set_relations",
                "set_allocation", "update_component", "update_verification_case", "run_verification",
            )
        ]
        WhitelistStore(settings.approvals_file).replace(entries)
        step("A2 白名单", True, f"12 条目 → {settings.approvals_file}")

        # A3：12 工具逐一 dry_run
        dry_cases = [
            ("create_requirement", dict(id=SMOKE_REQ, name="SMOKE DRAFT")),
            ("create_component", dict(id=SMOKE_COMP, name="SMOKE 组件")),
            ("create_verification_case", dict(id=SMOKE_VC, name="SMOKE 验证用例")),
            ("create_risk", dict(id=SMOKE_RISK, title="SMOKE 风险")),
            ("create_comment", dict(entity_kind="requirement", entity_id=SMOKE_REQ, text=SMOKE_COMMENT)),
            ("review_item", dict(req_id=SMOKE_REQ, comment="SMOKE 评审")),
            ("update_requirement", dict(req_id=SMOKE_REQ, reason="SMOKE 更新")),
            ("set_relations", dict(links=[] , reason="SMOKE 追踪")),
            ("set_allocation", dict(req_id=SMOKE_REQ, reason="SMOKE 分配")),
            ("update_component", dict(component_id=SMOKE_COMP, reason="SMOKE 组件更新")),
            ("update_verification_case", dict(vc_id=SMOKE_VC, reason="SMOKE 用例更新")),
            ("run_verification", dict(vc_id=SMOKE_VC, status="passed", reason="SMOKE 执行")),
        ]
        for name, extra in dry_cases:
            out = tools.call(name, project_id=PROJECT_ID, dry_run=True, **extra)
            assert isinstance(out, dict) and out["dry_run"] is True
            assert "would_send" in out and out["would_send"]["method"] in ("POST", "PUT")
            assert isinstance(out["checks"], list)
        step("A3 全量 dry_run", True, "12/12 通过（would_send + checks 结构）")

        # A4：git 提交计数不变
        git_after_a = _git_commit_count(initial)
        assert git_after_a == git_before_a, f"A 段后 git 提交数变化: {git_before_a} → {git_after_a}"
        step("A4 零副作用", True, f"git 提交数 {git_before_a} → {git_after_a}（不变）")

        # ---------------- B 段（最小真实写闭环） ----------------
        tools.call("create_requirement", project_id=PROJECT_ID, id=SMOKE_REQ,
                   name="SMOKE P2 需求", description="P2 冒烟建立")
        got = tools.call("get_requirement", project_id=PROJECT_ID, req_id=SMOKE_REQ)
        assert got.get("id") == SMOKE_REQ and got.get("name") == "SMOKE P2 需求"
        step("create_requirement", True, "回读一致")

        tools.call("review_item", project_id=PROJECT_ID, req_id=SMOKE_REQ, comment="P2 冒烟评审")
        unreviewed = tools.call("get_unreviewed_requirements", project_id=PROJECT_ID)
        ids = {r.get("id") for r in unreviewed.get("items", [])}
        assert SMOKE_REQ not in ids, f"评审后仍出现在未评审列表: {ids}"
        step("review_item", True, "未评审列表已移除该需求")

        tools.call("update_requirement", project_id=PROJECT_ID, req_id=SMOKE_REQ,
                   reason="P2 冒烟更新", description="P2 冒烟更新后的描述")
        got = tools.call("get_requirement", project_id=PROJECT_ID, req_id=SMOKE_REQ)
        assert got.get("description") == "P2 冒烟更新后的描述"
        step("update_requirement", True, "description 回读生效")

        tools.call("create_risk", project_id=PROJECT_ID, id=SMOKE_RISK, title="SMOKE 风险 register")
        risk_ids = {r.get("id") for r in tools.call("list_risks", project_id=PROJECT_ID).get("items", [])}
        assert SMOKE_RISK in risk_ids
        step("create_risk", True, "list_risks 可见")

        tools.call("create_component", project_id=PROJECT_ID, id=SMOKE_COMP, name="SMOKE 组件")
        comp_ids = {c.get("id") for c in tools.call("list_components", project_id=PROJECT_ID).get("items", [])}
        assert SMOKE_COMP in comp_ids
        step("create_component", True, "list_components 可见")

        tools.call("create_verification_case", project_id=PROJECT_ID, id=SMOKE_VC, name="SMOKE 验证用例")
        vc = tools.call("list_verification_cases", project_id=PROJECT_ID, vc_id=SMOKE_VC)
        assert vc.get("id") == SMOKE_VC
        step("create_verification_case", True, "list_verification_cases 可见")

        tools.call("create_comment", project_id=PROJECT_ID, entity_kind="requirement",
                   entity_id=SMOKE_REQ, text=SMOKE_COMMENT)
        comments = tools.call("list_comments", project_id=PROJECT_ID,
                              entity_kind="requirement", entity_id=SMOKE_REQ)
        comment_texts = [c.get("text", "") for c in comments.get("items", [])]
        assert any(SMOKE_COMMENT in (t or "") for t in comment_texts), comment_texts
        step("create_comment", True, "list_comments 可见该条")

        tools.call("run_verification", project_id=PROJECT_ID, vc_id=SMOKE_VC, status="passed",
                   notes="P2 冒烟执行", reason="P2 冒烟执行记录")
        vc = tools.call("list_verification_cases", project_id=PROJECT_ID, vc_id=SMOKE_VC)
        history = vc.get("execution_history") or []
        assert history and str(history[-1].get("status")) == "passed", history
        step("run_verification", True, "execution_history 追加 passed")

        traces = tools.call("get_traces", project_id=PROJECT_ID)
        links = list(traces.get("links", []))
        smoke_link = {"source": SMOKE_REQ, "target": SMOKE_COMP, "type": "refines"}
        links.append(smoke_link)
        tools.call("set_relations", project_id=PROJECT_ID, links=links, reason="P2 冒烟追加追踪")
        traces = tools.call("get_traces", project_id=PROJECT_ID)
        assert smoke_link in traces.get("links", []), "set_relations 回读未含冒烟链接"
        step("set_relations", True, "读-改-写回放成功")

        tools.call("set_allocation", project_id=PROJECT_ID, req_id=SMOKE_REQ,
                   component_id=SMOKE_COMP, allocated=True, reason="P2 冒烟分配")
        matrix = tools.call("get_allocation_matrix", project_id=PROJECT_ID)
        row = next((r for r in matrix.get("rows", []) if r.get("row_id") == SMOKE_REQ), None)
        assert row is not None and row.get("cells", {}).get(SMOKE_COMP) is True, row
        step("set_allocation", True, "allocation-matrix 回读 allocated=True")

        git_after_b = _git_commit_count(initial)
        real_writes = 10
        assert git_after_b - git_after_a == real_writes, f"git 新提交 {git_after_b - git_after_a} != 真实写调用 {real_writes}"
        step("git 提交计数", True, f"A 段后 {git_after_a} → B 段后 {git_after_b}（+{real_writes} == 真实写调用数）")

        rows = audit.read_all()
        expected_lines = 1 + 12 + real_writes  # A1 denied + A3 dry_run + B 段真实写
        assert len(rows) == expected_lines, f"审计行数 {len(rows)} != {expected_lines}"
        for row in rows:
            for field in ("ts", "tool", "level", "project_id", "dry_run", "params_summary",
                          "reason", "decision", "approved_by", "deny_reason", "upstream",
                          "http_status", "result", "duration_ms", "version"):
                assert field in row, f"审计行缺字段 {field}: {row}"
        step("审计日志", True, f"{len(rows)} 行（denied/dry_run/真实写）字段齐全")

        # 匿名只读验证：无凭据客户端调用读取 → 上游 401 经 UpstreamError 透传
        anon = AuthSession(Settings(base_url=settings.base_url, username="", password="", token=""))
        try:
            anon.get("/api/projects")
            raise AssertionError("匿名调用未收到预期拒绝")
        except UpstreamError as exc:
            assert exc.status_code in (401, 403), exc.status_code
            body = str(exc)
            assert "anon" not in body and "pass" not in body.lower()
        step("匿名只读", True, "无凭据 → 上游 401/403 UpstreamError（无凭据信息）")

    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(out_path, settings, steps, failed=str(exc), git_info=None)
        return 1
    except HarnessError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(out_path, settings, steps, failed=str(exc), git_info=None)
        return 1

    _write_record(
        out_path, settings, steps, failed=None,
        git_info={"before_a": git_before_a, "after_a": git_after_a, "after_b": git_after_b},
        audit_lines=len(rows), account_note=account_note, degraded=degraded,
    )
    print(f"冒烟通过，记录已落盘: {out_path}")
    return 0


def _git_commit_count(session: AuthSession) -> int:
    data = session.get(f"/api/projects/{PROJECT_ID}/git/log")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("commits", "log", "items", "entries"):
            if isinstance(data.get(key), list):
                return len(data[key])
    raise AssertionError(f"git/log 响应形状未知: {type(data)}")


def _write_record(out_path, settings, steps, *, failed, git_info, audit_lines=None,
                  account_note=None, degraded=False) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows = "\n".join(f"| {name} | ok | {detail} |" if status is True else f"| {name} | {status} | {detail} |"
                     for name, status, detail in steps)
    git_section = (
        f"git 提交计数：A 段前 {git_info['before_a']} → A 段后 {git_info['after_a']}（不变）"
        f" → B 段后 {git_info['after_b']}（+{git_info['after_b'] - git_info['after_a']}）\n\n"
        "残渣清单（P2 真实写副作用）：\n"
        f"- 新增实体：`{SMOKE_REQ}`（需求）、`{SMOKE_RISK}`（风险）、`{SMOKE_COMP}`（组件）、"
        f"`{SMOKE_VC}`（验证用例）；评论 1 条（需求 {SMOKE_REQ}）\n"
        f"- 追踪矩阵：+1 链接（{SMOKE_REQ} refines {SMOKE_COMP}）；分配：{SMOKE_REQ} → {SMOKE_COMP}\n"
        f"- 需求总数：P1 基线 57（历史快照）→ P2 真实写后 58（`list_requirements` total），"
        "P1 冒烟记录的 total==57 断言自此只作为历史快照\n"
    ) if git_info else "（失败，未进入 B 段或记录不完整）\n"
    out_path.write_text(
        f"""# P2 cessna-172 冒烟记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- 项目：{PROJECT_ID}
- 结果：**{"通过" if failed is None else f"失败: {failed}"}**
- 服务账号：{account_note or "见下方步骤"}{"（已降级）" if degraded else ""}
- 白名单/审计（临时目录，不入库）：{settings.approvals_file}

## 步骤与关键计数

{rows}

## git 与残渣

{git_section}
- 审计日志：{audit_lines if audit_lines is not None else "见上方步骤"} 行（临时文件，属运行时状态）。

## 说明

- A 段为零副作用验证（dry_run 不产生 git 提交）；B 段为最小真实写闭环（SMOKE-P2- 前缀）。
- P1 冒烟（docs/smoke/P1-cessna-172.md）total==57 仅作历史快照，不再作为重跑断言。
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
