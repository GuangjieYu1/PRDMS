# P4 spec：追踪/覆盖缺口报告（复合技能②，全 READ 层）

> 状态：需求会话产出，待开发会话实施。
> 入口：design [docs/reqmesh-harness-design.md](../reqmesh-harness-design.md)（§3 D8 旗舰用例②、§5 流程、§7 验证基线） · epic [#4](https://github.com/GuangjieYu1/PRDMS/issues/4) · 术语 [CONTEXT.md](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md) · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md) · P1 spec [docs/specs/p1-tool-layer-mvp.md](p1-tool-layer-mvp.md) · P2 spec [docs/specs/p2-write-path.md](p2-write-path.md) · P3 spec [docs/specs/p3-nl-requirements.md](p3-nl-requirements.md)
> 交接：见 [docs/handoffs/p4-traceability-report.md](../handoffs/p4-traceability-report.md)

## Problem Statement

design D8 的旗舰用例②要求「追踪/覆盖缺口报告」：调用方指定项目 → 聚合 coverage / gap-analysis / traces / suspect-links / unreviewed / allocation 多源数据 → 输出可读的追踪与覆盖缺口报告，每条缺口带建议修复动作。目前该能力是**多步手工过程**：模型要自己调用 5 个追踪域工具 + `get_unreviewed_requirements` 共 6 次、理解 coverage 的 shallow/deep 口径与 gap 条目的 issues 词表、在脑中做跨源去重（同一需求的缺口散落在 coverage/gap/unreviewed/allocation 多个响应里）、再自行拟定修复建议——6 次调用与跨源拼接没有收敛为一次语义动作。P5（内置 agent loop）尚未交付，因此**聚合逻辑必须在单个工具处理器内部同步完成**（D5，与 P3 draft_requirement 同款约束）。

本会话核实的关键事实（见「事实核实」节）：六源的返回结构全部可查（fixture + live 实测）；P1 的 `get_project_report` 是 reqmesh **服务端计算型报告**的 1:1 路由透传，P4 的报告是**客户端多源聚合**——两种计算模型，必须独立成工具而非扩展 report 枚举；cessna-172 现状与 epic 预估基线已有漂移（P2/P3 真实写后），验收须以本会话实测基线快照 + 跨源自洽断言双轨执行。

## 事实核实（本会话，证据留档，不拍脑袋）

1. **`get_project_report` 边界（P1 资产，开发会话零改动）**：P1 映射表 #25 把 6 个 reqmesh **服务端计算型报告端点**合并为一个工具 + `report` 枚举（components_report.py 的 `_REPORT_ROUTES`：quality→`/quality`、compliance→`/compliance`、metrics→`/metrics`、evaluation→`/evaluation`、validation→`/validate`、workflow→`/workflow`），返回 = 原始 JSON envelope **透传**（P1 spec「工具层返回原始 JSON 透传」）。**不含**追踪/覆盖缺口报告——reqmesh 没有任何一个端点返回「多源聚合缺口报告」，`/coverage`、`/gap-analysis`、`/traces`、`/suspect-links`、`/unreviewed`、`/allocation-matrix` 是六个互相独立的端点。P4 报告的计算位置在**客户端**（harness），与枚举成员「1:1 对应一个服务端端点」的契约根本不同 → 独立工具（开放问题④），`_REPORT_ROUTES`/`get_project_report` 零改动。
2. **六源返回结构**（vendored openapi 快照的响应 schema 全为空 `{}`——P1 spec 事实；形状以 tests/fixtures/http/ 的实测抓取样本 + 本会话 live 探针为准）：
   - `get_coverage` → `{total, shallow_covered, deep_covered, coverage_pct, deep_pct, items:[{id, name, needs[], covered_types[], uncovered_types[], unwanted_coverage[], shallow, deep, broken_chain}]}`。`needs`/`covered_types` 词表（上游 backend/app/services/tracing.py `NEEDS_VOCABULARY`）：`design`（组件 satisfies）、`verification_case`（验证用例 verify）、`analysis_case`（分析 scope）、`child_requirement`（分解）、`reference`（外部引用）；cessna-172 实测只使用 design/verification_case 两种 needs。
   - **shallow/deep 口径（上游源码核实，tracing.py）**：`shallow` = 全部声明的 needs 都有**任一**覆盖（uncovered_types 为空）；`deep` = shallow 且每个 `child_requirement` 覆盖来源自身也 deep（递归分解链）；`broken_chain = shallow and not deep`；`unwanted_coverage` = covered_types − needs（多余覆盖）；`normative=false` 的需求跳过分析（cessna-172 实测 AVNC0010、OVERVIEW01 两条 → coverage.total=59 < 需求总数 61）。
   - `get_gap_analysis` → `{total, gaps, items:[{id, name, issues[]}]}`；`items` 只含带问题的条目（len == gaps），`total` = 全部需求数。issues 词表（上游 api/analysis_routes.py `gap_analysis`）：`no_description`（描述空）、`no_rationale`（理由空）、`no_source`（来源空）、`unlinked`（无任何 relations）；cessna-172 实测 no_description 零命中，其余三类命中。
   - `get_traces` → `{links:[{source, target, type}]}`；type 为关系标签（cessna-172 实测全为 `refines`；suspect-links 中另有 `satisfies`/`comments on`）。
   - `get_suspect_links` → `{count, links:[{source, source_collection, target, type, stored_fingerprint, current_fingerprint, reason}]}`——编辑后指纹失配的链接；`reason` 为上游人话描述（如 "Satisfies a requirement that changed since it was reviewed"）。
   - `get_unreviewed_requirements` → `{items:[{id, name, reviewed, current_fingerprint}], count}`；`reviewed=null` = 从未评审；`reviewed=<指纹>` 且 ≠ `current_fingerprint` = **评审过期**（内容变更后指纹失配——两种子情形都进未评审清单，本会话实测确认）。
   - `get_allocation_matrix` → `{axis, verb, column_label, row_kind, rows:[{row_id, row_name, row_status, row_type, cells{组件id:bool}, req_id, req_name, req_status, req_type, allocated_to}]}`；`allocated_to` 为空串/null = 未分配组件（分配缺口）。
3. **cessna-172 现状基线（2026-09-02T05:38Z 本会话 live 探针实测，只读 GET；与 epic 预估基线不一致——见下）**：
   - `list_requirements.total` = **61**（P2 冒烟 58 + P3 B 段 3 条残渣）；components total=81；`/quality` average=90。
   - coverage = `{total: 59, shallow_covered: 48, deep_covered: 42, coverage_pct: 81, deep_pct: 71}`；broken_chain=6、带 uncovered_types 的条目=11、带 unwanted_coverage 的条目=31。
   - gap-analysis = `{total: 61, gaps: 40}`；分布 unlinked=20 / no_rationale=15 / no_source=29（单条可多 issue）。
   - traces = 9 条链接（8 条 ACFT0000→子域 refines + 1 条 SMOKE-P2-001→SMOKE-P2-C01）；suspect-links = 2 条（SMOKE-P2-C01 satisfies SMOKE-P2-001、COMMENT-1799C5D3 comments on SMOKE-P2-001，均因 SMOKE-P2-001 评审后被修改）。
   - unreviewed = 41 条（40 条从未评审 + 1 条评审过期 = SMOKE-P2-001）；allocation = 61 行，未分配 7 条（AFRM0000、AVNC0006、AVNC0010、OVERVIEW01、SMOKE-P3-001/002/003）。
   - `git/log` → `is_repo: false`（P2/P3 实测偏差同款，冒烟 git 断言条件化）。
   - **与 epic 预估基线（coverage 80%、shallow 44/deep 38、gap 36、traces 8）的差异说明**：预估数字等于 P1 期 fixture 快照（tests/fixtures/http/coverage.json total=55、gap_analysis.json gaps=36、traces.json 8 条），P1 冒烟记录（total=56/shallow 45/deep 39/gap 37/traces 9）与 P2/P3 真实写后均已漂移。验收基线采用**双轨**（开放问题⑥）：① 跨源自洽断言（报告数字 == 同次运行的源工具数字——reqmesh 前端分析消费同一批端点，数字一致即与前端分析一致，恒真且抗漂移）；② 本会话实测快照作绝对数断言（2026-09-02T05:38Z 上表），若实例在冒烟前再漂移，按 P1 惯例在冒烟记录注明「快照仅作历史基线」，绝对数断言降级、自洽断言保留。
4. **可覆盖的缺口维度清单（本会话从六源结构推导定案，12 类）**：见「缺口维度清单与建议模板表」。严重度四级（high > medium > low > info）由规则表固定，不进 reqmesh 数据。
5. **许可证边界**：P4 的聚合逻辑为独立编写（只消费公开 REST 响应形状，不复制 reqmesh 源码）；上游 coverage 语义（shallow/deep/broken_chain）以本 spec 事实 2 的文字表述为准，实现不 import reqmesh 代码。响应形状无 GPL 代码成分（fixture 为实测数据样本，P1 惯例）。

## Solution

在 P3 的 reqmesh-harness 上新增一块（全 READ 层，零写操作）：

1. **report 聚合内核 `src/reqmesh_harness/report/`**（新包，模式对齐 P3 lint/：纯函数、无网络副作用）：六源聚合 → 12 类缺口维度提取 → 按实体 id 去重合并 → 排序 → 组装 report schema。fail-fast：任一源失败整体报错，不产部分报告（部分缺口报告会误导，且各源都是廉价幂等 GET，重试即可）。
2. **`get_traceability_gap_report` 单个 READ 工具**（新文件 `tools/groups/reporting.py`，不动 P3 skills.py）：一次调用内部只发 6 个 GET（coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix），输出结构化报告文档，每条缺口带**规则驱动的建议修复动作（仅建议，不执行）**。
3. **建议模板表 `src/reqmesh_harness/report/templates.py`**：12 类缺口维度 → {severity, action（中文）, tool_hint（引用的既有写工具名，不调用）}。

注册表 39 → **40 行**（25 READ + 12 写 + 2 P3 + 1 P4）；MCP 注册与 OpenAI 导出同源对账（P1/P2/P3 模式不变）。冒烟对 cessna-172 跑金样例断言 + 零副作用断言，记录落盘。**P4 无 B 段**（全 READ，无任何写操作；不涉审批门/dry_run/审计写行）。

## User Stories

1. As an LLM agent, I want a single `get_traceability_gap_report` call per project, so that I get a complete traceability & coverage gap report instead of assembling six tool calls myself.
2. As an LLM agent, I want the report's key numbers to equal the raw analyses (coverage/gap/traces/suspect/unreviewed/allocation) in the same run, so that the report never disagrees with the reqmesh frontend's analyses.
3. As an LLM agent, I want a merged per-entity gap list (multi-source dimensions unioned under one id), so that I see one entry per requirement instead of the same gap scattered across four responses.
4. As an LLM agent, I want each gap entry to carry a rule-driven suggested fix that names the existing write tool which could apply it, so that I can decide the next action without inventing tool usage from scratch.
5. As an LLM agent, I want deterministic severity-ordered output, so that repeated calls and tests are byte-comparable.
6. As an LLM agent, I want an optional dimension whitelist filter, so that I can focus a report on e.g. only traceability-class gaps.
7. As a developer, I want the tool to be read-only by construction (GET-only session, structural absence of write paths), so that P4 can never mutate reqmesh state.
8. As an operator, I want a repeatable smoke run against cessna-172 that asserts key numbers, gap-list completeness, template hits, and zero side effects, with the record on disk.

## Implementation Decisions

### 开放问题①：工具命名与形态（已决策）

**决策：单个 READ 工具 `get_traceability_gap_report`（verb `get`，实体 `traceability_gap_report`）；编排全部在工具处理器内部同步完成（P5 前无 agent 运行时，D5）；不拆分。**

- 命名：verb_entity（ADR-0002），`get` 在 READ 词汇表内（list/get/search）——**零动词扩展，ADR-0002 无需词汇表回写**；实体 `traceability_gap_report` 对齐既有 `get_project_report` 的「报告作实体后缀」惯例（备选 `report_traceability_gaps` 需新增 READ 动词 `report`，与 get_project_report 形成同概念双动词，拒绝；`get_gap_report` 与 get_gap_analysis 语义混淆，拒绝）。
- 注册表：level=READ（readOnlyHint=True）、domain=**复合技能**（P3 已预告「P4 复合技能②并入」——tools/__init__.py 注释与 ADR-0002 P3 实现注记均在案）、title=追踪/覆盖缺口报告；description 以 `READ-ONLY` 开头（P1 惯例）中文书写：说明六源、全 READ、fail-fast、建议仅参考不执行。
- **单工具 vs 拆分（边界理由）**：P5 前无 agent loop 承接多步编排（本会话硬约束）；READ 层报告无审批门/状态机复杂度，拆分只会把「6 次调用 + 跨源去重 + 排序 + 建议生成」的编排责任推回调用方。拆分方案仅在未来需要「报告缓存/分块流式/增量订阅」时才值得重议（属 P5/P6，不在本会话）。
- 与 ADR 的关系（显式声明）：ADR-0001 无冲突（MCP 为核 + OpenAI 导出同源）；ADR-0002 无动词扩展、无权限前缀（审批门依然从注册表 level 映射，绝不解析名字）；domain=复合技能是兑现 P3 预告而非新分组。开发会话完成后按惯例补 ADR-0002 一行实现注记（新工具并入 domain=复合技能 + 不扩展 report 枚举的理由），非词汇表变更。

### 开放问题②：报告结构与格式（已决策）

**决策：结构化 JSON 单一序列化（summary/chapters/gaps/meta 四段），不输出 Markdown/HTML 二次格式。**

- 理由：① 模型消费 JSON 最优（本工具的第一消费者是 LLM）；② 单一序列化使 golden 测试可逐路径断言，无格式漂移；③ Markdown/表格渲染是消费者的便宜操作（模型可自行渲染），维护两份序列化违背「注册表是唯一事实源」精神。Markdown/HTML 导出列入 Out of Scope（P6 交付层）。
- **浅层 vs 深层覆盖口径（与 reqmesh 前端一致，事实 2）**：report 同时呈现 `shallow_covered`/`deep_covered`/`coverage_pct`/`deep_pct` 与逐条 `shallow`/`deep`/`broken_chain`；浅层=声明 needs 全部有任一覆盖，深层=浅层且分解链递归成立。报告不发明第三个口径。
- **章节划分**（report schema 见「工具契约」）：`summary`（全量关键计数，**不受过滤影响**——可比口径）、`chapters`（六源各自章节：faithful 源数据 + 维度注解，仅含带维度注解的条目——缺口维度 + info 级多余覆盖标注；traces 章为链接清单作上下文，非缺口）、`gaps`（**主清单**：按实体 id 去重合并多源维度 + evidence + actions）、`meta`（工具名/版本/生效过滤）。
- **缺口条目排序规则（确定性，三重键）**：主清单 `gaps[]` 按 ① 条目内最高严重度（high > medium > low > info）降序 → ② 维度数降序 → ③ 实体 id 升序（ASCII）；条目内 `dimensions[]` 按（严重度降序, type 升序），`actions[]` 按（严重度降序, action 文本升序）。chapters 内 items 按 id 升序（源响应无顺序保证，必须显式排序）。

### 开放问题③：建议修复动作生成（已决策）

**决策：规则驱动生成——12 类缺口维度 → 建议模板表（见下），每条缺口都带建议；不采用「只列事实不生成建议」。**

- 理由：epic #4 验收标准明文「报告含建议修复动作」；模板是确定性的（dimension type → 固定中文 action + tool_hint），无 LLM、无编造风险。
- **纯建议边界（硬约束）**：报告绝不执行任何修复——不调用任何写工具、不触碰任何写端点（P2 写工具与 reqmesh 写 API 一律不碰）；`tool_hint` 只是引用既有写工具的**名字**（不 import、不调用），供调用方自行决定是否经审批门执行（写操作是 P2/P3 工具的职责，本工具只是指路）。
- 建议按严重度降序渲染进 entry.actions；同一 entry 多维度 → 多条建议。

**缺口维度清单与建议模板表（12 类；severity 与 action/tool_hint 为契约，实现逐行测试）**：

| # | dimension type | severity | action（中文模板，渲染时嵌入实体 id/need 类型等证据） | tool_hint（仅引用，不执行） | 说明 |
|---|---|---|---|---|---|
| 1 | `coverage.uncovered`（need=design） | medium | 为需求分配满足该需求的组件（design 覆盖）：从 list_components 选定组件后 set_allocation(allocated=true)，或让组件 satisfies 该需求 | set_allocation (MUTATE) | 与 allocation.missing 同根；evidence.need_type=design |
| 2 | `coverage.uncovered`（need=verification_case） | high | 为该需求建立验证覆盖：create_verification_case 新建或复用既有验证用例，再经 set_relations / update_requirement(verification_cases) 关联 | create_verification_case (DRAFT) + set_relations (MUTATE) | evidence.need_type=verification_case |
| 3 | `coverage.chain_broken` | high | 修复覆盖链：为需求补充子需求分解（refines/derives）并确保子需求自身 deep 覆盖；或直接补齐顶层缺失的覆盖类型 | update_requirement(relations) / set_relations (MUTATE) | shallow=true 且 deep=false |
| 4 | `coverage.unwanted` | info | 核查多余覆盖来源并清理：移除不需要类型的链接/分配 | set_relations / set_allocation(allocated=false) (MUTATE) | 非缺口，信息级标注；evidence.unwanted_coverage |
| 5 | `content.no_description` | low | 补充需求描述文本 | update_requirement(description=…) (MUTATE) | cessna-172 零命中；词表完整性保留（上游 issues 词表 4 值之一） |
| 6 | `content.no_rationale` | low | 补充理由（why） | update_requirement(rationale=…) (MUTATE) | gap-analysis issues |
| 7 | `content.no_source` | low | 补充来源（出处） | update_requirement(source=…) (MUTATE) | gap-analysis issues |
| 8 | `trace.unlinked` | high | 建立追踪链接：get_traces 读-改-写回放，经 set_relations 追加 refines/derives/verifies 链接 | set_relations (MUTATE) | gap-analysis issues unlinked |
| 9 | `trace.stale` | medium | 链接目标已变更：对目标需求 review_item 重新评审刷新指纹；或经 set_relations 移除并重建该链接 | review_item (DRAFT) / set_relations (MUTATE) | suspect-links；evidence.link_type/from/reason |
| 10 | `review.never` | medium | 提交评审 | review_item (DRAFT) | unreviewed reviewed=null |
| 11 | `review.stale` | medium | 内容变更后重新评审（刷新指纹） | review_item (DRAFT) | unreviewed 指纹失配 |
| 12 | `allocation.missing` | medium | 为需求分配组件：选定满足组件后 set_allocation(allocated=true) | set_allocation (MUTATE) | allocation-matrix allocated_to 为空 |

严重度词表固定为 `high`/`medium`/`low`/`info`（四级，不进 reqmesh 数据）；排序见②。

### 开放问题④：与 get_project_report 的边界（已决策）

**决策：独立工具，不扩展 report 枚举。**

- `get_project_report` 的 `report` 枚举 = reqmesh **服务端计算型报告端点**的 1:1 路由（`_REPORT_ROUTES`），契约是「原始 JSON envelope 透传」（P1 spec）；P4 报告是 **harness 客户端多源聚合**（6 端点 + 去重/排序/建议），两种计算模型混进一个枚举会破坏：① 1:1 路由表与映射测试的可执行性（枚举成员必须对应一个路由）；② envelope 透传契约（聚合产物不是任何端点的响应）。
- **P1 预告的枚举扩展机制仍然有效（本会话核实 vendored openapi）**：《reference freshness / conflicts / backlog / pugh / risk-bingo》五个**服务端**端点全部存在于 0.5.0 快照（`/references/freshness`、`/conflicts`、`/backlog`、`/pugh`、`/risk-bingo`）——将来任一 phase 把它们作为枚举成员加入 `_REPORT_ROUTES` 是合法的非破坏性扩展（P1 预告兑现路径），**但那是服务端报告端点的扩展，不是 P4 的路径**：P4 报告不对应任何单一 reqmesh 端点，放入枚举无路由可映射。枚举 6 值本轮冻结不动；五个预告端点属 P4 Out of Scope（分析域而非追踪/覆盖缺口域）。
- 非破坏性范围：components_report.py / `_REPORT_ROUTES` / `get_project_report` **零改动**；注册表仅加 1 行；export/mapping 增对账行（见「注册表与导出扩展」）。回归测试证明枚举行为不变。

### 开放问题⑤：过滤维度（已决策）

**决策：默认全量；仅提供 `dimensions: list[str] | None` 白名单过滤（12 类维度类型值，Literal 枚举）；不提供组件/基线/需求组/类型/状态过滤。**

- 理由：① 六源端点**均无服务端过滤参数**（vendored openapi 核实：coverage/gap-analysis/traces/suspect-links/unreviewed 无 query 参数，allocation-matrix 仅 axis/rows/search/filter_type）——组件/基线/需求组/类型/状态过滤只能是客户端后过滤，模型拿到全量 JSON 自行 slice 是零成本操作，工具重复实现违背「工具做语义、模型做呈现」的分工；② 基线维度的缺口数据六源均不存在（baselines 端点只返回里程碑清单，与缺口无关联），强行过滤是伪功能；③ `dimensions` 白名单有真实用例（「只看追踪类缺口」「只看未评审」）且实现/测试便宜：过滤作用于 chapters（带缺口条目）与 gaps 主清单，**summary 保持全量**（计数口径稳定，报告间可比）。
- 分页：不提供 offset/limit——聚合报告受项目规模约束（cessna-172 = 61 条需求），单文档完整返回优于分页语义；P1 分页透传是针对列表端点的机制，不适用于聚合产物。

### 开放问题⑥：验收金样例（已决策）

**决策：金样例 = 双轨基线 + ≥3 条断言（G1–G6 六条），对 cessna-172 执行，全 READ 无 B 段。**（基线快照与漂移策略见事实 3。）

| # | 断言 | 内容 |
|---|---|---|
| G1 | **关键数字与 reqmesh 前端分析一致** | 同次运行内：report.summary.coverage.{total,shallow_covered,deep_covered,coverage_pct,deep_pct} == get_coverage 返回值；summary.gap_analysis.{total,gaps} == get_gap_analysis；summary.traces.links == len(get_traces.links)；summary.suspect_links.count == get_suspect_links.count；summary.unreviewed.{count,never,stale} == get_unreviewed_requirements 拆分；summary.allocation.{rows,unallocated} == 矩阵行数/allocated_to 空行数。reqmesh 前端分析消费同一批端点 → 数字一致即与前端分析一致。绝对数按基线快照断言：61 / 59-48-42-81-71 / 40 / 9 / 2 / 41（40 never + 1 stale）/ 61 行 7 未分配（2026-09-02T05:38Z 实测）；漂移时按 P1 惯例注明并保留自洽断言 |
| G2 | **缺口清单完整** | master gaps 的 id 集合 == 六源缺口 id 并集（无丢失、无编造）；点检 SMOKE-P2-001（review.stale + 2×trace.stale，evidence 含 link_type/from/reason）与 AFRM0000（coverage.uncovered(design) + allocation.missing 同根并存） |
| G3 | **建议模板命中** | 报告中每条 action 命中模板表（type→模板）；抽样断言：trace.unlinked → set_relations 读-改-写回放提示、content.no_source → update_requirement(source=…)、review.never → review_item、allocation.missing → set_allocation(allocated=true) |
| G4 | **排序规则** | gaps[] 前缀样本断言：high 组 < medium 组 < low 组 < info 组，组内按维度数降序、再 id 升序 |
| G5 | **零副作用（A 段）** | 调用前后 list_requirements.total == 61（不变）；冒烟全程 HTTP 方法 ⊆ {GET}（登录 POST 除外）；git 提交数不变——is_repo=false 时条件降级注明（P2/P3 实测偏差同款；本会话实测 is_repo=false） |
| G6 | **确定性** | 连续两次调用除 generated_at 外逐字节一致 |

- 冒烟脚本 scripts/smoke_p4.py（network-tagged，不进默认 pytest 集合）：登录（POST）→ 六源基线采集（源工具调用，作 G1 对账对象）→ get_traceability_gap_report 两次（G1–G4、G6）→ 前后 total 断言（G5）→ 记录落盘 docs/smoke/P4-cessna-172.md（时间戳、实例 URL、项目、每步结果与关键计数、基线快照、零副作用声明；凭据不落盘）。
- 负例（离线单测覆盖，不进冒烟）：dimensions 白名单过滤效果、单源 500 → fail-fast 整体报错、模板表 12 行逐一命中（含 no_description 零命中语料）、排序边界（同严重度同维度数）。
- 本会话已用 live 探针完成基线采集（事实 3）；开发会话冒烟如遇漂移，按 G1 降级规则处理并在记录注明。

### 工具契约

**get_traceability_gap_report**（MCP 工具，description 以 READ-ONLY 开头，中文）：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| project_id | str | * | 项目上下文 |
| dimensions | list[Literal[12 类维度]] | — | 缺口维度白名单；默认 None = 全部（⑤） |

返回结构（report schema，v1）：

```
{
  "project_id": str,
  "generated_at": "<ISO-8601 UTC>",
  "summary": {                              # 全量计数（不受 dimensions 过滤影响）
    "requirements_total": int,              # 61（来自 gap-analysis.total 而非额外请求）
    "coverage":      {total, shallow_covered, deep_covered, coverage_pct, deep_pct,
                      broken_chain, uncovered_items, unwanted_items},
    "gap_analysis":  {total, gaps},
    "traces":        {links: int, types: {type: count}},
    "suspect_links": {count: int},
    "unreviewed":    {count: int, never: int, stale: int},
    "allocation":    {rows: int, unallocated: int},
    "gap_entities":  int,                   # 主清单条目数
    "dimension_breakdown": {high, medium, low, info}   # 主清单全部维度按严重度计数
  },
  "chapters": {                             # 六源章节；带维度注解的条目（含 info 级多余覆盖标注）
    "coverage":       {total_analyzed, count, items: [{id, name, needs, uncovered_types,
                       unwanted_coverage, shallow, deep, broken_chain, dimensions: [{type, severity}]}]},
    "gap_analysis":   {total, gaps, count, items: [{id, name, issues, dimensions}]},
    "traces":         {links, types, items: [{source, target, type}]},   # 清单上下文，非缺口
    "suspect_links":  {count, items: [{source, source_collection, target, type, reason,
                       dimensions: [{type, severity, evidence}]}]},
    "unreviewed":     {count, never, stale, items: [{id, name, reviewed, current_fingerprint,
                       dimensions: [{type, severity, evidence}]}]},
    "allocation":     {rows, unallocated, items: [{req_id, req_name, req_type, row_id,
                       row_name, allocated_to, dimensions}]}
  },
  "gaps": [                                 # 主清单：跨源去重合并，三重键排序（②）
    {
      "id": str, "collection": "requirements", "name": str,
      "dimensions": [{type, severity, source, evidence: {…}}],   # source ∈ 六源章节名
      "actions": [{action: str, tool_hint: [str], severity}],     # 模板渲染（③）
      "max_severity": str
    }
  ],
  "meta": {"tool": "get_traceability_gap_report", "version": 1,
           "filters": {"dimensions": [...] | null}}
}
```

- 主清单 key = 实体 id（六源缺口均为需求中心：coverage/gap/unreviewed/allocation 的条目即需求；suspect-links 按 target 并入该需求的条目——target 为被指向实体，实测即需求）。去重合并 = 同 id 多源维度并集，evidence 保留源数据字段（如 trace.stale 的 link_type/from/reason、review.stale 的 reviewed/current_fingerprint、coverage.uncovered 的 need_type）。
- `requirements_total` 取自 gap-analysis.total（61，与 list_requirements.total 同源）——**六源之外零请求**，契约明示不额外调用 list_requirements。
- 错误：任一源 4xx/5xx → UpstreamError 透传（MCP tool error，整体失败无部分报告）；形状未知 → HarnessError（P3 get_requirement_quality 同款防御）。全 READ：不产生任何审计行、不涉审批门。

### 配置项

无新增 Settings/环境变量（dimensions 参数覆盖过滤；无阈值、无循环上限）。P1–P3 配置全部沿用。

### 注册表与导出扩展

- build_registry() 增 1 行：`get_traceability_gap_report`（domain=复合技能、level=READ）。40 行（25 READ + 12 写 + 2 P3 + 1 P4）。
- annotations_for 零改动（READ → readOnlyHint=True 已有）；`_REPORT_ROUTES`/get_project_report 零改动（④）。
- OpenAI 导出：40 工具 1:1 对账（P2 模式）；dimensions 的 Literal 枚举经既有 defs 内联机制导出；golden `tests/fixtures/http/openai_export.json` 同步更新。
- tests/mapping.py 增 1 行 ToolMap（project_id*、dimensions 可选；Case 以六源 fixture 为 routes 的调用样例）。
- ADR-0002 补实现注记（开发会话完成后，非词汇表变更）：新工具并入 domain=复合技能（兑现 P3 预告）+ 不扩展 report 枚举的理由。

### 冒烟（单段，network-tagged）

- 脚本 scripts/smoke_p4.py（模式沿用 smoke_p1/p2/p3.py）：登录 → 六源基线采集 → get_traceability_gap_report 两次 → G1–G6 断言 → 记录落盘 docs/smoke/P4-cessna-172.md。**无 B 段**：P4 全 READ，不产生任何 reqmesh 写副作用与残渣。
- 前置：实例可达 + 凭据经环境变量（.env 已有）；服务账号/审批门无关（纯 READ）。
- 冒烟不得调用 git/init（ADMIN 层，P2 惯例）；git 提交断言 is_repo=true 时执行、否则降级注明（P2 实测偏差 2 同款）。

## 验收标准（逐条可测试；括号为归属 ticket）

1. get_traceability_gap_report 经 MCP 双 transport 列出并可调用，schema 与契约表一致（含 dimensions Literal 枚举）（#33）。
2. 六源聚合：一次调用内部只发 6 个 GET（coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix），无其他请求（#31、#34）。
3. 关键数字逐项相等：summary 各字段 == 同次运行的源工具返回值（G1）（#31、#34、#35）。
4. 12 类缺口维度全部可提取，证据字段齐全，严重度映射与模板表一致（#31、#32、#34）。
5. 去重合并：master gaps 按实体 id 并集多源维度；id 集合 == 六源缺口 id 并集（无丢失、无编造）（#31、#34、#35）。
6. 排序确定性：三重键（severity rank → 维度数降序 → id 升序）与条目内规则（#31、#34、#35）。
7. 建议模板：模板表 12 行逐行命中；每条 action 命中模板；抽样断言见 G3（#32、#34、#35）。
8. 只读承诺：调用期间 HTTP 方法 ⊆ {GET}；报告绝不调用写工具/写端点、不产生审计行（#33、#34、#35）。
9. 过滤：dimensions 白名单过滤 chapters/gaps，summary 保持全量（#31、#34）。
10. 注册表 40 行；OpenAI 导出 40 工具与 MCP 注册 1:1 对账、名称合规、parameters 过 jsonschema；get_project_report/`_REPORT_ROUTES` 零改动回归（#33）。
11. 离线测试全绿（无网络依赖）；P1–P3 既有测试不回退（现 329+ passed）（#34）。
12. 冒烟 G1–G6 全部断言通过，记录落盘 docs/smoke/P4-cessna-172.md（含基线快照与零副作用声明）；P4 无 B 段、无残渣（#35）。

## Testing Decisions

- 标准沿用 P1–P3：只测外部行为（聚合正确性、schema 形状、排序、模板命中、只读、过滤、fail-fast、确定性）；不测内部实现细节。
- 全部单元测试离线：respx 打桩 + fixture 文件（六源复用 tests/fixtures/http/ 既有样本，**勿改**；P4 仅新增过滤期望等少量新样本）；golden 报告以事实 3 基线快照构造期望（tests/fixtures/http/report_golden.json，含 summary/gaps 关键路径与 SMOKE-P2-001/AFRM0000 合并条目点检）。
- 模块级测试职责：
  - report/ 内核：六源聚合逐项相等；12 类维度提取与证据；去重合并（多源同 id 并集）；三重键排序（含同严重度/同维度数边界）；dimensions 过滤（chapters/gaps 过滤 + summary 全量）；fail-fast（单源 500/404）；确定性（两次调用除 generated_at 外一致）。
  - 模板：12 行逐行命中；渲染确定性；tool_hint 词表 ⊆ 既有写工具名（review_item/update_requirement/set_relations/set_allocation/create_verification_case）。
  - 工具：schema 与契约一致；只读断言（HTTP 方法 ⊆ {GET}）；mapping.py ToolMap 路由。
  - 导出：40 工具对账（test_openai_export.py 既有模式）。
  - 冒烟：G1–G6 见⑥，network-tagged。
- 生成模型不重跑（P4 无新请求体模型）；report 内核为手写纯函数（无生成代码）。

## Out of Scope

- 报告 Markdown/HTML/表格渲染与发布 → 消费者渲染或 P6 文档层。
- 自动修复执行（调用任何写工具）、修复计划编排（多步写序列的 agent 编排）→ 既有 P2/P3 写工具 + P5 agent loop。
- 报告缓存/增量订阅/流式分块 → P5/P6。
- 组件/基线/需求组/类型/状态过滤（六源无服务端过滤参数，客户端 slice 属消费者职责，⑤）。
- get_project_report 的 report 枚举扩展 → 不纳入 P4（独立工具，④）；《reference freshness/conflicts/backlog/pugh/risk-bingo》五个服务端端点存在于 0.5.0 快照，是**未来 phase** 的合法枚举扩展对象（P1 预告兑现路径），P4 不消费（分析域而非追踪/覆盖缺口域，且不在 P4 六源聚合范围）。
- 分页（聚合单文档，⑤）；质量/风险维度纳入报告（quality 属 P3 技能与 get_project_report(quality)，不在追踪/覆盖缺口范围）。
- ADMIN 层、写工具新增/修改 → 维持 P2/P3 边界不变。
- P1–P3 资产不重构：tracking.py/requirements.py/components_report.py/registry 既有行/skills.py/guardrails/client 零修改（仅 registry 加 1 行 + 新增文件）。

## Further Notes

- 术语一律按 CONTEXT.md：工具/权限层级/审批门/审计/工作会话；本 spec 新增域词「缺口维度（dimension type）」「主清单（gaps）」为报告 schema 字段语义，非流程术语。
- 与 ADR 的关系：ADR-0001 无冲突；ADR-0002 无动词扩展（verb=get 词汇表内）、无权限前缀；domain=复合技能为兑现 P3 预告；report 枚举不扩展（④）——开发会话完成后补一行实现注记。
- 许可证边界：聚合逻辑独立编写，仅消费公开 REST 响应形状与实测 fixture；不复制 reqmesh GPL 源码（事实 5）。
- 开发会话按 design §5：实施后自动启动审核子代理与测试子代理；每轮循环结论记对应 ticket comment；超 5 轮仍失败回到需求会话（入口即交接文本）。
- 实测偏差回写惯例：开发会话对真实实例实测的偏差（如基线漂移、suspect/unreviewed 边界样本）记入 docs/smoke/P4-cessna-172.md「实测偏差」节，需求会话确认后回写本 spec 的「实测偏差与决策」节（P1/P2/P3 同款流程）。
