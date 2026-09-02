# P3 开发会话完成报告：复合技能① 自然语言建需求（EARS + quality lint 闭环）

> 产出时间：2026-09-02（开发会话收口）；依据 design §5 流程：本地提交，**未推送**（推送是方向层唯一职责）。

## 1. 入口与范围

- Epic：#3；Tickets：#25–#30（全部关闭，见 §6）
- Spec：docs/specs/p3-nl-requirements.md；交接：docs/handoffs/p3-nl-requirements.md
- 硬约束核对：未 push（origin/main 仍停在 aa6b76f；本地 main 领先 5 commits）；P1/P2 资产零修改
  （writes.py/_write_common.py/guardrails\*/client\*/server.py/cli.py 未动，仅 import 复用 + registry 加行）；
  未动 reqmesh/ 上游目录；许可证边界按「独立重写」执行（见 §4 偏差）

## 2. Git 历史（本地 main，未推送）

- b612909 docs(P3): 需求会话产出 — spec/开放问题①–⑥决策/tickets #25–#30/交接文本
- 4a593c9 feat(P3): 复合技能①实现 — EARS 五句式 + 本地 quality lint 闭环 + 两个工具（#25–#28）
- 020056e fix(P3): 回流第 1 轮 — 审核/测试子代理发现修复（#25–#29）
- a776f3f fix(P3): 回流第 2 轮 — 许可证边界独立化收尾（review 有条件通过转通过）

## 3. 交付物

| 产物 | 路径 |
|---|---|
| EARS 解析/渲染 | reqmesh-harness/src/reqmesh_harness/ears/（五句式 + 要点形式 + 混用冲突 + 英文槽位边界） |
| 本地 quality lint | reqmesh-harness/src/reqmesh_harness/lint/（20 条规则镜像 + config 装载 + 6 类修正表 + 残余白名单） |
| 复合工具 | reqmesh-harness/src/reqmesh_harness/tools/groups/skills.py（draft_requirement + get_requirement_quality） |
| 注册表/导出 | 37 → 39 工具（26 READ + 7 DRAFT + 6 MUTATE）；OpenAI 导出 golden 同步 |
| 离线测试 | tests/test_ears.py(36) + test_lint.py(56) + test_skills.py(22) + mapping/既有测试更新 |
| 冒烟 | scripts/smoke_p3.py；记录 docs/smoke/P3-cessna-172.md（live 通过） |
| ADR-0002 回写 | verb 词汇表扩展 draft + draft_/DRAFT 同形歧义消解 |
| README | P3 范围 + 目录表 + 服务账号角色修正（maintainer） |

## 4. 测试结果

- 全量离线：**329 passed / 2 skipped / 2 deselected（network 冒烟）**；P1/P2 既有 215 个零回退；
  新增 114 个用例。
- 测试真实性（测试子代理核验）：无恒真断言；金样例逐字符/打分权重/三终态/409 重取均强断言；
  6 类修正各至少 1 条用例会红于删除对应替换；mapping expect_body 与实际 POST body 逐字段一致。
- Live 冒烟（172.16.100.2，reqmesh-harness maintainer）：A 段零副作用（G1–G5 dry_run：
  ears 逐字符一致 + lint score=100 + rounds=1 + total 58→58 + 审计 6 行）+ B 段真实写闭环
  （SMOKE-P3-001..003 = G1/G2/G5：文本级回读相等 + status=proposed + unreviewed 可见 +
  服务端分==本地分==100 + total→61 + 审计 9 行含 lint_score/lint_rounds）；git 断言
  is_repo=false 条件降级（P2 同款）。

## 5. 回流记录

- 第 1 轮（审核 + 测试子代理）：P0 许可证（规则正则独立重写，15/17 与上游不同形）、
  P1 打分 round→floor（上游一致）、P1-1 义务位情态衔接（should 句式闭环）、
  P1-2 gerund 归一、P2-3 双 shall/双 then、P2-4 冒烟 type 列、P3-5 system 槽位边界、
  P3-6 config 逐字段；各轮结论已记对应 ticket comment。
- 第 2 轮（核验子代理）：有条件通过 → 独立化收尾（MEASURABLE_RE/escape_clauses）→ 通过。

## 6. Issue 状态

- ✅ #25 lint 模块 · ✅ #26 EARS 模板与解析 · ✅ #27 draft_requirement 复合工具
- ✅ #28 get_requirement_quality + 39 工具对账 · ✅ #29 离线测试套件 · ✅ #30 cessna-172 冒烟
- Epic #3：保持 open（按 design §5：epic 在方向层推送后关闭）。

## 7. 实测偏差（待需求会话确认——完成报告不代做决策）

| # | 偏差 | 处理 |
|---|---|---|
| 1 | spec ⑥/③ 判例「G4 默认 config==98」为 round 假设；上游 /quality 为 floor → 同情形 97 | 实现取上游一致 floor（保「本地分==服务端分」对全部分数成立），断言 97；待需求会话确认 spec 判例 |
| 2 | spec ⑥ 未列 G5（"is unlatched"）触发 passive_voice（与 G4 同为 be+过去分词，默认 config 97） | 按规则表语义实现并断言，注明 |
| 3 | spec ⑥ 金样例表含 type 列（G1 non_functional_performance / G5 safety 等）与 ②「默认 functional」的口径 | 冒烟脚本已按表传参并断言；首轮 live 运行按默认 functional 落库（记录已注明口径待确认） |
| 4 | 服务账号 role：D7「contributor」→ P2 实测 maintainer（edit 层最小角色） | 沿用 P2 结论（design 实现注记已回写）；README 同步修正 |

## 8. 后续演进提示

- P5 agent loop：lint 循环是纯函数接口（文本进/文本出），LLM 改写替换确定性修正表无需改工具契约；
  draft_requirement 的"确定性修正"仍是唯一非 LLM 修复路径。
- P4 复合技能②并入 domain「复合技能」。
- 冒烟重跑需清理 SMOKE-P3-001..003（ADMIN 删除族不在 P3 范围）。
