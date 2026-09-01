# P1 cessna-172 冒烟记录

- 时间：2026-09-01T11:29:34.231629+00:00
- 实例：http://172.16.100.2:8000
- 项目：cessna-172
- 结果：**通过**（全链路 200，无副作用）

## 步骤与关键计数

| 步骤 | 状态 | 关键计数 |
|---|---|---|
| 登录 | ok | 用户 yugj / 角色 contributor |
| whoami | ok | username=yugj role=contributor |
| list_projects | ok | 项目数 1，含 cessna-172 |
| list_requirements | ok | total=58（基线 ≥57；P2 真实写后可能增长——历史快照见 P1 记录，不再作为精确重跑断言） |
| get_coverage | ok | total=56 shallow_covered=45 deep_covered=39 coverage_pct=80 |
| get_gap_analysis | ok | 缺口 37 |
| get_traces | ok | links=9 |

## 无副作用声明

本冒烟仅发起：登录（POST /api/auth/login）与 6 个工具调用（whoami/list_projects/
list_requirements/coverage/gap-analysis/traces，全部为 GET）；未调用任何写端点，
未修改 reqmesh 数据（git 历史无新增提交）。凭据未落库、未写入本记录。
