#!/usr/bin/env python3
"""P4 冒烟（network-tagged，不进默认 pytest 集合）：单段（全 READ，无 B 段、无残渣）。

- 目标：REQMESH_BASE_URL（默认 http://172.16.100.2:8000）的 cessna-172 项目；
- 流程：登录（POST）→ 六源基线采集（源工具调用，作 G1 对账对象）→
  get_traceability_gap_report 两次（G1–G4、G6）→ 前后 total 断言（G5）→
  记录落盘 docs/smoke/P4-cessna-172.md（REQMESH_SMOKE_OUT 可覆盖）；
- G1–G6（spec ⑥）：关键数字与 reqmesh 前端分析一致（跨源自洽，恒真抗漂移）/
  缺口清单完整（id 并集 + 点检）/ 建议模板命中 / 排序规则 / 零副作用 / 确定性；
- 双轨基线：绝对数断言（2026-09-02T05:38Z 快照：61/59-48-42-81-71/40/9/2/41/7）
  遇漂移按 P1 惯例降级注明（自洽断言保留，不失败）；
- 零副作用：调用前后 list_requirements.total 不变（61）、冒烟全程 HTTP 方法 ⊆ {GET}
  （登录 POST 除外）、git 提交数不变（is_repo=false 时降级注明）、审计 0 行；
- 只读端点：git 判断只用 /git/log（**绝不调用 git/status**——贡献者账号会 403）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.config import Settings
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.report import DIMENSION_TYPES, SEVERITY_RANK, render_action
from reqmesh_harness.tools import build_registry
from reqmesh_harness.tools.runtime import Runtime, set_runtime

PROJECT_ID = "cessna-172"

# 绝对数基线（2026-09-02T05:38Z live 实测快照；漂移时降级为历史基线，自洽断言保留）
BASELINE = {
    "requirements_total": 61,
    "coverage": {
        "total": 59,
        "shallow_covered": 48,
        "deep_covered": 42,
        "coverage_pct": 81,
        "deep_pct": 71,
    },
    "gap_analysis": {"total": 61, "gaps": 40},
    "traces": {"links": 9},
    "suspect_links": {"count": 2},
    "unreviewed": {"count": 41, "never": 40, "stale": 1},
    "allocation": {"rows": 61, "unallocated": 7},
}
CHECKPOINTS = {"SMOKE-P2-001", "AFRM0000"}

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # PRDMS 仓库根
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P4-cessna-172.md"

# 冒烟全程 HTTP 方法观察（登录 POST 是唯一例外）
_methods: list[tuple[str, str]] = []
_orig_impl = {
    m: getattr(httpx.Client, m) for m in ("get", "post", "put", "patch", "delete")
}


def _record(method: str):
    def wrap(self, url, **kwargs):
        _methods.append((method.upper(), str(url)))
        return _orig_impl[method](self, url, **kwargs)

    return wrap


def main() -> int:
    settings = Settings()
    if not settings.has_credentials():
        print(
            "未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）",
            file=sys.stderr,
        )
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))

    tmp = Path(tempfile.mkdtemp(prefix="smoke-p4-"))
    # 临时目录隔离会话/审计/白名单文件：绝不改动操作员真实 XDG 文件（P2/P3 同款）
    settings = settings.model_copy(
        update={
            "session_file": tmp / "session.json",
            "audit_file": tmp / "audit.jsonl",
            "approvals_file": tmp / "approvals.toml",
        }
    )
    set_runtime(Runtime(settings))
    audit = AuditLog(settings.audit_file)
    steps: list[tuple[str, str | int, str]] = []
    drift: list[str] = []

    def step(name: str, status: str | bool, detail: str = "") -> None:
        steps.append((name, "ok" if status is True else status, detail))

    try:
        for m in ("get", "post", "put", "patch", "delete"):
            setattr(httpx.Client, m, _record(m))

        initial = AuthSession(settings)
        initial.ensure_ready(validate=True)
        tools = build_registry()
        whoami = tools.call("whoami")
        step(
            "whoami",
            True,
            f"{whoami.get('username')}（role={whoami.get('role')}；P4 只读，view 层即可）",
        )

        git_repo, git_before = _git_commit_count(initial)
        total_before = _requirements_total(tools)

        # ---------------- 六源基线采集（G1 对账对象） ----------------
        sources = {
            "coverage": tools.call("get_coverage", project_id=PROJECT_ID),
            "gap_analysis": tools.call("get_gap_analysis", project_id=PROJECT_ID),
            "traces": tools.call("get_traces", project_id=PROJECT_ID),
            "suspect_links": tools.call("get_suspect_links", project_id=PROJECT_ID),
            "unreviewed": tools.call(
                "get_unreviewed_requirements", project_id=PROJECT_ID
            ),
            "allocation": tools.call("get_allocation_matrix", project_id=PROJECT_ID),
        }
        step(
            "六源基线采集",
            True,
            "coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix",
        )

        # ---------------- 报告两次（G1–G4、G6） ----------------
        report1 = tools.call("get_traceability_gap_report", project_id=PROJECT_ID)
        report2 = tools.call("get_traceability_gap_report", project_id=PROJECT_ID)
        step("get_traceability_gap_report ×2", True, "两次调用成功")

        # G1：跨源自洽（同次运行：报告数字 == 源工具数字——恒真抗漂移）
        s = report1["summary"]
        cov, gap, trc = sources["coverage"], sources["gap_analysis"], sources["traces"]
        sus, unrev, alloc = (
            sources["suspect_links"],
            sources["unreviewed"],
            sources["allocation"],
        )
        assert (
            s["requirements_total"] == gap["total"]
        ), "requirements_total != gap_analysis.total"
        assert s["coverage"]["total"] == cov["total"]
        assert s["coverage"]["shallow_covered"] == cov["shallow_covered"]
        assert s["coverage"]["deep_covered"] == cov["deep_covered"]
        assert s["coverage"]["coverage_pct"] == cov["coverage_pct"]
        assert s["coverage"]["deep_pct"] == cov["deep_pct"]
        assert s["gap_analysis"] == {"total": gap["total"], "gaps": gap["gaps"]}
        assert s["traces"]["links"] == len(trc["links"])
        assert s["suspect_links"]["count"] == sus["count"]
        assert s["unreviewed"]["count"] == len(unrev["items"])
        assert s["unreviewed"]["never"] == sum(
            1 for i in unrev["items"] if i.get("reviewed") is None
        )
        assert s["unreviewed"]["stale"] == sum(
            1
            for i in unrev["items"]
            if i.get("reviewed") is not None
            and i.get("reviewed") != i.get("current_fingerprint")
        )
        assert s["allocation"]["rows"] == len(alloc["rows"])
        assert s["allocation"]["unallocated"] == sum(
            1 for r in alloc["rows"] if not r.get("allocated_to")
        )
        step("G1 跨源自洽", True, "summary 逐项 == 同次运行六源工具返回值")

        # G1 绝对数快照（漂移降级为历史基线）
        abs_ok = (
            s["requirements_total"] == BASELINE["requirements_total"]
            and all(s["coverage"][k] == v for k, v in BASELINE["coverage"].items())
            and s["gap_analysis"] == BASELINE["gap_analysis"]
            and s["traces"]["links"] == BASELINE["traces"]["links"]
            and s["suspect_links"]["count"] == BASELINE["suspect_links"]["count"]
            and s["unreviewed"] == BASELINE["unreviewed"]
            and (s["allocation"]["rows"], s["allocation"]["unallocated"])
            == (BASELINE["allocation"]["rows"], BASELINE["allocation"]["unallocated"])
        )
        if abs_ok:
            step(
                "G1 绝对数基线",
                True,
                f"与 2026-09-02T05:38Z 快照一致：{s['requirements_total']} / "
                f"{s['coverage']['total']}-{s['coverage']['shallow_covered']}-{s['coverage']['deep_covered']}-"
                f"{s['coverage']['coverage_pct']}-{s['coverage']['deep_pct']} / {s['gap_analysis']['gaps']} / "
                f"{s['traces']['links']} / {s['suspect_links']['count']} / "
                f"{s['unreviewed']['count']}（{s['unreviewed']['never']}+{s['unreviewed']['stale']}）/ "
                f"{s['allocation']['rows']} 行-{s['allocation']['unallocated']} 未分配",
            )
        else:
            note = (
                f"快照仅作历史基线：实测 {s['requirements_total']} / {s['coverage']['total']}-"
                f"{s['coverage']['shallow_covered']}-{s['coverage']['deep_covered']} / "
                f"{s['gap_analysis']['gaps']} / {s['traces']['links']} / {s['suspect_links']['count']} / "
                f"{s['unreviewed']['count']}（{s['unreviewed']['never']}+{s['unreviewed']['stale']}）/"
                f"{s['allocation']['unallocated']}"
            )
            drift.append(note)
            step(
                "G1 绝对数基线",
                "降级（漂移→历史基线）",
                note + "；自洽断言保留（恒真）",
            )

        # G2：缺口清单完整（id 并集，无丢失、无编造）
        union: set[str] = set()
        for item in cov["items"]:
            if (
                item.get("uncovered_types")
                or item.get("broken_chain")
                or item.get("unwanted_coverage")
            ):
                union.add(item["id"])
        union.update(i["id"] for i in gap["items"])
        union.update(l["target"] for l in sus["links"])
        union.update(i["id"] for i in unrev["items"])
        union.update(
            r.get("req_id") or r.get("row_id")
            for r in alloc["rows"]
            if not r.get("allocated_to")
        )
        master_ids = {g["id"] for g in report1["gaps"]}
        assert master_ids == union, (
            sorted(master_ids - union),
            sorted(union - master_ids),
        )
        step(
            "G2 缺口清单完整",
            True,
            f"master gaps {len(master_ids)} 条 == 六源缺口 id 并集（无丢失、无编造）",
        )

        # G2 点检（实体在缺口并集内才断言；漂移缺失则降级注明）
        by_id = {g["id"]: g for g in report1["gaps"]}
        if "SMOKE-P2-001" in by_id:
            entry = by_id["SMOKE-P2-001"]
            types = {d["type"] for d in entry["dimensions"]}
            assert "review.stale" in types, entry
            stale = [d for d in entry["dimensions"] if d["type"] == "trace.stale"]
            assert len(stale) == 2, (entry["id"], len(stale))
            for d in stale:
                ev = d["evidence"]
                assert {"link_type", "from", "reason"} <= set(ev), ev
            step(
                "G2 点检 SMOKE-P2-001",
                True,
                "review.stale + 2×trace.stale（evidence 含 link_type/from/reason）",
            )
        else:
            drift.append("SMOKE-P2-001 已不在缺口并集（漂移）")
            step(
                "G2 点检 SMOKE-P2-001",
                "降级",
                "不在缺口并集（漂移），按历史点检样本跳过",
            )
        if "AFRM0000" in by_id:
            entry = by_id["AFRM0000"]
            types = {d["type"] for d in entry["dimensions"]}
            assert (
                "coverage.uncovered:design" in types and "allocation.missing" in types
            ), entry
            assert len(entry["actions"]) == len(entry["dimensions"])
            step(
                "G2 点检 AFRM0000",
                True,
                "coverage.uncovered(design) + allocation.missing 同根并存",
            )
        else:
            drift.append("AFRM0000 已不在缺口并集（漂移）")
            step("G2 点检 AFRM0000", "降级", "不在缺口并集（漂移），按历史点检样本跳过")

        # G3：建议模板命中（每条 action 命中模板表 + tool_hint ⊆ 既有写工具名 + spec 抽样）
        write_tools = {s.name for s in tools.all() if s.level in ("DRAFT", "MUTATE")}
        for g in report1["gaps"]:
            for dim in g["dimensions"]:
                need_type = (dim.get("evidence") or {}).get("need_type")
                expected = render_action(dim["type"], g["id"], need_type)
                assert any(a["action"] == expected for a in g["actions"]), (
                    g["id"],
                    dim["type"],
                )
                assert all(set(a["tool_hint"]) <= write_tools for a in g["actions"])
        assert {d["type"] for g in report1["gaps"] for d in g["dimensions"]} <= set(
            DIMENSION_TYPES
        )
        step(
            "G3 建议模板命中", True, "每条 action 命中模板表；tool_hint ⊆ 既有写工具名"
        )
        sample_checks = []
        for g in report1["gaps"]:
            for dim in g["dimensions"]:
                if dim["type"] == "trace.unlinked":
                    a = next(a for a in g["actions"] if "读-改-写" in a["action"])
                    sample_checks.append(
                        ("trace.unlinked", a["tool_hint"] == ["set_relations"])
                    )
                elif dim["type"] == "content.no_source":
                    a = next(a for a in g["actions"] if "来源" in a["action"])
                    sample_checks.append(
                        ("content.no_source", a["tool_hint"] == ["update_requirement"])
                    )
                elif dim["type"] == "review.never":
                    a = next(
                        a for a in g["actions"] if a["tool_hint"] == ["review_item"]
                    )
                    sample_checks.append(("review.never", "review_item" in a["action"]))
                elif dim["type"] == "allocation.missing":
                    a = next(
                        a for a in g["actions"] if a["tool_hint"] == ["set_allocation"]
                    )
                    sample_checks.append(
                        (
                            "allocation.missing",
                            "set_allocation(allocated=true)" in a["action"],
                        )
                    )
        assert all(ok for _, ok in sample_checks), sample_checks
        seen = {name for name, _ in sample_checks}
        step("G3 抽样断言", True, f"{'、'.join(sorted(seen))} 模板命中（G3 列）")

        # G4：排序规则（主清单三重键；条目内维度/actions）
        gaps = report1["gaps"]
        for prev, cur in zip(gaps, gaps[1:]):
            key = lambda g: (
                -SEVERITY_RANK[g["max_severity"]],
                -len(g["dimensions"]),
                g["id"],
            )
            assert key(prev) <= key(cur), (prev["id"], cur["id"])
        for g in gaps:
            for prev, cur in zip(g["dimensions"], g["dimensions"][1:]):
                assert (-SEVERITY_RANK[prev["severity"]], prev["type"]) <= (
                    -SEVERITY_RANK[cur["severity"]],
                    cur["type"],
                )
            for prev, cur in zip(g["actions"], g["actions"][1:]):
                assert (-SEVERITY_RANK[prev["severity"]], prev["action"]) <= (
                    -SEVERITY_RANK[cur["severity"]],
                    cur["action"],
                )
        step(
            "G4 排序规则",
            True,
            "三重键（severity 降序 → 维度数降序 → id 升序）+ 条目内规则",
        )

        # ⑤ 过滤（接受标准 #9；summary 全量 + chapters/gaps 过滤）
        filtered = tools.call(
            "get_traceability_gap_report",
            project_id=PROJECT_ID,
            dimensions=["review.never", "review.stale"],
        )
        assert filtered["summary"] == s, "过滤后 summary 应全量不变"
        assert filtered["meta"]["filters"] == {
            "dimensions": ["review.never", "review.stale"]
        }
        assert all(
            {d["type"] for d in g["dimensions"]} <= {"review.never", "review.stale"}
            for g in filtered["gaps"]
        )
        step("维度过滤", True, "dimensions 白名单 → chapters/gaps 过滤、summary 全量")

        # G6：确定性（两次调用除 generated_at 外逐字节一致）
        def _canon(r: dict) -> str:
            return json.dumps(
                {**r, "generated_at": None}, ensure_ascii=False, sort_keys=True
            )

        assert _canon(report1) == _canon(report2), "两次调用除 generated_at 外不一致"
        step("G6 确定性", True, "两次调用逐字节一致（generated_at 除外）")

        # G5：零副作用（total 不变 / 方法 ⊆ GET / git 条件断言 / 审计 0 行）
        total_after = _requirements_total(tools)
        assert (
            total_after == total_before
        ), f"total 变化: {total_before} → {total_after}"
        git_repo, git_after = _git_commit_count(initial)
        assert git_after == git_before, f"git 提交数变化: {git_before} → {git_after}"
        non_get = [(m, u) for m, u in _methods if m != "GET"]
        unexpected = [
            (m, u) for m, u in non_get if not (m == "POST" and "/api/auth/login" in u)
        ]
        assert not unexpected, f"冒烟期间非 GET 请求: {unexpected}"
        assert audit.read_all() == [], f"READ 层不应产生审计行: {audit.read_all()}"
        git_note = f"git 提交数 {git_before} → {git_after}（不变；is_repo={git_repo}）"
        if not git_repo:
            git_note += " ——项目未初始化 git 仓库，提交计数断言降级注明"
        step(
            "G5 零副作用",
            True,
            f"total {total_before} → {total_after}（不变）· 冒烟期间非 GET 仅登录 POST · 审计 0 行 · "
            + git_note,
        )

    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        _write_record(
            out_path,
            settings,
            steps,
            failed=str(exc),
            git_info=None,
            drift=drift,
            baseline=None,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 — 冒烟脚本：任何异常均记录并返回失败
        print(f"冒烟失败: {exc!r}", file=sys.stderr)
        _write_record(
            out_path,
            settings,
            steps,
            failed=repr(exc),
            git_info=None,
            drift=drift,
            baseline=None,
        )
        return 1
    finally:
        for m, impl in _orig_impl.items():
            setattr(httpx.Client, m, impl)

    _write_record(
        out_path,
        settings,
        steps,
        failed=None,
        git_info={"before": git_before, "after": git_after, "is_repo": git_repo},
        drift=drift,
        baseline={"total": total_before, "summary": s},
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
    """(is_repo, commit_count)：仅用 /git/log；**绝不调用 git/status**（contributor 403）。"""
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


def _write_record(
    out_path, settings, steps, *, failed, git_info, drift, baseline
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    rows = "\n".join(
        (
            f"| {name} | ok | {detail} |"
            if status is True
            else f"| {name} | {status} | {detail} |"
        )
        for name, status, detail in steps
    )
    git_section = (
        (
            f"git 提交计数：{git_info['before']} → {git_info['after']}（不变；is_repo={git_info['is_repo']}）"
        )
        if git_info
        else "（失败，记录不完整）"
    )
    drift_section = (
        "\n".join(f"- {d}" for d in drift)
        if drift
        else "无（绝对数快照与 2026-09-02T05:38Z 实测一致）"
    )
    baseline_section = (
        "| requirements_total | 61 | list_requirements total |\n"
        "| coverage | 59 / 48-42-81-71 | get_coverage {total, shallow-deep-pct} |\n"
        "| gap_analysis | total=61, gaps=40 | get_gap_analysis |\n"
        "| traces | 9 条链接 | get_traces |\n"
        "| suspect_links | 2 | get_suspect_links |\n"
        "| unreviewed | 41（40 never + 1 stale = SMOKE-P2-001） | get_unreviewed_requirements |\n"
        "| allocation | 61 行，7 未分配（AFRM0000/AVNC0006/AVNC0010/OVERVIEW01/SMOKE-P3-001..003） | get_allocation_matrix |"
    )
    out_path.write_text(
        f"""# P4 cessna-172 冒烟记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- 项目：{PROJECT_ID}
- 结果：**{"通过" if failed is None else f"失败: {failed}"}**
- 账号：个人账号（yugj/contributor 或服务账号均可；P4 全 READ，require_view 层）

## 基线快照（2026-09-02T05:38Z 需求会话 live 实测）

{baseline_section}

## 步骤与关键计数

{rows}

## git 与零副作用

{git_section}

- 零副作用声明：调用前后 list_requirements.total 不变；冒烟期间 HTTP 方法 ⊆ {{GET}}（登录 POST 除外）；
  审计日志 0 行（全 READ，不涉审批门/审计写行）；git 提交数不变（is_repo=false 时降级注明）；
  **P4 无 B 段**——无任何真实写闭环与残渣。

## 实测偏差与开发会话注记（待需求会话确认）

{drift_section}
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
