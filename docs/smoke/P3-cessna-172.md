# P3 cessna-172 冒烟记录

- 时间：2026-09-02T02:21:56.372827+00:00
- 实例：http://172.16.100.2:8000
- 项目：cessna-172
- 结果：**通过**
- 服务账号：reqmesh-harness（role=maintainer）
- 白名单/审计（临时目录，不入库）：/tmp/smoke-p3-2l9zewwc/approvals.toml

## 步骤与关键计数

| whoami/服务账号 | ok | reqmesh-harness（role=maintainer） |
| A1 空白名单阻断 | ok | ApprovalDeniedError（fix_hint 含 approvals add） + 审计 denied 行 |
| A2 白名单 | ok | draft_requirement+cessna-172 → /tmp/smoke-p3-2l9zewwc/approvals.toml |
| A3 金样例全量 dry_run | ok | G1–G5 五句式（ears 逐字符一致 + lint score=100 + rounds=1） |
| A4 零副作用 | ok | total 58 → 58（不变）· git 提交数 0 → 0（不变；is_repo=False） ——项目未初始化 git 仓库，B 段提交计数断言降级（见说明） |
| B 段 SMOKE-P3-001 | ok | ubiquitous 落库·回读相等·unreviewed 可见·服务端分=100 |
| B 段 SMOKE-P3-002 | ok | event 落库·回读相等·unreviewed 可见·服务端分=100 |
| B 段 SMOKE-P3-003 | ok | unwanted 落库·回读相等·unreviewed 可见·服务端分=100 |
| 需求总数 | ok | 58 → 61（+3 == B 段真实写调用数） |
| git 提交计数 | 降级 | 项目未初始化 git 仓库（is_repo=false）：提交计数断言跳过（dry_run 不产生提交仍成立） |
| 审计日志 | ok | 9 行（denied/dry_run/真实写）字段齐全（含 lint_score/lint_rounds） |

## git 与残渣

git 提交计数：A 段前 0 → A 段后 0（不变） → B 段后 0（+0）

残渣清单（P3 真实写副作用）：
- 新增需求（SMOKE-P3-）：SMOKE-P3-001（G1 ubiquitous）、SMOKE-P3-002（G2 event）、SMOKE-P3-003（G5 unwanted）——保持未评审（B 段不调用 review_item 是设计语义）
- 需求总数：P2 基线 58（历史快照）→ P3 真实写后 61

- 审计日志：9 行（临时文件，属运行时状态）。

## 说明

- A 段为零副作用验证：G1–G5 全量 dry_run（ears 逐字符一致 + lint score=100 + rounds=1），
  total 不变（58）、无真实写调用（审计仅 denied/dry_run 行）、
  git 提交数不变（条件断言）。
- B 段为最小真实写闭环（SMOKE-P3- 前缀）：文本级回读相等断言（sanitize 后纯文本原样回读）、
  status==proposed、rationale 含 NL 原文溯源、unreviewed 可见、服务端分 == 本地分（100 对账）。
- **name 派生复核（补充断言，运行后追加）**：spec ③ 要求 would_send.body.name 与映射模板一致；
  首次运行后已对 scripts/smoke_p3.py 补充 name 逐字符断言，并对 B 段落库实体做了只读回读核验：
  SMOKE-P3-001 name == "Achieve a range of at least 1185 km at maximum cruise power"、
  SMOKE-P3-002 == "Display the overspeed warning"、SMOKE-P3-003 == "Display a door warning within 1 s"
  ——与派生规则（response 首字母大写、截 80 字符）逐字符一致，重跑时该断言随 A 段执行。
- P1/P2 冒烟记录的 total==57/58 仅作历史快照，不再作为重跑断言。

## 实测偏差与开发会话注记（待需求会话确认）

1. **G5 默认 config == 98（与 G4 同）**：spec ⑥ 仅列举 G4「is engaged」触发 passive_voice；
   实测 G5「is unlatched」同为 be+过去分词（-ed 词尾），按 spec 规则表语义在**默认 config**下
   同为 98 分（cessna-172 config 已关 passive_voice → 两者均 100，冒烟不受影响）。单元测试
   tests/test_lint.py 已按此行为断言并注明；若需求会话认为 G5 应豁免，需放宽规则表说明。
2. **打分取整（spec 判例修正，待需求会话确认）**：spec ③ 判例「G4 默认 config==98」按 round 计算；
   上游 /quality 用 int(clamped*100//max_penalty)（floor）→ 同情形为 97。开发会话采纳**上游一致
   公式**（floor，硬约束「打分公式与上游一致」），本地 G4/G5 默认 config 断言 97（tests/test_lint.py），
   并把 spec 的 98 判例作为实测偏差记入本清单。冒烟对账（B 段）仅断言无 finding 的 100 分，
   floor/round 在 100 分处无差异。
3. **后续重跑**：B 段用固定 SMOKE-P3- id，重跑需先清理残渣（删除族属 ADMIN 层，不在 P3）：
   记录中的残渣清单即清理对象。
4. **spec ⑥ type 列（回流第 1 轮补充）**：spec ⑥ 金样例表含 type 列（G1=non_functional_performance、
   G5=safety 等）；首次运行按 spec ②「默认 functional」落库。回流后 smoke_p3.py 已按表传 type
   并逐断言（A/B 段），运行后重跑即可核对；首次运行实体的 type==functional 属首版行为，
   待需求会话确认「⑥ 的 type 列是否应作为调用参数」后再定口径（记录不重写历史的既定事实）。
