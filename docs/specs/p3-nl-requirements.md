# P3 spec：自然语言建需求（EARS + quality lint 闭环 → 落库）

> 状态：需求会话产出，待开发会话实施。
> 入口：design [docs/reqmesh-harness-design.md](../reqmesh-harness-design.md)（§3 D5/D6/D8、§5 流程、§7 验证基线） · epic [#3](https://github.com/GuangjieYu1/PRDMS/issues/3) · 术语 [CONTEXT.md](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md) · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md) · P1 spec [docs/specs/p1-tool-layer-mvp.md](p1-tool-layer-mvp.md) · P2 spec [docs/specs/p2-write-path.md](p2-write-path.md)
> 交接：见 [docs/handoffs/p3-nl-requirements.md](../handoffs/p3-nl-requirements.md)

## Problem Statement

P2 交付了 12 个写工具与四级审批门，但「自然语言建需求」仍是多步手工过程：模型需要自己理解 EARS/INCOSE 措辞规范、逐字写出需求文本、猜测 quality lint 会不会通过、再调用 create_requirement。design D8 的旗舰用例①要求把这个过程收敛为**单个 MCP 工具**：调用方给自然语言（一句话或要点）→ 工具产出符合 EARS 句式的需求文本 → 经 quality lint 迭代修正 → 通过后落库（DRAFT 层审批门 + 审计 + dry-run，全链路复用 P2 写路径）。P5 尚未交付，因此**编排逻辑必须在工具内部同步完成，不得依赖 agent 运行时或任何 LLM provider**（D5）。

本会话核实的关键事实（见「事实核实」节）：reqmesh 的 quality lint 是**读取时计算**的（GET /quality 项目级分析，写入时零校验）；规则集以 INCOSE 规则为逐条引用，README 声称「基于 INCOSE/EARS/ISO 29148」但**上游没有任何 EARS 句式实现**——EARS 句式是本会话新增；quality 规则配置按项目存于 _meta.yaml 并经 /quality 响应下发。

## 事实核实（本会话，证据留档，不拍脑袋）

1. **P1 的 25 个 READ 工具没有 quality 工具，但项目级分析已可达**：get_project_report(report="quality") 已路由 GET /api/projects/{project_id}/quality（P1 映射表 #25，components_report.py 的 _REPORT_ROUTES）。该端点响应（对 cessna-172 实测，2026-09-01）：average=89、total=58、config={min_words, max_words, rules, weights}、per_requirement=[{id, name, score, findings:[{rule, severity, message, start, end}]}]（按 score 升序）。**需求级反馈没有独立端点**——只能从项目级响应按 id 过滤；**写入时上游不校验 quality**（score_requirement/project_quality 仅被 /quality 与 CLI 调用，写入路径只有 schema 校验）。结论：P3 的 lint 闭环必须**本地镜像规则集**（文本在落库前不存在于 reqmesh，服务端只能给已存需求打分），并新增 1 个需求级 quality READ 工具（③）。
2. **create_requirement 字段语义**（P2 生成模型 RequirementCreate + 上游 backend/app/models/requirement.py 与 router.py 双源核实）：
   - id（必填）：safe_id（允许 [A-Za-z0-9._ -]，禁 ".."）+ 项目命名标准校验（enforce_naming，cessna-172：requirements = 4 位 alpha 前缀 + 4 位数字后缀，separator 为空；校验**宽松**——只要求以数字结尾）；已存在 → 409。
   - description：API 收**纯文本** str，服务端 sanitize_html 转义存储（HTML 富文本为发布形态；纯文本输入原样转义回读，无 <p> 包裹——冒烟回读断言可做文本级相等）。质量 lint 对 name + description（先 strip HTML）合并打分。
   - name：短标题（默认空串）；type：16 值枚举，默认 functional；status：7 值枚举，默认 proposed；priority：low/medium/high/critical，默认 medium；parent/subject 可选；rationale/source 默认空串。
   - verification_method / verification_status：**不可写**，读取时从验证用例派生；无验证用例时 method 回落 "test"（UNVERIFIED_METHOD）——所以新需求在服务端 quality 里默认受 untestable 规则约束（需可度量数字+单位）。
   - PUT 部分更新：exclude_unset 语义 + 可选 If-Match（modified 版本令牌）——P2 已按此实现，P3 不新增写面。
   - 写路由 POST /requirements 需 require_maintain（maintainer）——与 P2 服务账号结论一致，P3 复用同一账号，不新增身份。
3. **quality 规则集准确表述**（上游 backend/app/services/quality_rules.py + quality.py + README「Quality Linting」节，读取核实；vendored openapi 快照**不含**规则集，仅 /quality 空 schema）：
   - README 表述：「Inline requirement writing feedback based on INCOSE, EARS, and ISO 29148 guidelines」（weak words、vague quantifiers、placeholders、non-atomic、untestable、word count、HTML-aware）。**准确边界**：代码级逐条引用只有 **INCOSE Guide to Writing Requirements**（v4 summary sheet，如 R07 Avoid Vague Terms / R08 No Escape Clauses / R10 Avoid Open-Ended Clauses / R11 Superfluous Infinitives / R16 Avoid Not / R17 Oblique / R19 Avoid Combinators / R20 Avoid Purpose / R21 Avoid Parentheses / R24 Avoid Pronouns / R26 Avoid Absolutes / R35 Temporal Indefinite / R38 Avoid Abbreviations / R01 Structured Statements）；**上游无任何 EARS 实现，也无 ISO 29148 专属规则**（ISO/IEC 15288:2023 §6.4.2.3 仅在 Requirement 模型 docstring 提及）——EARS 句式是 P3 的新增，README 的 EARS/ISO 29148 表述为上游营销性概括，本 spec 以此为准。
   - 规则清单（rule id 是公开契约，项目可经 _meta.yaml 的 quality.{rules,weights,min_words,max_words} 开关/调权；config 键与 rule id 有复数差异：vague_quantifiers、placeholders 为 config 复数键）：
     | rule id | severity | weight | INCOSE | 说明 |
     |---|---|---|---|---|
     | weak_words | warning | 5 | R07 | should/may/might/could/would + appropriate/adequate/user-friendly/fast/robust/flexible/scalable/easy/simple/reasonable 等 |
     | negation | warning | 4 | R16 | shall not / must not / will not / never / not |
     | superfluous_infinitive | warning | 4 | R11 | have the ability to / be capable of / be designed to / be able to / be used to |
     | escape_clauses | warning | 6 | R08 | as far as possible / where possible / if necessary / as required / if practicable 等 |
     | oblique | warning | 3 | R17 | and/or；3+ 字母/3+ 字母 |
     | purpose_clause | info | 2 | R20 | with the intent of / in order to / so as to / so that |
     | passive_voice | info | 2 | —（指南外） | be + 过去分词（given/taken/made/set/built/known/shown/found/seen/done/sent/held/left 及 -ed 词尾） |
     | vague_quantifier | warning | 3 | — | some/several/many/few/minimal/maximal/enough/sufficient/a lot of/a number of/a few/a couple of |
     | pronoun | warning | 4 | R24 | these/those/their/them/they/this/its/she/he/it |
     | absolute | warning | 4 | R26 | completely/totally/always/every/never/none/any/all + 100% |
     | combinator | info | 3 | R19 | in addition to/as well as/otherwise/meanwhile/however/whether/unless/but |
     | temporal_indefinite | warning | 4 | R35 | in a timely manner/in due course/when convenient/as soon as/eventually/promptly/at last |
     | open_ended | warning | 6 | R10 | including but not limited to/such as/and so on/among others/etc. |
     | placeholder | **error** | 10 | — | TODO/FIXME/TBD/XXX/HACK/???/?? |
     | abbreviation | info | 2 | R38 | e.g./i.e./vs./approx./misc./min./max. |
     | non_atomic | info | 5 | — | 单句两个 and |
     | parentheses | info | 2 | R21 | 圆/方括号内容 |
     | no_obligation（bespoke） | warning | 6 | R01 | 无 shall/must/will/is required to（enabled=False 的规则表条目，由倒置检查实现） |
     | untestable（bespoke） | warning | 5 | — | verification_method=test 且文本无可度量数字+单位（%、percent、时间、字节、频率、长度、质量、温度等词表） |
     | word_count（bespoke） | warning/info | 10 | — | 少于 min_words（默认 5）warning；多于 max_words（默认 200）info（半罚） |
   - 打分：score = 100 - min(penalty, max_penalty)/max_penalty*100（默认权重合计 90）；cessna-172 实测 config：min_words=5、max_words=300、passive_voice=false（其余默认）。/quality 有 rate limit（20/60s，上游 rate_limit(20, 60)）——P3 复合工具每次调用只发 1 次 /quality（取项目 config）。
   - **许可证边界**（沿用 P1 开放问题①的同款决策）：reqmesh 为 GPL，P3 的本地 lint **不复制上游 regex/权重/message 源码**，而是按上述公开契约（rule id、severity、weight、INCOSE 引用与 README 行为描述）独立重写模式；EARS 检查是 P3 原创。行为等价性由冒烟「本地分 == 服务端分」对账断言保障。
4. **id 生成的可得数据**：GET /api/projects/{project_id}/requirements/next-uid（P1/P2 延后清单中的「写流程辅助 READ 端点」，P3 按 P2 预告启用）实测返回 {"prefix": "REQ", "next_id": "REQ0001"}（自动递增后缀，跳过已占用的 id）。P3 复合工具**内部**经只读客户端直连该端点取 id，**不新增公开 next-uid 工具**（调用方也可显式传 id 覆盖；并发冲突 409 时重取一次）。

## Solution

在 P2 的 reqmesh-harness 上新增三块：

1. **本地 lint 模块 src/reqmesh_harness/lint/**：按上表独立重写规则（rule id 公开契约）+ EARS 结构性检查（独立于打分）+ 确定性修正表 + 项目 config 装载（GET /quality 的 config 字段，失败回落默认 config 并标注）。
2. **draft_requirement 复合工具（1 个 MCP 工具 = 完整 NL→EARS→lint→落库闭环）**：解析自然语言（一句话/要点）→ EARS 句式渲染 → 本地 lint 迭代修正（≤N 轮）→ 过线后复用 P2 写路径落库（DRAFT 审批门 + 审计 + dry-run 全链路）；dry_run=true 时生成+lint 但不落库。
3. **get_requirement_quality READ 工具（1 个）**：需求级 quality 反馈——GET /quality 后客户端按 req_id 过滤（服务端无独立端点，事实 1），返回该需求的 score/findings 与项目 average/total 上下文。

注册表 37 → **39 行**（25 READ + 12 写 + 2 新增）；MCP 注册与 OpenAI 导出同源对账（P1/P2 模式不变）。冒烟对 cessna-172 跑 A 段（金样例 dry_run 全量，零副作用）+ B 段（3 条真实写闭环），记录落盘。

## User Stories

1. As an LLM agent, I want a single draft_requirement tool that turns a natural-language sentence or bullet points into an EARS requirement, lints it, and persists it, so that I never hand-assemble requirement text or guess lint outcomes.
2. As an LLM agent, I want the tool to pick the EARS template automatically from markers (WHEN/IF/WHILE/WHERE), with an explicit template override, so that both free-form and deterministic calls work.
3. As an LLM agent, I want the lint loop to fix what can be fixed deterministically and report residual findings honestly, so that I know exactly what passed and what did not.
4. As an LLM agent, I want dry_run=true to return the EARS text, lint report and would_send preview without writing, so that I can preview before approval.
5. As an LLM agent, I want a get_requirement_quality tool for one requirement, so that I can check a persisted requirement's server-side quality score and findings.
6. As an operator, I want draft_requirement to reuse the P2 approval gate verbatim (whitelist entry keyed by the tool's own name, audit line per invocation), so that the composite skill is governed exactly like any other DRAFT tool.
7. As an auditor, I want every draft_requirement invocation that reaches the write path recorded in the audit log with the lint outcome, so that the full NL→落库 chain is traceable.
8. As a developer, I want the whole unit test suite offline (respx fixtures), so that lint logic is verified without the LAN instance.

## Implementation Decisions

### 开放问题①：工具命名与形态（已决策）

**决策：单个复合工具 draft_requirement（verb draft，DRAFT 层）+ 单个 READ 工具 get_requirement_quality；编排全部在工具处理器内部同步完成（P5 前无 agent 运行时，D5）。**

- draft_requirement：verb_entity 命名（ADR-0002），注册表 level="DRAFT"、domain="复合技能"（新实体域，P4 复合技能②并入），description 以 DRAFT 开头（P2 前缀惯例）并用中文书写；readOnlyHint=False。
- **与 ADR-0002 的关系（显式声明）**：draft（起草）是 verb 词汇表**扩展**——与 P2 扩展 create/update/set/run/review 同一机制，开发会话完成后按惯例回写 ADR-0002 实现注记。**显式标注同形歧义**：draft_ 前缀与权限层级 DRAFT 同形，而 ADR-0002 禁止的是「以权限层级作为命名前缀」；此处 draft 是动词而非层级前缀，且 ADR-0002 的硬规则（审批门从注册表 level 映射、绝不解析工具名）使同形零风险——**扩展，不是冲突**。备选 compose_requirement（同样需扩展词汇表且语义弱于「起草草稿」）、create_requirement_from_nl（名字带后缀，违背 verb_entity 简洁性）均拒绝。
- 不拆分为「生成工具 + lint 工具 + 落库工具」多步编排：拆分会把编排责任推回调用方（模型），而 P5 之前没有 agent loop 承接多步编排（本会话硬约束）；单工具内部循环是唯一满足 D8「闭环」且不依赖 agent 运行时的形态。
- get_requirement_quality：READ 层、domain="需求"、verb get（词汇表内，无扩展）、description 以 READ-ONLY 开头。
- 注册表 37 → 39 行；OpenAI 导出 39 工具 1:1 对账（P2 测试模式）；tests/mapping.py 增 2 行映射。

### 开放问题②：EARS 句式子集与 reqmesh 字段映射（已决策）

**决策：完整支持 EARS 五句式（Mavin et al. 2009）；输入为受控自然语言（标记句或要点），工具只做槽位抽取与模板渲染，不做翻译、不编造内容。**

| template | EARS 句式（渲染输出，英文） | 触发标记（自动检测，template="auto"） | 要点形式（key: value 行） |
|---|---|---|---|
| ubiquitous | The (system) shall (response). | 无 WHEN/IF/WHILE/WHERE 标记（默认） | system: / response: |
| event | WHEN (trigger), the (system) shall (response). | 句首 When + 句中 shall | when:（或 trigger:）/ response: |
| unwanted | IF (condition), THEN the (system) shall (response). | 句首 If + then + shall | if:（或 condition:）/ response: |
| state | WHILE (state), the (system) shall (response). | 句首 While + shall | while:（或 state:）/ response: |
| optional | WHERE (feature), the (system) shall (response). | 句首 Where + shall | where:（或 feature:）/ response: |

- 解析规则（确定性，无 LLM）：
  - **句子形式**：正则按标记分派句式（When/If/While/Where + then + shall）；无标记时按「The (system) shall (response)」分派 ubiquitous。(system) 未检测到时回落参数 system（默认 "the system"）。渲染统一为首字母大写 + 句号结尾。
  - **要点形式**：nl_text 按行 key: value 解析（key 见上表，支持 system/name/type/priority/parent/subject/id 行内覆盖）；句子与要点混用取并集，冲突时报 InputParseError。
  - **语言边界（显式）**：P3 仅接受**英文**槽位内容。中文输入 → InputParseError（hint 说明 P5 的 agent loop 将承担翻译）。理由：① 确定性工具无法翻译；② reqmesh 的 lint 规则是英文 regex，中文文本会因「无英文弱词命中」而**假性满分**，违背 D8 quality 闭环的目的。P5 落地后翻译职责在 agent loop，draft_requirement 契约不变。
  - 解析失败（无 shall、标记残缺、要点 key 未知）→ InputParseError（MCP tool error，含受支持形态示例；不发写请求、不记审计——审计只覆盖写尝试，见⑤）。
- **reqmesh 字段映射模板**（渲染后按此组装 RequirementCreate）：
  | reqmesh 字段 | 取值规则 |
  |---|---|
  | id | 参数 id；缺省 → 内部 GET /requirements/next-uid（next_id）；上游 409 冲突 → 重取一次后重试，仍冲突则报错 |
  | description | EARS 渲染句子（纯文本；服务端 sanitize 后按原样回读，冒烟以文本相等断言） |
  | name | 参数 name；缺省 → 派生：response 子句首字母大写、截断 80 字符（确定性规则） |
  | type | 参数，默认 functional |
  | priority | 参数，默认 medium |
  | status | 固定 proposed（新需求不做评审，不暴露参数；评审由既有 review_item 单独执行，新需求保持未评审状态出现在 get_unreviewed_requirements） |
  | parent / subject | 参数透传（均可省略） |
  | rationale | 固定 "自然语言建需求（draft_requirement）：" + nl_text 原文（≤200 字符截断）——溯源原文，审计/评审可用 |
  | source | 留空串（调用方无来源语义；不编造） |
  | verification_* | 不可写（上游派生）——lint 的 untestable 按无验证用例回落 "test" 语义执行（事实 2） |

### 开放问题③：lint 入口与过线标准（已决策）

**决策：lint 在 harness 本地执行（镜像规则集，独立重写、不复制 GPL 源码）；每次调用经 GET /quality 取项目 config（规则开关/权重/字数上下限），失败回落默认 config 并在报告标注 config_source="default"；过线标准 = 打分 ≥ REQMESH_LINT_MIN_SCORE（默认 90）且零 error 级 finding。**

- **本地镜像规则表**：覆盖事实 3 全部 20 条规则（18 pattern + no_obligation/untestable/word_count），规则 id/severity/weight 与上游一致；finding 字段形状对齐上游（rule, severity, message, start, end）；message 用中文书写（仓库文档语言惯例，模型消费友好），**注明 rule id 与 INCOSE 引用**。EARS 结构检查**不进打分**（二进制 gate：句式匹配 + system/response 非空），保持「本地分 == 服务端分」可对账。
- 打分公式与上游一致：score = 100 - min(penalty, max_penalty)/max_penalty*100；lint 文本 = name + 换行 + description（name 派生值参与打分，与上游 combined 一致）。
- **过线标准（两层，均为可配置）**：
  1. 硬门槛：无 error 级 finding（placeholder 是唯一 error 级规则——占位符不可自动修复，工具**绝不编造内容**补位）；
  2. 分数门槛：score ≥ REQMESH_LINT_MIN_SCORE（默认 90；Settings 新增，pydantic-settings）。
- **EARS 与 INCOSE 的固有张力（显式记录）**：Unwanted 句式允许 shall not 响应，必然触发 negation（R16，-4 分）——这是句式语义而非措辞缺陷，**不允许**为消除 finding 而反转语义。negation 因此列入 Unwanted 句式的**残余 finding 白名单**（见④），并写入工具 description 提示调用方优先用「正向缓解」表述（如 "display a door warning" 而非 "not permit engine start"）。
- **新增 READ 工具 get_requirement_quality(project_id, req_id)**：服务端事实源的需求级反馈（落库后对账用）。实现 = GET /quality 一次 + 客户端过滤 per_requirement 中 id == req_id；返回 {id, name, score, findings, average, total}；目标需求不存在时相关字段为 null 并在 description 注明。rate limit（20/60s）在 description 注明。
- **threshold 的语义边界**：REQMESH_LINT_MIN_SCORE 是**本地 lint 的过线标准**；服务端 /quality 分数用于冒烟对账断言（本地分 == 服务端分，Unwanted 除外按残余规则解释），不做运行时二次拦截（服务端分与本地分同源同规则，二次拦截是冗余调用）。

### 开放问题④：迭代策略（已决策）

**决策：工具内确定性修正循环，最多 N = REQMESH_LINT_MAX_ROUNDS（默认 3）轮；不能确定修复的 finding 记为残余；循环结束仍未过线 → 不落库，返回完整报告与 hint。**

- 每轮 = 应用修正表（下）→ 重渲染 → 重打分；**收敛检测**：某轮修正前后文本不变则提前终止（防空转）。
- **确定性修正表**（仅此 6 类，其余一律残余——语义性修复需要 LLM，是 P5 的事）：
  | rule id | 修正动作（确定性） |
  |---|---|
  | weak_words | 义务位情态动词替换：should/might/could/would → shall（形容词类命中不修，残余） |
  | superfluous_infinitive | have the ability to X → X；be able to X / be capable of X / be designed to X / be used to X → X |
  | escape_clauses | 删除命中的从句（含前置逗号） |
  | oblique | and/or → or（A/B 类不拆，残余） |
  | abbreviation | e.g.→for example、i.e.→that is、vs.→versus、approx.→approximately、misc.→miscellaneous、min.→minimum、max.→maximum |
  | parentheses | 去括号保留内容（(X)→X） |
- **残余 finding 白名单**（句式固有，允许过线时携带）：unwanted → {negation}；其余句式 → 空集。白名单外仍有过线标准内的 warning/info finding → 视为未过线。
- **终止语义（不落库，返回结构见工具契约）**：
  - N 轮后未过线 → persisted=false + 最佳候选文本 + lint 报告 + hint（调用方可用 create_requirement 自行兜底，技能不代做质量决策）；
  - placeholder（error）→ 立即终止（不尝试修复）；
  - untestable + require_measurable=true（默认）→ 未过线：工具**绝不编造数字**，报告 untestable finding，hint 提示补充可度量数字+单位或显式 require_measurable=false；
  - require_measurable=false → untestable 降为残余（照常落库，finding 保留在报告），供无法量化需求（如部分 business/regulatory 条目）的显式豁免——**豁免是调用方明示的，不是默认**。
- **P5 演进路径**：REQMESH_LINT_MAX_ROUNDS 循环是纯函数接口（文本进、文本出），P5 的 agent loop 把「确定性修正」替换为「LLM 改写」时无需改工具契约。

### 开放问题⑤：与审批门关系（已决策）

**决策：draft_requirement 以注册表 level="DRAFT" 进入 P2 审批门，白名单条目按工具名 draft_requirement 独立裁决；落库复用 _write_common.write_request（同一段门/审计/dry-run 机器），不改 P2 代码。**

- **白名单规则**：DRAFT 层条目 tool = "draft_requirement"，project 可省略（通配全部项目）——与 P2 DRAFT 规则完全一致。**审批 draft_requirement 不等于审批 create_requirement**（两条目独立；操作员批准的是「自然语言建需求」这项复合能力，直接建需求的 create_requirement 仍单独卡门）。fail-closed、拒绝时返回 P2 同款 ApprovalDeniedError + approvals add 修复建议。
- **复用边界（不动 P1/P2 资产，仅 import）**：处理器从 tools/groups/_write_common.py import write_request / provided / create_checks / UNSET，从 client/generated/models.py import RequirementCreate——**零修改 P2 文件**。write_request(tool="draft_requirement", level="DRAFT", method="POST", path=..., body=..., dry_run=..., reason="", params=..., checks=create_checks(...))。
- **dry-run 语义边界（P2 不变式完整继承）**：dry_run=true 照跑审批门（dry-run 不是绕过审批的后门）；批准后不发写请求，返回 {dry_run: true, would_send: {method, path, body}, checks} + EARS/lint 报告；**不产生 git 提交**。lint 循环在 dry_run 下完整执行（预览的文本就是落库会用的文本）。
- **审计**：每次调用到达 write_request 即一条审计行（tool="draft_requirement"、level="DRAFT"、reason=""、dry_run 布尔），denied/dry_run/错误路径同 P2 全记。params_summary 在 P2 字段之外**附加两个标量**：lint_score（int）与 lint_rounds（int）——lint 结果进审计，全文 lint 报告在工具返回值（审计不做嵌套全文）。**未达写路径的失败（InputParseError、lint 未过线）不记审计行**——审计覆盖的是写尝试，与 P2 语义一致；此边界写入 spec 供审核子代理核对。
- 上游错误照 P2 透传（UpstreamError → MCP tool error），lint 已过但上游 409（id 冲突）时按②重取一次 id。

### 开放问题⑥：验收金样例（已决策）

**决策：5 条金样例覆盖五句式（英文、cessna-172、预期本地分 == 服务端分 == 100；passive_voice 在 cessna-172 config 为 false，金样例 4 在默认 config 下为 98——两者都写入断言）**，冒烟 A 段全量 dry_run（零副作用）+ B 段 3 条真实写闭环。

| # | 句式 | NL 输入（一句话） | 断言 EARS 输出 | type | 说明 |
|---|---|---|---|---|---|
| G1 | ubiquitous | The aircraft shall achieve a range of at least 1185 km at maximum cruise power. | 同输入（首字母大写规范化） | non_functional_performance | 可度量（1185 km）；无弱词 |
| G2 | event | When the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning. | WHEN the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning. | functional | 触发标记检测；302 km/h 可度量 |
| G3 | state | While in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level. | WHILE in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level. | functional | 状态标记检测；2.5 m/s 可度量 |
| G4 | optional | Where the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m. | WHERE the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m. | functional | 特性标记检测；"is engaged" 在默认 config 触发 passive_voice（info，98 分），cessna-172 config（off）为 100 |
| G5 | unwanted | If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s. | IF the cabin door is unlatched, THEN the aircraft shall display a door warning within 1 s. | safety | 正向缓解表述（无 negation 罚分）；1 s 可度量 |

- 金样例逐一核对过 lint 规则表：无 weak_words/escape/open_ended/abbreviation/oblique（km/h、m/s 为 1-2 字母边，不触发 3+ 字母斜杠规则）/pronoun/absolute/combinator（单 and）/parentheses/placeholder；均有 shall（no_obligation 过）与可度量单位（untestable 过）；词数在 min_words/max_words 内。**单元测试断言：本地 lint 对 G1–G5 打分 == 100**（G4 在默认 config 下 == 98 的用例单独覆盖）。
- **冒烟 A 段（零副作用，cessna-172）**：临时空白名单下 draft_requirement 被阻断（断言 ApprovalDeniedError 形状 + 审计 denied 行）→ 添加白名单后 G1–G5 全部 dry_run=true：断言 ① ears.sentence 与上表逐字符一致（G1 规范化后一致）、ears.template 正确；② lint.passed=true、score==100、findings 为空、rounds==1；③ would_send.body.description/name/type/rationale 与映射模板一致、checks 形状正确（id 冲突/引用检查）；④ **全程 list_requirements.total 不变（58）**、写路径零 HTTP 写请求、is_repo 时 git 提交数不变（cessna-172 实测 is_repo=false，条件化降级并注明，P2 同款处理）；⑤ 审计行数 == dry_run 调用数。
- **冒烟 B 段（真实写闭环，SMOKE-P3-001..003 固定 id）**：对 G1/G2/G5 dry_run=false 落库：断言 ① 201 返回实体 description 与 EARS 句子**文本相等**（sanitize 后纯文本原样回读）；② get_requirement 回读一致、status=="proposed"、rationale 含 NL 原文溯源；③ 新需求出现在 get_unreviewed_requirements；④ get_requirement_quality(req_id) 返回 score==100（**本地分 == 服务端分对账**）；⑤ 审计行数 == 全部写调用数（A+B 段）、lint_score/lint_rounds 字段在列；⑥ list_requirements.total == 61；残渣清单落盘（3 条 SMOKE-P3 需求 id）。B 段冒烟**不调用** review_item（新需求保持未评审是设计语义，②）。
- 负例（离线单测覆盖，不进冒烟）：弱词自动修正（should→shall）、placeholder 立即拒绝、require_measurable=true 拒绝无单位文本、N 轮后仍未过线返回 persisted=false、中文输入 InputParseError。

### 工具契约

**draft_requirement**（MCP 工具，description 以 DRAFT 开头，中文）：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| project_id | str | * | 项目上下文 |
| nl_text | str | * | 自然语言输入（标记句或要点，见②；≤2000 字符，超长报 InputParseError） |
| template | Literal[auto, ubiquitous, event, unwanted, state, optional] | — | 默认 auto（按标记检测） |
| system | str | — | system 槽位，默认 the system |
| name | str | — | 覆盖派生 name |
| type | RequirementType | — | 默认 functional |
| priority | Priority | — | 默认 medium |
| parent / subject | str | — | 透传 |
| id | str | — | 缺省内部取 next-uid（409 重取一次） |
| require_measurable | bool | — | 默认 true（④） |
| dry_run | bool | — | 默认 false（P2 统一参数） |

返回结构（三个终态；dry_run=true 与 persisted=true 互斥）：

- 落库成功（dry_run=false 且过门且过线）：{persisted: true, requirement: 上游 201 响应实体, ears: {template, sentence, system}, lint: {score, passed, rounds, findings, residual_findings, min_score, config_source, config}}
- 预览（dry_run=true，审批门照跑）：{persisted: false, dry_run: true, ears, lint, would_send: {method, path, body}, checks}
- 未过线（不落库；也用于 measurable/placeholder 硬拒绝）：{persisted: false, ears, lint: {passed: false, ...}, would_send, hint}

错误：InputParseError（解析失败，含受支持形态示例）、ApprovalDeniedError（P2 同款）、UpstreamError（P2 透传）。lint 未过线与解析失败**不记审计**（⑤边界）。

**get_requirement_quality**（READ-ONLY，中文）：project_id*、req_id* → {id, name, score, findings, average, total}（目标无记录时相关字段为 null 并在 description 注明）。一次 GET /quality + 客户端过滤；rate limit 20/60s 注明。

### 配置项（Settings 新增，环境变量，pydantic-settings）

- REQMESH_LINT_MIN_SCORE：int，默认 90（③ 分数门槛）。
- REQMESH_LINT_MAX_ROUNDS：int，默认 3（④ 修正轮数上限）。
- 其余全部沿用 P1/P2（REQMESH_BASE_URL、凭据、REQMESH_APPROVALS_FILE、REQMESH_AUDIT_FILE 等）——无新文件类配置。

### 注册表与导出扩展

- build_registry() 增 2 行：draft_requirement（domain 复合技能，level DRAFT）、get_requirement_quality（domain 需求，level READ）。39 行（25 READ + 12 写 + 2 新增）。
- annotations_for 零改动（DRAFT → readOnlyHint=False/destructiveHint=False 已有）。
- OpenAI 导出：39 工具 1:1 对账（P2 测试模式）；template/type/priority 的 Literal 枚举经既有 defs 内联机制导出。
- tests/mapping.py 增 2 行 ToolMap（draft_requirement 用例覆盖三终态 + 解析失败；get_requirement_quality 覆盖过滤与缺失两态）。
- **ADR-0002 回写**（开发会话完成后，P1/P2 同款实现注记）：verb 词汇表扩展 draft；draft_ 与 DRAFT 层级同形歧义及「审批门绝不解析名字」的消解依据随注记记录。

### 冒烟（A/B 两段，network-tagged）

- 脚本 scripts/smoke_p3.py（模式沿用 smoke_p1.py/smoke_p2.py，不进默认 pytest 集合）：A 段（金样例 dry_run 全量，零副作用断言）+ B 段（G1/G2/G5 真实写闭环）见⑥；记录落盘 docs/smoke/P3-cessna-172.md（时间戳、实例 URL、服务账号、每步结果与关键计数、残渣清单、A 段零副作用声明）。
- 前置：操作员已建 reqmesh-harness（maintainer）服务账号（P2 前置不变）；白名单经 approvals add draft_requirement（B 段；A 段先用临时空白名单断言 fail-closed）。
- 冒烟不得调用 git/init（ADMIN 层，P2 惯例）；git 提交断言 is_repo=true 时执行、否则降级注明（P2 实测偏差 2 同款）。

## 验收标准（逐条可测试；括号为归属 ticket）

1. draft_requirement 经 MCP 双 transport 列出并可调用，schema 与契约表一致（#27）。
2. 五句式渲染：G1–G5 输入 → EARS 输出与金样例表逐字符一致（#26、#29）。
3. 本地 lint：G1–G5 打分 == 100（默认与 cessna-172 config 下；G4 默认 config == 98 单独用例）；弱词修正、占位符硬拒绝、measurable 门、N 轮上限、残余白名单（unwanted→negation）各有用例（#25、#29）。
4. lint 打分对账：B 段落库后 get_requirement_quality 服务端分 == 本地分（100）（#30）。
5. 落库复用写路径：draft_requirement 未批准被阻断（fail-closed）、dry_run 不发写请求且返回 would_send、审计每调用一行含 lint_score/lint_rounds（#27、#29）。
6. dry_run 与 lint 失败路径不产生任何 reqmesh 写副作用（A 段 list_requirements.total 不变 + 审计 denied 行计数）（#30）。
7. get_requirement_quality 对已落库需求返回 score/findings，对未知 id 返回 null 字段（#28）。
8. 注册表 39 行；OpenAI 导出 39 工具与 MCP 注册 1:1 对账、名称合规、parameters 过 jsonschema（#28）。
9. 冒烟 A/B 段全部断言通过，记录落盘 docs/smoke/P3-cessna-172.md；docs/smoke/P1-cessna-172.md 的 total==57 与 P2 的 58 仅作历史快照（P3 B 段后为 61）（#30）。
10. 离线测试全绿（无网络依赖）；P1/P2 既有 215 个测试不回退（#25–#29）。

## Testing Decisions

- 标准沿用 P1/P2：只测外部行为（解析/渲染/打分/修正/门/审计/dry_run/导出对账）；不测内部实现细节。
- 全部单元测试离线：respx 打桩 + fixture 文件（/quality 项目 config 两态、next-uid、201 创建响应、409 冲突、404 过滤）；金样例文本作为 fixture 常量。
- 模块级测试职责：
  - lint/：规则逐条命中/不命中用例（金样例反例样本）；打分公式与权重合计（默认 max_penalty==90）；config 键复数映射（vague_quantifiers/placeholders）；修正表逐条 + 收敛检测；残余白名单；measurable 正则边界（"m/s" 命中、"miles" 不命中）。
  - EARS 解析：五句式句子形式 + 要点形式 + 混用冲突 + InputParseError 各形态（中文、无 shall、未知 key）。
  - 工具：draft_requirement 三终态（persisted/dry_run/未过线）+ 门 denied + 审计字段 + 409 重取 id；get_requirement_quality 过滤与缺失。
  - 导出：39 工具对账。
  - 冒烟：A/B 段断言见⑥，network-tagged。
- 生成模型不重跑（P3 无新请求体模型——RequirementCreate 已存在）；lint 模块为手写纯函数（无生成代码）。

## Out of Scope

- 翻译/多语言 NL（中文等）→ P5 agent loop（LLM）职责，P3 显式拒绝并给出 InputParseError（②）。
- LLM 语义改写修复 lint（替换确定性修正表）→ P5；REQMESH_LINT_MAX_ROUNDS 接口预留（④）。
- 自动 review_item（新需求保持未评审）、review_all 批量评审 → 不纳入本技能（既有工具可单独调用）。
- 新增公开 next-uid/next-id READ 工具 → 不新增（复合工具内部直连；P4/P5 按需加注册行）。
- 报告聚合（项目 quality 历史/趋势）、lint 报告持久化/检索 → P4/P6。
- ADMIN 层、bulk/rename 族、其余延后写工具 → 维持 P2 延后清单不变。
- P1/P2 资产不重构：writes.py/_write_common.py/审批门/审计零修改（仅 import 复用）。

## Further Notes

- 术语一律按 CONTEXT.md：审批门、权限层级、dry-run、审计、project context；「tool」指本 spec 的两个新工具；工程对话称「工作会话」。
- 与 ADR 的关系：ADR-0001 无冲突（MCP 为核 + OpenAI 导出不变）；ADR-0002 为 verb 词汇表扩展（draft），同形歧义已显式声明（①）；开发会话完成后回写实现注记。
- 许可证边界：本地 lint 独立重写（不复制 reqmesh GPL 源码），等价性靠「本地分 == 服务端分」冒烟对账（事实 3、验收 4）。
- 开发会话按 design §5：实施后自动启动审核子代理与测试子代理；每轮循环结论记对应 ticket comment；超 5 轮仍失败回到需求会话（入口即交接文本）。
