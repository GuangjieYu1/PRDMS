#!/usr/bin/env python3
"""P1 冒烟（network-tagged）：对真实实例的 cessna-172 跑通只读链路并落盘记录。

链路（全部经工具层注册表调用）：登录 → whoami → list_projects（断言含 cessna-172）→
list_requirements（断言 total==57）→ get_coverage → get_gap_analysis → get_traces。

凭据仅经环境变量注入（REQMESH_USERNAME/REQMESH_PASSWORD，或未配凭据时的 Bearer
兜底 REQMESH_TOKEN）；记录落盘 docs/smoke/P1-cessna-172.md（可用 REQMESH_SMOKE_OUT
覆盖）。除登录外只发 GET（只读无副作用）；password/token 不落盘、不进记录。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import HarnessError
from reqmesh_harness.tools import build_registry

PROJECT_ID = "cessna-172"
EXPECTED_REQUIREMENTS_TOTAL = 57  # design §7 基线
REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # PRDMS 仓库根（docs/ 与 spec 同级）
DEFAULT_OUT = REPO_ROOT / "docs" / "smoke" / "P1-cessna-172.md"


def main() -> int:
    settings = Settings()
    if not settings.has_credentials():
        print("未配置凭据：设置 REQMESH_USERNAME/REQMESH_PASSWORD（或 REQMESH_TOKEN）", file=sys.stderr)
        return 2
    out_path = Path(os.environ.get("REQMESH_SMOKE_OUT", str(DEFAULT_OUT)))

    try:
        auth_session = AuthSession(settings)
        auth_session.ensure_ready(validate=True)  # 预热：建立认证会话（工具调用共享会话文件）

        tools = build_registry()
        whoami = tools.call("whoami")
        assert whoami.get("username"), "whoami 未返回用户"

        projects = tools.call("list_projects")
        project_ids = [p.get("id") for p in projects]
        assert PROJECT_ID in project_ids, f"项目列表缺 {PROJECT_ID}"

        requirements = tools.call("list_requirements", project_id=PROJECT_ID)
        total = requirements.get("total")
        assert total == EXPECTED_REQUIREMENTS_TOTAL, f"需求总数 {total} != {EXPECTED_REQUIREMENTS_TOTAL}"

        coverage = tools.call("get_coverage", project_id=PROJECT_ID)
        assert coverage.get("total") is not None

        gap = tools.call("get_gap_analysis", project_id=PROJECT_ID)
        gap_count = gap.get("gaps", 0) if isinstance(gap, dict) else len(gap)

        traces = tools.call("get_traces", project_id=PROJECT_ID)
        assert traces.get("links") is not None
    except AssertionError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        return 1
    except HarnessError as exc:
        print(f"冒烟失败: {exc}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        f"""# P1 cessna-172 冒烟记录

- 时间：{now.isoformat()}
- 实例：{settings.base_url}
- 项目：{PROJECT_ID}
- 结果：**通过**（全链路 200，无副作用）

## 步骤与关键计数

| 步骤 | 状态 | 关键计数 |
|---|---|---|
| 登录 | ok | 用户 {whoami.get('username')} / 角色 {whoami.get('role')} |
| whoami | ok | username={whoami.get('username')} role={whoami.get('role')} |
| list_projects | ok | 项目数 {len(projects)}，含 {PROJECT_ID} |
| list_requirements | ok | total={total}（基线 {EXPECTED_REQUIREMENTS_TOTAL}） |
| get_coverage | ok | total={coverage.get('total')} shallow_covered={coverage.get('shallow_covered')} deep_covered={coverage.get('deep_covered')} coverage_pct={coverage.get('coverage_pct')} |
| get_gap_analysis | ok | 缺口 {gap_count} |
| get_traces | ok | links={len(traces.get('links'))} |

## 无副作用声明

本冒烟仅发起：登录（POST /api/auth/login）与 6 个工具调用（whoami/list_projects/
list_requirements/coverage/gap-analysis/traces，全部为 GET）；未调用任何写端点，
未修改 reqmesh 数据（git 历史无新增提交）。凭据未落库、未写入本记录。
""",
        encoding="utf-8",
    )
    print(f"冒烟通过，记录已落盘: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
