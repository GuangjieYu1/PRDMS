#!/usr/bin/env python3
"""P3 冒烟（network-tagged，不进默认 pytest 集合）：金样例 A 段零副作用 + B 段真实写闭环。

- 目标：http://172.16.100.2:8000（REQMESH_BASE_URL 可覆盖）的 cessna-172 项目；
- 临时目录隔离白名单/审计/会话文件（绝不改动操作员真实 XDG 文件）；
- A 段：空白名单拒绝（fail-closed）→ 添加白名单 → G1–G5 全量 dry_run（零副作用：
  total 不变 58、无真实写调用、git 条件断言、审计逐调用一行）；
- B 段：G1/G2/G5 真实写闭环（SMOKE-P3-001..003 固定 id）——回读文本相等、
  status==proposed、rationale 溯源、unreviewed 可见、服务端分 == 本地分（100）、
  total==61；不调用 review_item（新需求保持未评审是设计语义，spec ⑥）；
- 记录落盘 docs/smoke/P3-cessna-172.md（REQMESH_SMOKE_OUT 可覆盖）；
- 服务账号断言沿用 P2：reqmesh-harness（maintainer），未建号允许降级 yugj 并注明。
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ApprovalDeniedError, HarnessError
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import Runtime, set_runtime

PROJECT_ID = "cessna-172"
SERVICE_ACCOUNT = "reqmesh-harness"
DEGRADED_ACCOUNT = "yugj"

# spec ⑥ 金样例：(NL 输入, 期望句式, 期望 EARS 输出, B 段固定 id 或 None, type[spec ⑥ 列])
GOLDEN = [
    (
        "The aircraft shall achieve a range of at least 1185 km at maximum cruise power.",
        "ubiquitous",
        "The aircraft shall achieve a range of at least 1185 km at maximum cruise power.",
        "SMOKE-P3-001",
        "non_functional_performance",
    ),
    (
        "When the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning.",
        "event",
        "WHEN the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning.",
        "SMOKE-P3-002",
        "functional",
    ),
    (
        "While in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level.",
        "state",
        "WHILE in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level.",
        None,
        "functional",
    ),
    (
        "Where the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m.",
        "optional",
        "WHERE the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m.",
        None,
        "functional",
    ),
    (
        "If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s.",
        "unwanted",
        "IF the cabin door is unlatched, THEN the aircraft shall display a door warning within 1 s.",
        "SMOKE-P3-003",
        "safety",
    ),
]

DERIVED_IDS = ("SMOKE-P3-001", "SMOKE-P3-002", "SMOKE-P3-003")

# spec ② 字段映射：name 派生（response 子句首字母大写、截 80 字符）——逐金样例断言
EXPECTED_NAMES = (
    "Achieve a range of at least 1185 km at maximum cruise power",
    "Display the overspeed warning",
    "Maintain a climb rate of at least 2.5 m/s at sea level",
    "Hold the selected altitude within 15 m",
    "Display a door warning within 1 s",
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # PRDMS 仓库根（docs/ 与 spec 同级）
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P3-cessna-172.md"

EXPECTED_TOTAL_BEFORE = 58  # P2 真实写后基线（B 段 +3 → 61）
EXPECTED_TOTAL_AFTER = 61


def main() -> int:
    settings = Settings()
    if not settings.has_credentials():
        print("未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）", file=sys.stderr)
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))

    tmp = Path(tempfile.mkdtemp(prefix="smoke-p3-"))
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
    account_note = "—"
    degraded = False

    def step(name: str, status: str | bool, detail: str = "") -> None:
        steps.append((name, "ok" if status is True else status, detail))

    try:
        # 预热 + 服务账号断言（新会话登录，绝不沿用本机残留 yugj 会话）
        initial = AuthSession(settings)
        initial.ensure_ready(validate=True)
        tools = build_registry()
        whoami = tools.call("whoami")
        username = whoami.get("username")
        role = whoami.get("role")
        assert role in ("maintainer", "contributor"), "服务账号角色应为 maintainer（或 contributor 降级），实际 " + str(role)
        degraded = username == DEGRADED_ACCOUNT
        account_note = f"{username}（role={role}）"
        step("whoami/服务账号", True, account_note)

        # ---------------- A 段（零副作用） ----------------
        git_repo, git_before_a = _git_commit_count(initial)
        total_before = _requirements_total(tools)

        # A1：空白名单 fail-closed（金样例 G1 dry_run）
        try:
            tools.call("draft_requirement", project_id=PROJECT_ID, nl_text=GOLDEN[0][0],
                       id="SMOKE-P3-D001", dry_run=True)
            raise AssertionError("空白名单下 draft_requirement 未被阻断")
        except ApprovalDeniedError as exc:
            assert "approvals add draft_requirement" in str(exc)
        rows = audit.read_all()
        assert rows[-1]["decision"] == "denied" and rows[-1]["result"] == "blocked"
        assert rows[-1]["tool"] == "draft_requirement"
        step("A1 空白名单阻断", True, "ApprovalDeniedError（fix_hint 含 approvals add） + 审计 denied 行")

        # A2：白名单（DRAFT 层：project 可省略——按最小权限给出具体 project）
        WhitelistStore(settings.approvals_file).append(
            WhitelistEntry(tool="draft_requirement", project=PROJECT_ID)
        )
        step("A2 白名单", True, f"draft_requirement+{PROJECT_ID} → {settings.approvals_file}")

        # A3：G1–G5 全量 dry_run（type 按 spec ⑥ 金样例列）
        for i, (nl, template, sentence, _b_id, req_type) in enumerate(GOLDEN, start=1):
            out = tools.call(
                "draft_requirement", project_id=PROJECT_ID, nl_text=nl,
                id=f"SMOKE-P3-D00{i}", type=req_type, dry_run=True,
            )
            assert out["ears"]["template"] == template
            assert out["ears"]["sentence"] == sentence, out["ears"]["sentence"]
            assert out["lint"]["passed"] is True
            assert out["lint"]["score"] == 100, out["lint"]
            assert out["lint"]["findings"] == [], out["lint"]["findings"]
            assert out["lint"]["rounds"] == 1
            assert out["lint"]["config_source"] == "project"
            body = out["would_send"]["body"]
            assert body["description"] == sentence
            assert body["name"] == EXPECTED_NAMES[i - 1], body["name"]
            assert body["type"] == req_type, body["type"]
            assert body["status"] == "proposed"
            assert body["rationale"].startswith("自然语言建需求（draft_requirement）：" + nl[:200])
            assert body["source"] == ""
            assert isinstance(out["checks"], list)
        step("A3 金样例全量 dry_run", True, "G1–G5 五句式（ears 逐字符一致 + lint score=100 + rounds=1）")

        # A4：零副作用（total 不变 + git 条件断言 + 无真实写行）
        total_after_a = _requirements_total(tools)
        assert total_after_a == total_before == EXPECTED_TOTAL_BEFORE, (total_before, total_after_a)
        git_repo, git_after_a = _git_commit_count(initial)
        assert git_after_a == git_before_a, f"A 段后 git 提交数变化: {git_before_a} → {git_after_a}"
        git_note = f"git 提交数 {git_before_a} → {git_after_a}（不变；is_repo={git_repo}）"
        if not git_repo:
            git_note += " ——项目未初始化 git 仓库，B 段提交计数断言降级（见说明）"
        rows = audit.read_all()
        assert len(rows) == 6, len(rows)  # A1 denied + A3 5 次 dry_run
        assert all(r["tool"] == "draft_requirement" for r in rows)
        step("A4 零副作用", True, f"total {total_before} → {total_after_a}（不变）· " + git_note)

        # ---------------- B 段（真实写闭环） ----------------
        req_ids = {r.get("id") for r in tools.call("list_requirements", project_id=PROJECT_ID).get("items", [])}
        leftover = [i for i in DERIVED_IDS if i in req_ids]
        if leftover:
            raise AssertionError(
                "发现上次冒烟残留 SMOKE-P3- 需求（请先清理再重跑，删除族属 ADMIN 层）: " + str(leftover)
            )

        for b_id in DERIVED_IDS:
            nl, template, sentence, _x, req_type = next(g for g in GOLDEN if g[3] == b_id)
            result = tools.call(
                "draft_requirement", project_id=PROJECT_ID, nl_text=nl, id=b_id, type=req_type,
            )
            assert result["persisted"] is True, result
            # ① 201 实体：description 与 EARS 句子文本相等（sanitize 后纯文本原样回读）
            got = result["requirement"]
            assert got["description"] == sentence, got["description"]
            # name 派生与映射模板一致（spec ②）
            expected_name = EXPECTED_NAMES[[g[3] for g in GOLDEN].index(b_id)]
            assert got["name"] == expected_name, got["name"]
            # ② get_requirement 回读一致；status==proposed；rationale 含 NL 原文溯源
            req = tools.call("get_requirement", project_id=PROJECT_ID, req_id=b_id)
            assert req["description"] == sentence
            assert req["status"] == "proposed"
            assert nl[:200] in (req.get("rationale") or "")
            # ③ 未评审列表可见（B 段不调用 review_item——保持未评审是设计语义）
            unreviewed = {r.get("id") for r in tools.call(
                "get_unreviewed_requirements", project_id=PROJECT_ID).get("items", [])}
            assert b_id in unreviewed, f"{b_id} 未出现在未评审列表: {unreviewed}"
            # ④ 服务端分 == 本地分（100）：get_requirement_quality 对账
            quality = tools.call("get_requirement_quality", project_id=PROJECT_ID, req_id=b_id)
            assert quality["score"] == 100, quality
            assert quality["findings"] == [], quality
            assert quality["id"] == b_id
            step(f"B 段 {b_id}", True, f"{template} 落库·回读相等·unreviewed 可见·服务端分=100")

        # ⑥ total == 61（P1 57 / P2 58 为历史快照）
        total_after_b = _requirements_total(tools)
        assert total_after_b == EXPECTED_TOTAL_AFTER, total_after_b
        step("需求总数", True, f"{total_before} → {total_after_b}（+3 == B 段真实写调用数）")

        # git 条件断言 + ⑤ 审计行数/字段
        git_repo, git_after_b = _git_commit_count(initial)
        if git_repo:
            assert git_after_b - git_after_a == 3, (git_after_a, git_after_b)
            step("git 提交计数", True, f"A 段后 {git_after_a} → B 段后 {git_after_b}（+3 == 真实写调用数）")
        else:
            step("git 提交计数", "降级", "项目未初始化 git 仓库（is_repo=false）：提交计数断言跳过（dry_run 不产生提交仍成立）")

        rows = audit.read_all()
        assert len(rows) == 9, len(rows)  # 1 denied + 5 dry_run + 3 真实写
        for row in rows:
            assert "lint_score" in row["params_summary"], row
            assert "lint_rounds" in row["params_summary"], row
        step("审计日志", True, f"{len(rows)} 行（denied/dry_run/真实写）字段齐全（含 lint_score/lint_rounds）")

    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(out_path, settings, steps, failed=str(exc), git_info=None,
                      account_note=account_note, degraded=degraded, totals=None)
        return 1
    except HarnessError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(out_path, settings, steps, failed=str(exc), git_info=None,
                      account_note=account_note, degraded=degraded, totals=None)
        return 1

    _write_record(
        out_path, settings, steps, failed=None,
        git_info={"before_a": git_before_a, "after_a": git_after_a, "after_b": git_after_b, "is_repo": git_repo},
        audit_lines=len(rows), account_note=account_note, degraded=degraded,
        totals={"before": total_before, "after_a": total_after_a, "after_b": total_after_b},
    )
    print(f"冒烟通过，记录已落盘: {out_path}")
    return 0


def _requirements_total(tools) -> int:
    data = tools.call("list_requirements", project_id=PROJECT_ID, limit=1)
    if not isinstance(data, dict):
        raise AssertionError(f"list_requirements 响应形状未知: {type(data).__name__}")
    total = data.get("total")
    assert isinstance(total, int), total
    return total


def _git_commit_count(session: AuthSession) -> tuple[bool, int]:
    """(is_repo, commit_count)：项目未初始化 git 仓库时 is_repo=False（计数不可用）。"""
    data = session.get(f"/api/projects/{PROJECT_ID}/git/log")
    if isinstance(data, dict):
        is_repo = bool(data.get("is_repo", False))
        for key in ("commits", "log", "items", "entries"):
            if isinstance(data.get(key), list):
                return is_repo, len(data[key])
        return is_repo, 0
    if isinstance(data, list):
        return True, len(data)
    raise AssertionError(f"git/log 响应形状未知: {type(data)}")


def _write_record(out_path, settings, steps, *, failed, git_info, audit_lines=None,
                  account_note="—", degraded=False, totals=None) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows = "\n".join(f"| {name} | ok | {detail} |" if status is True else f"| {name} | {status} | {detail} |"
                     for name, status, detail in steps)
    git_section = (
        f"git 提交计数：A 段前 {git_info['before_a']} → A 段后 {git_info['after_a']}（不变）"
        f" → B 段后 {git_info['after_b']}（+{git_info['after_b'] - git_info['after_a']}）\n\n"
        "残渣清单（P3 真实写副作用）：\n"
        "- 新增需求（SMOKE-P3-）：SMOKE-P3-001（G1 ubiquitous）、SMOKE-P3-002（G2 event）、"
        "SMOKE-P3-003（G5 unwanted）——保持未评审（B 段不调用 review_item 是设计语义）\n"
        f"- 需求总数：P2 基线 58（历史快照）→ P3 真实写后 {totals['after_b'] if totals else '—'}\n"
    ) if git_info else "（失败，未进入 B 段或记录不完整）\n"
    out_path.write_text(
        f"""# P3 cessna-172 冒烟记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- 项目：{PROJECT_ID}
- 结果：**{"通过" if failed is None else f"失败: {failed}"}**
- 服务账号：{account_note}{"（已降级）" if degraded else ""}
- 白名单/审计（临时目录，不入库）：{settings.approvals_file}

## 步骤与关键计数

{rows}

## git 与残渣

{git_section}
- 审计日志：{audit_lines if audit_lines is not None else "见上方步骤"} 行（临时文件，属运行时状态）。

## 说明

- A 段为零副作用验证：G1–G5 全量 dry_run（ears 逐字符一致 + lint score=100 + rounds=1），
  total 不变（{totals['before'] if totals else '—'}）、无真实写调用（审计仅 denied/dry_run 行）、
  git 提交数不变（条件断言）。
- B 段为最小真实写闭环（SMOKE-P3- 前缀）：文本级回读相等断言（sanitize 后纯文本原样回读）、
  status==proposed、rationale 含 NL 原文溯源、unreviewed 可见、服务端分 == 本地分（100 对账）。
- P1/P2 冒烟记录的 total==57/58 仅作历史快照，不再作为重跑断言。

## 实测偏差与开发会话注记（待需求会话确认）

1. **G5 默认 config == 98（与 G4 同）**：spec ⑥ 仅列举 G4「is engaged」触发 passive_voice；
   实测 G5「is unlatched」同为 be+过去分词（-ed 词尾），按 spec 规则表语义在**默认 config**下
   同为 98 分（cessna-172 config 已关 passive_voice → 两者均 100，冒烟不受影响）。单元测试
   tests/test_lint.py 已按此行为断言并注明；若需求会话认为 G5 应豁免，需放宽规则表说明。
2. **打分取整**：本地分按 round() 取整（G4 默认 98→见上）；上游 /quality 按 int(...*100//max_penalty)
   取 floor（同情形为 97）。冒烟对账（B 段）仅断言无 finding 的 100 分，不受取整差异影响。
3. **后续重跑**：B 段用固定 SMOKE-P3- id，重跑需先清理残渣（删除族属 ADMIN 层，不在 P3）：
   记录中的残渣清单即清理对象。
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
