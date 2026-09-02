# 工具命名与分组：verb_entity，无权限前缀

P1 需求会话对开放问题「工具命名前缀与分组方式」做出决策：MCP server 名定为 `reqmesh`（ADR-0001 已示 `mcp__reqmesh__<tool>`），工具名统一为 `<verb>_<entity>` snake_case，**不在工具名中携带权限层级前缀**；权限层级记录在工具注册表（唯一事实源）、MCP `annotations.readOnlyHint` 与工具 description（READ 层工具一律以 `READ-ONLY` 开头），P2 的审批门从注册表映射层级而非解析名字。分组按实体域（认证/项目、需求、追踪/覆盖、风险/决策、验证/分析/规格/定义、组件/基线/变更请求、报告）进行，在 MCP `tags` 与 spec 分节中呈现。

## Considered Options

- **权限前缀（`read_`/`mutate_`…）**：拒绝。与 MCP server 前缀叠加后冗长（`mcp__reqmesh__read_list_requirements`），且名字与层级双轨记录容易漂移；层级是护栏的属性，应单点维护在注册表。
- **纯动词前缀、每端点一工具**：拒绝。158 条路径会产生 80+ 工具，超出模型可操作范围；改为语义合并（见下）。

## Consequences

- verb 词汇表固定并按层级扩展：READ = `list` / `get` / `search`；P2 起新增 `create` / `update` / `delete` 等写动词。
- 合并模式：次要实体的 list 工具接受可选 `<entity>_id` 参数（省略返回集合，给出返回单条）；计算型报告合并为一个工具 + `report` 枚举参数。
- 护栏（P2）不得依赖名字推断权限层级，必须查注册表。
- 工具 description 使用中文书写（与仓库文档语言一致），标识符保持英文。

## 实现注记（P1 开发会话核实后回写）

MCP 协议的低层 Tool 类型（mcp 0.5.0 / 1.x）**没有 `tags` 字段**，因此「分组 tags」落地为：实体域作为 `meta.domain`、权限层级作为 `meta.permission` 随 `tools/list` 下发（对客户端可见），注册表仍是分组的唯一来源（OpenAI 导出与测试同源）。P2 审批门按本 ADR 从注册表映射层级。

## 实现注记（P2 开发会话回写：verb 词汇表扩展）

- 按 ADR 预告，「P2 起新增写动词」落地为：`create` / `update` / `set` / `run` / `review`（12 个写工具 = 6 DRAFT + 6 MUTATE）；`delete` 词汇表预留 ADMIN 层（P2 未启用）。
- description 前缀按层级（ADR 既定约定扩展）：READ 层 `READ-ONLY`（P1 惯例）、DRAFT 层 `DRAFT`、MUTATE 层 `MUTATE`（ADMIN 预留 `ADMIN`）；中文书写不变。
- 写工具参数字典事实：全部写工具统一 `dry_run: bool = False`；全部 MUTATE 工具统一必填 `reason: str`（只进审计，不进 reqmesh 数据）；create 类 `id` 由调用方给定（reqmesh 契约如此）——与 spec 映射表逐项对账（tests/mapping.py）。
- 审批门（P2）按本 ADR 从注册表 `level` 映射层级（DRAFT 通配/MUTATE 必匹配 project），**绝不解析工具名推断权限**——写工具名无权限前缀，符合本 ADR。

## 实现注记（P3 开发会话回写：verb 词汇表扩展 `draft`）

- 按 ADR 预告的「按层级扩展动词」机制，P3 新增白名单外动词 **`draft`（起草）**：
  `draft_requirement` = 复合技能①（NL→EARS 句式→本地 quality lint 闭环保→落库），
  注册表 level=DRAFT、domain=复合技能（P4 复合技能②并入）；`delete` 仍预留 ADMIN 层（P3 未启用）。
- **`draft_` 前缀与 DRAFT 权限层级的同形歧义（显式声明，非冲突）——开发会话核实后的消解依据**：
  ① `draft` 是动词（起草草稿），不是权限层级前缀——本 ADR 禁止的是「以权限层级作为
  命名前缀」（read_/mutate_ 类），动词在词汇表内扩展属既定机制（P2 的 create/update/set/run/review
  同款）；② 审批门从注册表 `level` 映射层级、**绝不解析工具名**（本 ADR 硬规则），
  同形前缀在护栏语义上零影响；③ 词义一致：DRAFT 层=「草拟但未生效」，draft=起草草稿。
  本消解规则对后续所有「层级词形 == 动词」的候选命名生效。
- P3 新增工具参数事实：`draft_requirement` 提供 `nl_text`（受控自然语言）与 `template`
  （EARS 句式显式覆盖，默认 auto 自动检测）；`require_measurable=false` 为显式豁免
  untestable 的开关（默认 true）；`dry_run` 语义与 P2 完全一致（照跑审批门）。
- description 前缀惯例不变：DRAFT 层工具以 `DRAFT` 开头（中文书写；READ 层
  `READ-ONLY` 不变——`get_requirement_quality` 属 READ 层）。

## 实现注记（P4 开发会话回写：复合技能②并入 + 不扩展 report 枚举）

- **新工具并入 domain=复合技能（兑现 P3 预告）**：`get_traceability_gap_report`
  （P4 复合技能②：追踪/覆盖缺口报告）注册表 domain=复合技能、level=READ——P3 注记
  「domain=复合技能（P4 复合技能②并入）」落定。verb=`get`（READ 词汇表内，
  **零动词扩展**），实体对齐 `get_project_report` 的「报告作实体后缀」惯例。
- **不扩展 get_project_report 的 report 枚举（对 P1 资产的零改动边界，非破坏）**：
  `get_project_report` = reqmesh **服务端计算型报告端点**的 1:1 路由（
  `_REPORT_ROUTES`）+ envelope 透传（P1 契约）；P4 报告 = harness **客户端多源聚合**
  （coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix 六源，无任何
  单一上游端点可路由）——两种计算模型。若并入枚举：① 破坏「枚举成员 1:1 对应一个路由」
  契约（映射表测试不可执行）；② 破坏 envelope 透传契约（聚合产物不是任何端点的响应）。
  因此独立工具；P1 预告的《reference freshness/conflicts/backlog/pugh/risk-bingo》
  五个**服务端**端点仍在 0.5.0 快照中，属未来 phase 的合法枚举扩展对象（P4 不消费）。
- 实现细节补记：`dimensions` 白名单参数 = `list[Literal[12 类维度]]`（可选，默认
  None）；12 类维度类型值与建议模板表（spec ③）逐行 1:1，其中 `coverage.uncovered`
  按 need 分两型（`coverage.uncovered:design` / `coverage.uncovered:verification_case`，
  严重度不同）——spec 表类型列背引号部分为 `coverage.uncovered`，need 注记在单元格内；
  本实现把 need 并入类型值以保证 Literal 枚举 12 值逐值对应（开发会话解释，待需求会话确认）。
