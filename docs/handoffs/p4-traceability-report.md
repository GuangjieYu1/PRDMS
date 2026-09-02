# 交接文本：P4 追踪/覆盖缺口报告（需求会话 → 开发会话）

> 派发时间：2026-09-02。开发会话以此文件为入口。

## 索引

- **Epic**：[#4](https://github.com/GuangjieYu1/PRDMS/issues/4) [P4] 复合技能②：追踪/覆盖缺口报告
- **Spec**：`docs/specs/p4-traceability-report.md`
- **Design doc**：`docs/reqmesh-harness-design.md`（§3 D8 旗舰用例②、§5 流程、§7 验证基线）
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md) · [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)（P4 无动词扩展；开发会话仅补一行实现注记：新工具并入 domain=复合技能 + 不扩展 report 枚举的理由）
- **P1–P3 参考（勿重做）**：`docs/specs/p1-tool-layer-mvp.md` · `docs/specs/p2-write-path.md` · `docs/specs/p3-nl-requirements.md` · `docs/handoffs/p1-tool-layer-mvp.md` · `docs/handoffs/p2-write-path.md` · `docs/handoffs/p3-nl-requirements.md` · `reqmesh-harness/` 现有代码

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#31](https://github.com/GuangjieYu1/PRDMS/issues/31) | report 聚合内核：六源数据聚合 + 缺口维度提取 + 去重合并 + 排序 + report schema 组装 | — |
| [#32](https://github.com/GuangjieYu1/PRDMS/issues/32) | 建议修复动作模板表与渲染：12 类缺口维度 → 规则驱动建议（仅建议，不执行） | — |
| [#33](https://github.com/GuangjieYu1/PRDMS/issues/33) | get_traceability_gap_report READ 工具：注册表 40 行 + OpenAI 导出对账 + ADR-0002 实现注记 | #31, #32 |
| [#34](https://github.com/GuangjieYu1/PRDMS/issues/34) | 离线测试套件：聚合内核/golden 报告/模板/过滤/只读断言/导出对账（P1–P3 不回退） | #31, #32, #33 |
| [#35](https://github.com/GuangjieYu1/PRDMS/issues/35) | cessna-172 冒烟：金样例断言 + 零副作用 + 基线快照记录落盘 | #33, #34 |

frontier 首步：#31、#32（可并行）；随后 #33；再后 #34；#35 收尾（网络冒烟）。**P4 无 B 段**（全 READ，无真实写闭环，无残渣）。

## 本会话决策摘要（开发会话必须遵守）

1. **工具命名与形态（开放问题①）**：单个 READ 工具 `get_traceability_gap_report(project_id, dimensions?)`——verb `get`（词汇表内，**零动词扩展**），实体对齐 get_project_report 的「报告作实体后缀」惯例；注册表 level=READ（readOnlyHint=True）、domain=**复合技能**（P3 预告「P4 复合技能②并入」兑现）、title=追踪/覆盖缺口报告、description 以 `READ-ONLY` 开头中文。编排全部在工具处理器内部同步完成（P5 前无 agent loop，D5）；**不拆分**（READ 层无审批门/状态机复杂度，拆分只把编排责任推回调用方）。备选 `report_traceability_gaps`（新增 READ 动词 report，与 get_project_report 双动词）与 `get_gap_report`（与 get_gap_analysis 混淆）均拒绝。
2. **报告结构与格式（②）**：结构化 JSON 单一序列化（`summary`/`chapters`/`gaps`/`meta` 四段），不输出 Markdown/HTML 二次格式（模型消费 + golden 可逐路径断言；渲染是消费者便宜操作，P6 属交付层）。浅层/深层口径严格按上游语义（浅层=声明 needs 全部有任一覆盖；深层=浅层且 child_requirement 分解链递归成立；broken_chain=浅层且非深层）——不发明第三口径。关键排序规则：主清单三重键（最高严重度降序 → 维度数降序 → id 升序），条目内维度（严重度降序, type 升序）、actions（严重度降序, action 文本升序）；chapters 按 id 升序（源响应无顺序保证）。
3. **建议修复动作生成（③）**：规则驱动——12 类缺口维度 → 模板表（severity/action 中文/tool_hint），每条缺口都带建议（epic #4 验收明文要求）。**纯建议硬约束**：报告绝不执行任何修复（不调用写工具/不触碰写端点），tool_hint 仅引用既有写工具名（review_item/update_requirement/set_relations/set_allocation/create_verification_case），调用方自行决定是否经审批门执行。
4. **与 get_project_report 的边界（④）**：**独立工具，不扩展 report 枚举**。get_project_report = 6 个 reqmesh 服务端计算型报告端点的 1:1 路由 + envelope 透传；P4 报告 = 客户端多源聚合（6 端点），无对应单一端点 → 放入枚举无路由可映射，破坏 1:1 契约与透传契约。**注意**：P1 预告的《reference freshness/conflicts/backlog/pugh/risk-bingo》五个服务端端点**全部存在于** 0.5.0 快照（本会话核实，spec 初版曾误判不存在已修正）——它们是未来 phase 的合法枚举扩展对象，P4 不消费（分析域）。`_REPORT_ROUTES`/get_project_report/components_report.py **零改动**。
5. **过滤维度（⑤）**：默认全量；仅 `dimensions: list[Literal[12 类维度]] | None` 白名单（作用于 chapters/gaps，**summary 保持全量**）。不提供组件/基线/需求组/类型/状态过滤（六源无服务端过滤参数——vendored openapi 核实；客户端 slice 属消费者职责；基线维度缺口数据六源不存在）。不提供分页（聚合单文档，cessna-172 = 61 条需求）。
6. **验收金样例（⑥）**：**双轨基线**（事实核实 3：epic 预估基线 80%/44/38/gap 36/traces 8 = P1 期 fixture 快照，P1 冒烟记录与 P2/P3 真实写后均已漂移——本会话 2026-09-02T05:38Z live 实测：total=61、coverage 59-48-42-81-71、gap 40、traces 9、suspect 2、unreviewed 41=40+1 stale、allocation 61 行 7 未分配、is_repo=false）+ 跨源自洽断言（报告数字 == 同次运行的源工具数字，即与 reqmesh 前端分析一致，恒真抗漂移）。断言 G1–G6（关键数字一致 / 缺口清单完整 / 建议模板命中 / 排序规则 / 零副作用 / 确定性），**≥3 条要求超额满足**；P4 冒烟无 B 段。

## 本会话核实的事实（spec「事实核实」节，开发会话以此为准，勿重新猜测）

1. 六源返回结构（fixture + live 实测；vendored openapi 响应 schema 全为空 `{}`，形状以 fixture/实测为准）：coverage（total/shallow_covered/deep_covered/coverage_pct/deep_pct/items[]，条目含 needs/covered_types/uncovered_types/unwanted_coverage/shallow/deep/broken_chain；needs 词表 design|verification_case|analysis_case|child_requirement|reference）；gap-analysis（{total, gaps, items[]}，issues 词表 no_description|no_rationale|no_source|unlinked）；traces（{links:[{source,target,type}]}）；suspect-links（{count, links:[{source, source_collection, target, type, stored_fingerprint, current_fingerprint, reason}]}）；unreviewed（{items:[{id, name, reviewed, current_fingerprint}]}，reviewed=null 从未评审 / 指纹失配=评审过期）；allocation-matrix（rows[] 含 req_id/req_name/req_type/row_id/row_name/allocated_to/cells{}）。
2. 上游 coverage 语义（reqmesh/backend/app/services/tracing.py 源码核实）：shallow=needs 全有任一覆盖；deep=shallow 且 child_requirement 覆盖来源递归 deep；broken_chain=shallow∧¬deep；unwanted_coverage=covered_types−needs；normative=false 跳过（cessna-172：AVNC0010/OVERVIEW01 → coverage.total=59 < 61）。
3. 上游 gap issues 语义（api/analysis_routes.py）：no_description=描述空（cessna-172 零命中）、no_rationale=理由空、no_source=来源空、unlinked=无 relations。
4. cessna-172 基线快照（2026-09-02T05:38Z，live 只读探针）：见决策摘要 6；重要点检样本：SMOKE-P2-001（评审过期 + 2 条 suspect 链接：组件 satisfies + 评论 comments on，均因评审后被改）、AFRM0000（coverage 缺 design 覆盖 = allocation 未分配，同根并存）、未分配 7 条（AFRM0000/AVNC0006/AVNC0010/OVERVIEW01/SMOKE-P3-001..003）。
5. `git/log` → is_repo=false（P2/P3 实测偏差同款；冒烟 git 断言条件化，本会话复测确认）。
6. git 端点实测：`/git/log` 对已认证用户可读（返回 is_repo=false）；`/git/status` 需 maintainer（contributor 403）——冒烟脚本判断 is_repo 只用 git/log，**不得调用 git/status**（个人账号 yugj/contributor 会 403）。

## P1–P3 复用点（勿重做，勿破坏）

- `tools/groups/tracking.py`：get_coverage/get_gap_analysis/get_traces/get_suspect_links/get_allocation_matrix 处理器——报告内核**直接复用同名处理器**（经 read_json 只读），不重复实现路由。
- `tools/groups/requirements.py`：get_unreviewed_requirements 同款复用。
- `tools/registry.py`：build_registry() 加 1 行（domain=复合技能、level=READ）；ToolSpec/annotations_for（READ → readOnlyHint=True 已有）零改动。
- `tools/export.py`/`server.py`：双 transport 与 OpenAI 导出同源，40 工具对账（P1/P2 测试模式）；golden openai_export.json 同步更新。
- `tests/mapping.py`：增 1 行 ToolMap（project_id*、dimensions 可选；Case 以六源 fixture 为 routes）。
- `tests/fixtures/http/`：六源 fixture 既有（coverage/gap_analysis/traces/suspect_links/unreviewed/allocation_matrix），**勿改**；新增仅限 P4 需要的新样本（golden 报告期望 report_golden.json、过滤期望）。
- P3 无落库依赖：P4 全 READ，不碰 `_write_common.py`/审批门/审计/写客户端——**零修改**。
- `config.py` Settings：无新增（无新环境变量）。
- 冒烟模式沿用 smoke_p1/p2/p3.py（network-tagged、记录落盘 docs/smoke/、凭据不落盘、git 条件断言）。
- .env 已有凭据（REQMESH_USERNAME/PASSWORD），个人账号 yugj/contributor 可覆盖全部 P4 只读端点（require_view 层）；服务账号无关。

## 验收标准（epic → spec → tickets）

- 工具：MCP 双 transport 列出可调、schema 与契约一致、注册表 40 行、OpenAI 导出 1:1 对账（#33）
- 聚合：summary 关键数字 == 同次运行六源返回值；六源外零请求（#31、#34）
- 缺口：12 类维度提取 + 证据齐全；master gaps id 集合 == 六源缺口 id 并集（#31、#34）
- 模板：12 行模板表逐行命中；tool_hint ⊆ 既有写工具名（#32、#34）
- 排序：三重键确定性（#31、#34）
- 只读：调用期间 HTTP 方法 ⊆ {GET}；不产生审计行（#33、#34）
- 过滤：dimensions 白名单作用于 chapters/gaps、summary 全量（#31、#34）
- 冒烟：G1–G6 全部通过；记录落盘 `docs/smoke/P4-cessna-172.md`（#35）
- 离线测试全绿；P1–P3 既有测试不回退（现 329+ passed）（#34）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。

## 硬约束

- **本地提交，禁止 git push**（推送是方向层唯一职责，design §5）。
- 术语遵循 `CONTEXT.md`（工具/权限层级/审批门/审计/工作会话；「session」只指运行时会话）；与 ADR 冲突须显式指出（本会话：与 ADR-0002 无冲突——无动词扩展、无权限前缀、domain 复合技能为兑现 P3 预告；report 枚举不扩展为对 P1 资产的零改动边界而非破坏）。
- 不动 `reqmesh/` 目录；不动已关闭的 P1/P2/P3 资产（tracking.py/requirements.py/components_report.py/既有注册行/skills.py/guardrails/client 零修改；仅 registry 加 1 行 + 新增 report/ 包与 reporting.py）。
- 全 READ 承诺：`get_traceability_gap_report` 不得调用任何写端点（P2 工具与 reqmesh 写 API 一律不碰）；冒烟断言零副作用（total 不变、HTTP 方法 ⊆ {GET}、git 条件断言）。
- 许可证边界：聚合逻辑独立编写（只消费公开 REST 响应形状与实测 fixture），不复制 reqmesh GPL 源码（spec 事实 5）。

## 需求会话回流确认（2026-09-02，开发会话完成报告核实后）

完成报告已实测核验（本会话独立复核，非仅读报告）：

1. **git**：本地 main 领先 origin/main **2 commits**（5800667→18e25c3，未 push）；P1–P3 核心资产零修改（writes.py / _write_common.py / guardrails/ / client/ / server.py / export.py / tracking.py / requirements.py / components_report.py / skills.py 无 diff；registry 仅加 1 行 reporting 注册；tests 改动仅工具数 39→40 计数与新增文件）；reqmesh/ 上游目录未动。
2. **测试**：离线复跑 **396 passed / 3 skipped / 2 deselected**（P3 基线 329+ 零回退；新增 test_report_kernel 23 / test_report_templates 11 / test_report_tool 10 用例函数 + 既有套件计数更新）。
3. **冒烟**：docs/smoke/P4-cessna-172.md 完整（基线快照 + G1–G6 + 零副作用声明）；**本会话另做独立 live 复验**（只读探针）：G1 跨源自洽 + 绝对数基线（与 2026-09-02T05:38Z 快照一致未降级）、G2 并集 57==57 无丢失/编造 + SMOKE-P2-001/AFRM0000 点检、G3 全部条目带建议且 hints ⊆ 写工具名、G4 逐对规范比较通过（首版探针检查键方向写反属检查失误，修正后确认实现无偏差）、G6 确定性、G5 total 61→61。
4. **issues**：#31–#35 全部 CLOSED（回流结论评论齐全）；epic #4 OPEN。
5. **3 项待确认偏差全部确认接受**并回写 spec「实测偏差与决策」节 + smoke 记录确认节：
   - ① `coverage.uncovered:<need>` 类型折叠（need 并入类型值 → 12 值 1:1 封闭 Literal，解决初版 12 行模板表/11 唯一值的不自洽）。
   - ② 离线 golden 用 P1 期 fixture 数字（本会话逐项对账可推导）/ live 冒烟用 2026-09-02 基线——双轨拆分，两轨不互引绝对数（Testing Decisions 已注明）。
   - ③ 非 design/vc need 防御性回退（design 变体 + evidence.need_type 保留；零触发；专属模板行留后续 phase）。
6. 全 READ 承诺核验：reporting.py 仅 import report 内核与 tracking/requirements READ 处理器，无任何写动词/写层 import（结构上不存在写路径）；审计 0 行、无 B 段、无残渣确认。

确认摘要记 #31/#32/#34 comment。方向层可执行：推送 origin（5800667..HEAD）→ 关闭 epic #4。
