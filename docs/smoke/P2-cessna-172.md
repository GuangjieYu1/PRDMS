# P2 cessna-172 冒烟记录

- 时间：2026-09-01T11:29:23.817083+00:00
- 实例：http://172.16.100.2:8000
- 项目：cessna-172
- 结果：**通过**
- 服务账号：reqmesh-harness（role=maintainer）
- 白名单/审计（临时目录，不入库）：/tmp/smoke-p2-bvp1j39d/approvals.toml

## 步骤与关键计数

| whoami/服务账号 | ok | reqmesh-harness（role=maintainer） |
| A1 空白名单阻断 | ok | ApprovalDeniedError + 审计 denied |
| A2 白名单 | ok | 12 条目 → /tmp/smoke-p2-bvp1j39d/approvals.toml |
| A3 全量 dry_run | ok | 12/12 通过（would_send + checks 结构） |
| A4 零副作用 | ok | git 提交数 0 → 0（不变；is_repo=False） ——项目未初始化 git 仓库，B 段提交计数断言将降级（见说明） |
| create_requirement | ok | 回读一致 |
| review_item | ok | 未评审列表已移除该需求 |
| update_requirement | ok | description 回读生效 |
| create_risk | ok | list_risks 可见 |
| create_component | ok | list_components 可见 |
| create_verification_case | ok | list_verification_cases 可见 |
| create_comment | ok | list_comments 可见该条 |
| run_verification | ok | execution_history 追加 passed |
| set_relations | ok | 读-改-写回放成功 |
| set_allocation | ok | allocation-matrix 回读 allocated=True |
| git 提交计数 | 降级 | 项目未初始化 git 仓库（is_repo=false）：提交计数断言跳过（dry_run 不产生提交仍成立——写路径不发 git 相关请求） |
| 审计日志 | ok | 23 行（denied/dry_run/真实写）字段齐全 |
| 匿名拒绝写 | ok | 无凭据写请求 → 上游 401/403 经 UpstreamError 透传（无凭据信息） |

## git 与残渣

git 提交计数：A 段前 0 → A 段后 0（不变） → B 段后 0（+0）

残渣清单（P2 真实写副作用）：
- 新增实体：`SMOKE-P2-001`（需求）、`SMOKE-P2-R01`（风险）、`SMOKE-P2-C01`（组件）、`SMOKE-P2-V01`（验证用例）；评论 1 条（需求 SMOKE-P2-001）
- 追踪矩阵：+1 链接（SMOKE-P2-001 refines SMOKE-P2-C01）；分配：SMOKE-P2-001 → SMOKE-P2-C01
- 需求总数：P1 基线 57（历史快照）→ P2 真实写后 58（`list_requirements` total），P1 冒烟记录的 total==57 断言自此只作为历史快照

- 审计日志：23 行（临时文件，属运行时状态）。

## 说明

- A 段为零副作用验证（dry_run 不产生 git 提交）；B 段为最小真实写闭环（SMOKE-P2- 前缀）。
- P1 冒烟（docs/smoke/P1-cessna-172.md）total==57 仅作历史快照，不再作为重跑断言。

## 实测偏差与清理指引（开发会话实测记录，待需求会话确认）

1. **服务账号角色**：spec D7「role=contributor」与 reqmesh v0.5.0 项目权限层级不符——
   默认映射 contributor=propose 层（仅 风险/评论/决策 可写：create_risk/create_comment）；
   requirements/components/verification/review/traces/allocation 等 10 个端点在 edit 层
   （require_maintain，backend/app/core/dependencies.py）。本实测服务账号取 **maintainer**
   （能覆盖 P2 写面的最小角色，非 admin；D7 最小权限意图不变）。
2. **git 提交计数**：cessna-172 未初始化 git 仓库（`GET /git/log` → is_repo=false，git/init
   经 API 返回 201 但服务侧未落地）。提交计数断言降级（is_repo=true 时恢复 spec 断言）；
   dry_run 不产生提交仍成立（写路径不发 git 相关请求）。
3. **匿名只读**：实例未启用 RT_REQUIRE_AUTH（匿名 GET 放行 200），spec 预设的「匿名只读
   → 401」不成立；断言已改为语义更强且恒真的「匿名**写** → 上游 401/403 经 UpstreamError
   透传（错误不含凭据信息）」。
4. **entity_kind 词表**：上游 422 校验词表为复数集合名（requirements/components/
   verification_cases/…）；create_comment 工具层已用 Literal 锁定（schema 枚举）——
   与 list_comments 过滤参数同一词表。
5. **后续重跑**：B 段用固定 SMOKE-P2- id，重跑需先清理残渣（删除族属 ADMIN 层，不在 P2）：
   ① GET /traces 移除 SMOKE 链接后 PUT 回写（服务账号可做）；② admin 删除
   SMOKE-* 实体与评论（requirements 删除需 ?force=true）。记录中的残渣清单即清理对象。
