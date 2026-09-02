# P4 cessna-172 冒烟记录

- 时间：2026-09-02T06:53:39.173193+00:00
- 实例：http://172.16.100.2:8000
- 项目：cessna-172
- 结果：**通过**
- 账号：个人账号（yugj/contributor 或服务账号均可；P4 全 READ，require_view 层）

## 基线快照（2026-09-02T05:38Z 需求会话 live 实测）

| requirements_total | 61 | list_requirements total |
| coverage | 59 / 48-42-81-71 | get_coverage {total, shallow-deep-pct} |
| gap_analysis | total=61, gaps=40 | get_gap_analysis |
| traces | 9 条链接 | get_traces |
| suspect_links | 2 | get_suspect_links |
| unreviewed | 41（40 never + 1 stale = SMOKE-P2-001） | get_unreviewed_requirements |
| allocation | 61 行，7 未分配（AFRM0000/AVNC0006/AVNC0010/OVERVIEW01/SMOKE-P3-001..003） | get_allocation_matrix |

## 步骤与关键计数

| whoami | ok | reqmesh-harness（role=maintainer；P4 只读，view 层即可） |
| 六源基线采集 | ok | coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix |
| get_traceability_gap_report ×2 | ok | 两次调用成功 |
| G1 跨源自洽 | ok | summary 逐项 == 同次运行六源工具返回值 |
| G1 绝对数基线 | ok | 与 2026-09-02T05:38Z 快照一致：61 / 59-48-42-81-71 / 40 / 9 / 2 / 41（40+1）/ 61 行-7 未分配 |
| G2 缺口清单完整 | ok | master gaps 57 条 == 六源缺口 id 并集（无丢失、无编造） |
| G2 点检 SMOKE-P2-001 | ok | review.stale + 2×trace.stale（evidence 含 link_type/from/reason） |
| G2 点检 AFRM0000 | ok | coverage.uncovered(design) + allocation.missing 同根并存 |
| G3 建议模板命中 | ok | 每条 action 命中模板表；tool_hint ⊆ 既有写工具名 |
| G3 抽样断言 | ok | allocation.missing、content.no_source、review.never、trace.unlinked 模板命中（G3 列） |
| G4 排序规则 | ok | 三重键（severity 降序 → 维度数降序 → id 升序）+ 条目内规则 |
| 维度过滤 | ok | dimensions 白名单 → chapters/gaps 过滤、summary 全量 |
| G6 确定性 | ok | 两次调用逐字节一致（generated_at 除外） |
| G5 零副作用 | ok | total 61 → 61（不变）· 冒烟期间非 GET 仅登录 POST · 审计 0 行 · git 提交数 0 → 0（不变；is_repo=False） ——项目未初始化 git 仓库，提交计数断言降级注明 |

## git 与零副作用

git 提交计数：0 → 0（不变；is_repo=False）

- 零副作用声明：调用前后 list_requirements.total 不变；冒烟期间 HTTP 方法 ⊆ {GET}（登录 POST 除外）；
  审计日志 0 行（全 READ，不涉审批门/审计写行）；git 提交数不变（is_repo=false 时降级注明）；
  **P4 无 B 段**——无任何真实写闭环与残渣。

## 实测偏差与开发会话注记（待需求会话确认）

无（绝对数快照与 2026-09-02T05:38Z 实测一致）
