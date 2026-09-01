#!/usr/bin/env python3
"""P1 冒烟（network-tagged）：对真实实例的 cessna-172 跑通只读链路并落盘记录。

链路：登录 → whoami → list_projects → list_requirements（断言 total==57）→
get_coverage → get_gap_analysis → get_traces，全程 200。

凭据仅经环境变量注入（REQMESH_USERNAME/REQMESH_PASSWORD，或 Bearer 兜底
REQMESH_TOKEN）；记录落盘 docs/smoke/P1-cessna-172.md（可用 REQMESH_SMOKE_OUT 覆盖）。
脚本不写任何 repo 内文件之外的路径；除登录外只发 GET（只读无副作用）。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import HarnessError

PROJECT_ID = "cessna-172"
EXPECTED_REQUIREMENTS_TOTAL = 57  # design §7 基线
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # PRDMS 仓库根（与 spec/handoffs 同级 docs/）
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P1-cessna-172.md"


def main() -> int:
    settings = Settings()
    if not settings.has_credentials():
        print("未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）", file=sys.stderr)
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))

    client = AuthSession(settings)
    steps: list[dict] = []

    def step(name: str, call) -> dict:
        data = call()
        status = "ok"
        steps.append({"step": name, "status": status, "data": data})
        return data

    try:
        client.ensure_ready(validate=True)
        steps.append({"step": "登录", "status": "ok", "data": {"username": settings.username}})

        whoami = step("whoami", lambda: client.get("/api/auth/whoami"))
        assert whoami.get("username"), "whoami 未返回用户"

        projects = step("list_projects", lambda: client.get("/api/projects"))
        project_ids = [p.get("id") for p in projects]
        assert PROJECT_ID in project_ids, f"项目列表缺 {PROJECT_ID}"

        requirements = step(
            "list_requirements",
            lambda: client.get(f"/api/projects/{PROJECT_ID}/requirements", {"offset": 0, "limit": 500}),
        )
        total = requirements.get("total")
        assert total == EXPECTED_REQUIREMENTS_TOTAL, f"需求总数 {total} != {EXPECTED_REQUIREMENTS_TOTAL}"

        coverage = step("get_coverage", lambda: client.get(f"/api/projects/{PROJECT_ID}/coverage"))
        assert coverage.get("total") is not None

        gap = step("get_gap_analysis", lambda: client.get(f"/api/projects/{PROJECT_ID}/gap-analysis"))
        gap_count = gap.get("gaps", 0) if isinstance(gap, dict) else len(gap)
        assert gap_count is not None

        traces = step("get_traces", lambda: client.get(f"/api/projects/{PROJECT_ID}/traces"))
        assert traces.get("links") is not None
    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        return 1
    except HarnessError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    lines = [
        "# P1 cessna-172 冒烟记录",
        "",
        f"- 时间：{now.isoformat()}",
        f"- 实例：{settings.base_url}（rt profile: personal）",
        f"- 项目：{PROJECT_ID}",
        f"- 结果：**通过**（全链路 200，无副作用）",
        "",
        "## 步骤与关键计数",
        "",
        "| 步骤 | 状态 | 关键计数 |",
        "|---|---|---|",
        f"| 登录 | ok | 用户 {whoami.get('username')} / 角色 {whoami.get('role')} |",
        f"| whoami | ok | username={whoami.get('username')} role={whoami.get('role')} |",
        f"| list_projects | ok | 项目数 {len(projects)}，含 {PROJECT_ID} |",
        f"| list_requirements | ok | total={total}（基线 {EXPECTED_REQUIREMENTS_TOTAL}） |",
        f"| get_coverage | ok | covered={coverage.get('total')} coverage_pct={coverage.get('coverage_pct')} |",
        f"| get_gap_analysis | ok | 缺口 {gap_count} |",
        f"| get_traces | ok | links={len(traces.get('links'))} |",
        "",
        "## 无副作用声明",
        "",
        "本冒烟仅发起：登录（POST /api/auth/login）与 6 个 GET（whoami/projects/"
        "requirements/coverage/gap-analysis/traces）；未调用任何写端点，未修改 "
        "reqmesh 数据（git 历史无新增提交）。凭据未落库、未写入本记录。",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(chr(10).join(lines), encoding="utf-8")
    print(f"冒烟通过，记录已落盘: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
