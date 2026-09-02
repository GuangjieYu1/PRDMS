# P4 开发会话完成报告：复合技能② 追踪/覆盖缺口报告（全 READ 层）

> 产出时间：2026-09-02（开发会话收口）；依据 design §5 流程：本地提交，**未推送**（推送是方向层唯一职责）。

## 1. 入口与范围

- Epic：#4；Tickets：#31–#35（全部关闭，见 §6）
- Spec：docs/specs/p4-traceability-report.md；交接：docs/handoffs/p4-traceability-report.md
- 硬约束核对：未 push（origin/main 仍停在 5800667；本地 main 本地新提交见 §2）；
  **P1–P3 资产零修改**（tracking.py/requirements.py/components_report.py/_REPORT_ROUTES/
  get_project_report/skills.py/guardrails*/client*/writes.py/_write_common.py/server.py/
  cli.py/config.py 均未动；仅 registry 加 1 行 + tests 计数/文档同步）；未动 reqmesh/ 目录；
  六源 fixture 未改（新增仅 report_golden.json）；许可证边界按「独立编写」执行（只消费
  公开 REST 响应形状，不复制 reqmesh GPL 源码）；全 READ 承诺（冒烟实测 0 审计行、
  HTTP 方法 ⊆ {GET} 除登录 POST、无 B 段无残渣）。

## 2. Git 历史（本地 main，未推送）

- 5800667 docs(P4): 需求会话产出 — spec、开放问题①–⑥决策、tickets #31–#35 与交接文本（方向层已提交）
- （本会话新提交：见提交时 message——feat(P4)+fix 回流 + docs 完成报告，具体以 git log 为准）

## 3. 交付物

| 产物 | 路径 |
|---|---|
| 12 类缺口维度模板表（severity/action/tool_hint，纯建议） | reqmesh-harness/src/reqmesh_harness/report/templates.py |
| 聚合内核（六源→维度提取→去重合并→排序→schema；纯函数零网络，fail-fast） | reqmesh-harness/src/reqmesh_harness/report/aggregate.py |
| 复合工具 | reqmesh-harness/src/reqmesh_harness/tools/groups/reporting.py（6 GET 一次完成） |
| 注册表/导出 | 39 → 40 工具（27 READ + 7 DRAFT + 6 MUTATE）；OpenAI 导出 golden 同步 |
| 离线测试 | tests/test_report_templates.py + test_report_kernel.py + test_report_tool.py（64 用例）+ mapping/既有测试 39→40 更新 + report_golden.json |
| 冒烟 | scripts/smoke_p4.py；记录 docs/smoke/P4-cessna-172.md（G1–G6 全通过，复跑幂等） |
| ADR-0002 回写 | 复合技能②并入 + 不扩展 report 枚举的理由（实现注记） |
| README | P4 范围 + 目录表 + 工具计数（27 READ + 13 写） |

## 4. 测试结果

- 全量离线：**396 passed / 3 skipped / 2 deselected（network 冒烟）**；P1–P3 既有零回退
  （基线 P3 329+）；新增 66 用例（64 新套件 + 2 回流回归）。
- 测试真实性（测试子代理独立核验）：9 项验收全实测通过；对抗脚本 33 项边界断言
  （12 类维度全提取含零命中语料、AFRM0000 多源并集、并集 53==53、三重键排序、
  fail-fast 500/404、确定性、输入不修改）；只读实证恰好 6 个 GET + ReadOnlyClient
  结构回归；schema 非法值拒绝。无恒真断言。
- Live 冒烟（172.16.100.2，reqmesh-harness/maintainer）：G1 跨源自洽（summary 逐项 ==
  六源工具返回值）+ 绝对数基线 == 2026-09-02T05:38Z 快照（61/59-48-42-81-71/40/9/2/41/7，
  **未触发降级**）；G2 master 57 条 == 并集 + SMOKE-P2-001/AFRM0000 点检；G3 模板命中 +
  抽样；G4 排序；G5 零副作用（total 61→61、0 审计行、非 GET 仅登录 POST、git 0→0、
  is_repo=false 条件降级）；G6 确定性；维度过滤（summary 全量）额外验证。

## 5. 回流记录

- 第 1 轮（审核子代理 CONDITIONAL PASS + 测试子代理 PASS）：
  - **M1（medium，已修复）**：filter_gaps 过滤后未按重算键重排 → 违反三重键排序契约
    （AC#6）；修复 = 过滤后重排（aggregate.py filter_gaps）+ 回归测试
    test_filtered_gaps_still_triple_key_sorted（实证场景点检）。
  - L1（low，已修复）：dimensions=[] 语义不一致 → 归一为 None（未提供 = 全部），
    meta.filters 记录 null + 回归测试。
  - L2（low，保留，未触发）：非 design/verification_case 的 uncovered need 防御性回退
    设计变体（fixture/live 仅用两种 need；evidence 保留实际 need_type，已注释）。
  - N1（待需求会话裁决）：coverage.uncovered:<need> 类型折叠（:design / :verification_case）
    ——为满足「Literal[12 类维度]」12 值逐值对应；审核裁定可接受（已声明、待确认），
    若批准应回写 spec 契约 Literal 与模板表类型列。
  - N2（待注明）：离线 golden 用 P1 期 fixture（55/44-38-80-69/36/8/0/37/57），
    live 基线（61/…）与 SMOKE-P2-001 点检只落在 live 冒烟记录——双轨拆分，建议
    需求会话在 spec「Testing Decisions」注明。
- 第 2 轮（审核核验）：M1/L1 按清单落实，全量 396 passed 无回退，**通过**；无新 medium+
  发现。各轮结论已记对应 ticket comment（#31–#35）。

## 6. Issue 状态

- ✅ #31 聚合内核 · ✅ #32 模板表与渲染 · ✅ #33 READ 工具（40 行 + 导出对账 + ADR 注记）
- ✅ #34 离线测试套件 · ✅ #35 cessna-172 冒烟
- Epic #4：保持 open（按 design §5：epic 在方向层推送后关闭）。

## 7. 待需求会话确认

| # | 事项 | 建议 |
|---|---|---|
| 1 | coverage.uncovered 的 need 并入类型值（coverage.uncovered:design / :verification_case） | 确认或回退；若确认，回写 spec 工具契约 dimensions Literal 与模板表类型列 |
| 2 | 离线 golden 用 P1 期 fixture（live 基线/点检仅冒烟记录） | spec「Testing Decisions」注明双轨拆分 |
| 3 | 非 design/vc 的 uncovered need 防御性回退（现阶段 zero-trigger） | 保持（含注记）或后续 phase 给专属模板行 |

## 8. 后续演进提示

- P5 agent loop：report 内核已是纯函数接口（六源 dict 进/报告 dict 出），LLM 编排或
  建议改写无需改契约；tool_hint 只指路，写工具经审批门执行仍是调用方职责。
- P6 交付层：报告 Markdown/渲染输出属消费者便宜操作（spec Out of Scope）。
- 冒烟可随时重跑（全 READ 无残渣，无需清理）；基线漂移时 G1 绝对数自动降级为历史基线。
