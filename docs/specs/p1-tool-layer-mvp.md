# P1 spec：reqmesh-harness 工具层 MVP

> 状态：需求会话产出，待开发会话实施。
> 入口：design [`docs/reqmesh-harness-design.md`](../reqmesh-harness-design.md) · epic [#1](https://github.com/GuangjieYu1/PRDMS/issues/1) · 术语 [`CONTEXT.md`](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md) · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md)
> 交接：见 [`docs/handoffs/p1-tool-layer-mvp.md`](../handoffs/p1-tool-layer-mvp.md)

## Problem Statement

reqmesh 部署在 `http://172.16.100.2:8000`（git 原生 YAML 存储，约 158 条路径/201 个操作），但没有面向 LLM 的访问层：模型无法自己完成登录、维护 Cookie/CSRF 会话、理解 80+ 个 GET 端点并把它们当作安全（只读）的语义化工具调用。PRDMS 需要一个最小可运行形态：认证客户端 + 全部 READ 工具 + MCP 双 transport，并对 cessna-172 演示项目跑通「登录→查需求→查覆盖率」冒烟。

## Solution

在 PRDMS 仓库内新建 `reqmesh-harness/`（Python 包 `reqmesh_harness`，Python 3.11，uv 管理），交付三块：

1. **认证客户端**：登录/登出、Cookie+CSRF 会话维护、会话持久化、401 自动重登（一次）、Bearer 兜底，凭据来自环境变量。
2. **READ 工具全集（25 个）**：盘点 84 个 GET 端点后按 ADR-0002 语义合并为 25 个工具，经工具注册表（唯一事实源）统一驱动 MCP 注册、OpenAI function JSON 导出与测试；工具在结构上只暴露 GET，保证只读无副作用。
3. **MCP 骨架**：`mcp` SDK（FastMCP），server 名 `reqmesh`，stdio 与 streamable-HTTP 双 transport 均可启动并列出工具。

冒烟：对 `http://172.16.100.2:8000` 的 cessna-172 项目跑「登录 → whoami → 列出项目 → 查需求（57 条）→ 查覆盖率 → 缺口分析」，记录通过凭据落盘。

## User Stories

1. As an LLM agent, I want the harness to authenticate against reqmesh with configured credentials, so that I never handle cookies, CSRF tokens, or re-login myself.
2. As an LLM agent, I want a `whoami` tool, so that I can verify the harness's identity and role before doing anything else.
3. As an LLM agent, I want to list projects, so that I can discover project ids (e.g. `cessna-172`) to scope later calls.
4. As an LLM agent, I want project details for one project, so that I can read its metadata and state summary.
5. As an LLM agent, I want to list requirements with filters (search / type / status / priority / offset / limit), so that I can find the requirements relevant to a question.
6. As an LLM agent, I want to fetch a single requirement by id, so that I can quote or reason about its exact content.
7. As an LLM agent, I want to search across project entities with a query string, so that I can resolve fuzzy references like "the requirement about fuel".
8. As an LLM agent, I want the requirement tree, so that I understand parent/child structure before editing or analyzing.
9. As an LLM agent, I want the change history of any entity, so that I can audit when and why something changed.
10. As an LLM agent, I want to read comments on an entity, so that I can surface discussion context.
11. As an LLM agent, I want the list of unreviewed requirements, so that I can drive review workflows.
12. As an LLM agent, I want the trace matrix, so that I can reason about relations between requirements, verification cases, and components.
13. As an LLM agent, I want backlinks for a specific entity, so that I can answer "what points at this?".
14. As an LLM agent, I want coverage analysis, so that I can report how well requirements are covered.
15. As an LLM agent, I want gap analysis, so that I can identify uncovered or under-covered requirements.
16. As an LLM agent, I want the allocation matrix (with axis/row filters), so that I can see which components satisfy which requirements.
17. As an LLM agent, I want suspect links, so that I can find trace links that went stale after edits.
18. As an LLM agent, I want the risk register (with optional single-risk lookup), so that I can read risk entries.
19. As an LLM agent, I want the risk matrix, so that I can see likelihood × severity placement of requirements.
20. As an LLM agent, I want to list decisions, so that I can read the decision log.
21. As an LLM agent, I want to list verification cases, so that I can read verification coverage by case.
22. As an LLM agent, I want to list analysis cases, so that I can read analysis results.
23. As an LLM agent, I want to list specifications and definitions, so that I can read spec documents and the project glossary.
24. As an LLM agent, I want to list components (flat or tree), so that I can navigate the component hierarchy.
25. As an LLM agent, I want to list baselines, so that I can see project milestones and their due dates.
26. As an LLM agent, I want to list change requests, so that I can read pending changes.
27. As an LLM agent, I want computed project reports (quality / compliance / metrics / evaluation / validation / workflow), so that I can summarize project health in one call.
28. As a developer, I want every tool to be read-only by construction (the tool layer can only issue GET), so that no P1 tool call can ever mutate reqmesh state.
29. As a developer, I want the whole unit test suite to run offline against recorded fixtures, so that tests don't depend on the LAN instance.
30. As a developer, I want deterministic pydantic model generation from the vendored openapi.json, so that regenerating never produces drift.
31. As an operator, I want to start the MCP server over stdio and over streamable-HTTP and list all tools on both, so that both transports are proven.
32. As a developer, I want OpenAI function-calling JSON exported from the same registry, so that a future runtime reuses the tools at zero cost.
33. As a developer, I want a repeatable smoke run against cessna-172 with a recorded pass log, so that P1's acceptance is verifiable.

## Implementation Decisions

### 工具集盘点（84 个 GET → 25 个工具）

epic 预估「约 22 个」，本会话盘点后的定案为 **25 个**：次要实体的 list/get 按 ADR-0002 合并（可选 `*_id` 参数），计算型报告合并为一个工具 + 枚举参数；语义差异大的资源（需求树、风险矩阵、缺口分析等）保持独立。映射表即实现契约（`project_id` 为必填 path 参数，所有工具均暴露；`offset`/`limit` 透传 reqmesh 分页，默认 500/上限 2000，自动翻页属 P3/P4 复合技能）：

| # | 工具名 | 端点（GET） | 参数（除 `project_id` 必填外） |
|---|--------|-------------|-------------------------------|
| 1 | `whoami` | `/api/auth/whoami` | — |
| 2 | `list_projects` | `/api/projects`；`project_id` 给出时 `/api/projects/{project_id}` | `project_id`? |
| 3 | `list_requirements` | `/api/projects/{project_id}/requirements` | `search`? `type`? `status`? `priority`? `offset`? `limit`? |
| 4 | `get_requirement` | `/api/projects/{project_id}/requirements/{req_id}` | `req_id`* |
| 5 | `search_requirements` | `/api/projects/{project_id}/search` | `q` `kind`? |
| 6 | `get_requirement_tree` | `/api/projects/{project_id}/requirements/tree` | — |
| 7 | `get_item_history` | `/api/projects/{project_id}/history/{item_id}` | `item_id`* |
| 8 | `list_comments` | `/api/projects/{project_id}/comments` | `entity_kind`? `entity_id`? `offset`? `limit`? |
| 9 | `get_unreviewed_requirements` | `/api/projects/{project_id}/unreviewed` | — |
| 10 | `get_traces` | `/api/projects/{project_id}/traces`；`entity_id` 给出时 `/api/projects/{project_id}/entities/{entity_id}/backlinks` | `entity_id`? `collection`? |
| 11 | `get_coverage` | `/api/projects/{project_id}/coverage` | — |
| 12 | `get_gap_analysis` | `/api/projects/{project_id}/gap-analysis` | — |
| 13 | `get_allocation_matrix` | `/api/projects/{project_id}/allocation-matrix` | `axis`? `rows`? `search`? `filter_type`? |
| 14 | `get_suspect_links` | `/api/projects/{project_id}/suspect-links` | — |
| 15 | `list_risks` | `/api/projects/{project_id}/risks`；`risk_id` 给出时 `/risks/{risk_id}` | `risk_id`? `offset`? `limit`? |
| 16 | `get_risk_matrix` | `/api/projects/{project_id}/risk-matrix` | — |
| 17 | `list_decisions` | `/api/projects/{project_id}/decisions`；`dec_id` 给出时 `/decisions/{dec_id}` | `dec_id`? `offset`? `limit`? |
| 18 | `list_verification_cases` | `/api/projects/{project_id}/verification`；`vc_id` 给出时 `/verification/{vc_id}` | `vc_id`? `offset`? `limit`? |
| 19 | `list_analysis_cases` | `/api/projects/{project_id}/analysis`；`case_id` 给出时 `/analysis/{case_id}` | `case_id`? `offset`? `limit`? |
| 20 | `list_specifications` | `/api/projects/{project_id}/specifications`；`spec_id` 给出时 `/specifications/{spec_id}` | `spec_id`? `offset`? `limit`? |
| 21 | `list_definitions` | `/api/projects/{project_id}/definitions`；`def_id` 给出时 `/definitions/{def_id}` | `def_id`? `offset`? `limit`? |
| 22 | `list_components` | `/api/projects/{project_id}/components`；`as_tree=true` 时 `/components/tree`；`component_id` 给出时 `/components/{component_id}` | `component_id`? `search`? `type`? `satisfies`? `as_tree`? `offset`? `limit`? |
| 23 | `list_baselines` | `/api/projects/{project_id}/baselines` | — |
| 24 | `list_change_requests` | `/api/projects/{project_id}/change-requests`；`cr_id` 给出时 `/change-requests/{cr_id}` | `cr_id`? `offset`? `limit`? |
| 25 | `get_project_report` | 按 `report` 枚举路由：`quality` `/quality` · `compliance` `/compliance` · `metrics` `/metrics` · `evaluation` `/evaluation` · `validation` `/validate` · `workflow` `/workflow` | `report`*（enum） |

（`?` 可选，`*` 必填。）

### 开放问题 ①：openapi.json → pydantic 模型生成方案（已决策）

**决策：`datamodel-code-generator`（dev 依赖，uv.lock 锁版本）+ vendored 快照 + 提交生成产物。**

- 快照：`reqmesh-harness/openapi/reqmesh-0.5.0.json`（本会话已从 `172.16.100.2:8000/openapi.json` 抓取并入库），生成脚本 `scripts/gen_models.py` 输出到 `client/generated/`，**生成产物提交进仓库且禁止手改**（头部注明生成器与来源快照），再生成为确定性操作（diff 为空）。
- 关键事实：reqmesh 的 openapi 文档化了 79 个组件 schema（`Requirement`、`Risk` 等实体 + 全部请求体），但 **响应体 schema 全部为空 `{}`**（184 个操作只声明 `application/json` 不声明形状）。因此生成模型的 P1 职责是：① 实体/请求体模型供 P2 写路径复用；② 对测试 fixture 中形状已知的实体（如 `Requirement`）做解析校验。**P1 工具层返回原始 JSON 透传**，类型化输出模型留到 P3/P4 按真实响应手写窄模型 + golden 校验。
- 备选方案与拒绝理由：`openapi-python-client`（整套客户端生成）——拒绝：自带 HTTP 客户端与认证方式，与设计文档要求的 httpx + Cookie/CSRF 薄客户端冲突，且响应 schema 为空导致其生成的响应模型同样无价值；手写全部模型——拒绝：实体多、漂移风险高；从 reqmesh GPL 源码复制 pydantic 模型——拒绝：许可证边界，openapi.json 是既定的契约边界（D3）。

### 开放问题 ②：工具命名前缀与分组（已决策）

见 [ADR-0002](../adr/0002-tool-naming-and-grouping.md)：server 名 `reqmesh`；`<verb>_<entity>` snake_case；无权限前缀（层级在注册表 + `readOnlyHint` + description，description 以 `READ-ONLY` 开头）；verb 词汇表 `list`/`get`/`search`；按实体域分组（`tags`）。description 用中文书写。

### 认证客户端契约

- 登录：`POST /api/auth/login`，body `{username, password}`；成功响应携带 `Set-Cookie: token`(HttpOnly JWT) + `csrftoken` cookie + body `csrf_token`（已核实，见 design §7）。
- 会话维护：httpx `CookieJar` 持久化到 XDG state 目录会话文件（重启 MCP server 后免重登，加载后以 `whoami` 校验，失效则重新登录）；`csrf_token` 一并持久化，供 P2 写请求挂 `X-CSRF-Token`。
- 认证回退：`Authorization: Bearer <token>` 亦受支持（reqmesh 已验证），作为 cookie 之外的兜底路径。
- 401 处理：首次 401 → 自动重登一次并重试；仍 401 → 抛类型化错误（凭据/会话失效），工具以 MCP tool error 返回诊断，不泄露密码。
- 凭据：环境变量 `REQMESH_USERNAME` / `REQMESH_PASSWORD`，由 pydantic-settings 读取（支持 `.env`，已 gitignore）；仓库内不落任何真实凭据。

### 客户端与只读护栏

- 薄客户端：`client/` 模块用 httpx 实现，仅工具层可见；工具层拿到的是只暴露 `get()` 的只读视图——**结构上不存在非 GET 路径**（P2 再引入经审批门包装的写视图）。
- 超时与重试：默认 30s（环境变量可调）；仅幂等 GET 允许有限重试（连接错误），401 按上节处理。

### MCP 骨架与工具注册表

- `mcp` 官方 SDK（FastMCP），server 名 `reqmesh`；stdio 为默认 transport，streamable-HTTP 经 ASGI app 挂载（stateless：每个请求作用域内构建客户端会话，会话文件共享，无服务端长驻项目上下文——project context 属 P5 memory 范围）。
- **注册表是唯一事实源**：每个工具在注册表中声明 name（ADR-0002）、description（`READ-ONLY` 开头、中文）、层级 `READ`、域 `tags`、输入 pydantic schema、处理器。注册表驱动三处：MCP 工具注册、OpenAI function JSON 导出、schema/只读测试。
- OpenAI 导出：导出 `{name, description, parameters}`，名称满足 `^[a-zA-Z0-9_-]{1,64}$`，parameters 为 OpenAI 可接受的 JSON Schema 子集；与 MCP 侧做 1:1 对账测试（无工具丢失）。

### 配置项（环境变量，pydantic-settings）

`REQMESH_BASE_URL`（默认 `http://172.16.100.2:8000`）、`REQMESH_USERNAME`、`REQMESH_PASSWORD`、`REQMESH_TIMEOUT`（默认 30）、`REQMESH_SESSION_FILE`（默认 XDG state）、HTTP transport：`REQMESH_HARNESS_HOST`/`REQMESH_HARNESS_PORT`（默认 `127.0.0.1:8123`；正式部署端口是 P6 开放问题）。

### 冒烟

- 脚本 `scripts/smoke_p1.py`（network-tagged，不进单元测试集）：登录 → `whoami` → `list_projects`（断言含 `cessna-172`）→ `list_requirements`（断言 `total == 57`，与 design §7 基线一致）→ `get_coverage` → `get_gap_analysis` → `get_traces`，全程 200。
- 记录落盘 `docs/smoke/P1-cessna-172.md`：时间戳、实例 URL、每步结果与关键计数、无副作用声明。此记录即 epic 要求的「冒烟通过记录」。

## Testing Decisions

- 好测试的标准：只测外部行为——工具 schema 合法、返回 envelope 透传正确、只发 GET、认证状态机正确；不测内部实现细节（httpx 调用方式等）。
- 全部单元测试离线运行：HTTP 一律用 `respx` 打桩，样例响应以 fixture 文件形式入库（来源：真实实例抓取的脱敏样本 + 手工构造的边界样本）。
- 模块级测试职责：
  - 认证：登录成功（cookie+csrf 捕获）、密码错误 → 类型化错误、401 → 重登一次成功、重登失败 → 报错、持久化会话文件失效 → 回落登录。
  - 工具：25 个工具逐一 schema 校验（输入 schema 与映射表一致；输出为 JSON envelope）＋ 只读断言（会话中出现的 HTTP 方法 ⊆ {GET}）。
  - MCP：stdio 与 streamable-HTTP 分别「启动 → list tools（25 个，name/description/readOnlyHint 齐全）→ 调用 `list_requirements`（打桩后端）→ 返回 envelope」。
  - 导出：OpenAI JSON 全部导出、名称合规、parameters 过 `jsonschema` 校验、与 MCP 注册表 1:1 对账。
  - 生成：`scripts/gen_models.py` 重跑后 diff 为空；fixture 中 `Requirement` 样本过生成模型解析。
- 无既有测试先例（本仓库尚无 harness 代码）；沿用 reqmesh 后端的 pytest 风格（断言外部行为、fixture 文件化）。

## Out of Scope

- 写路径：MUTATE/DRAFT/ADMIN 工具、审批门、dry-run、专用服务账号开通（P2，D6/D7）。
- 复合技能：自然语言建需求（EARS + quality lint）、追踪/覆盖缺口报告（P3/P4）。
- 内置运行时：agent loop、provider、loopback RPC、memory/project context（P5）。
- CI/evals/部署/文档发布（P6）。
- 延后的 READ 端点（P1 不包装，注明去向）：
  - 管理/系统域 → P6：auth users 列表/导出、settings、public-config、system info/dependencies/latex/update、demo-project、git key/log/status、presence、events、activity。
  - 执行/产出型（服务端计算或产文件）→ P3/P4/P6 按需：analysis case run、publish/download、BOM 导出、test-results/sample。
  - 写流程辅助 → P2/P3：next-uid/next-id、requirement fingerprint/value/impact/components、CR redline、baseline diff。
  - 分析扩展 → P3/P4（`get_project_report` 的 `report` 枚举可扩充）：reference freshness、conflicts、backlog、pugh、risk-bingo。
  - 非数据 API：SPA 页面、/health、/ready、/version、/api/version。

## Further Notes

- 分页透传：工具不做自动翻页（P3/P4 复合技能按需实现），description 注明默认 limit=500。
- 开发会话按 design §5 流程：实施后自动启动审核与测试子代理；失败轮次在对应 ticket comment 记录结论摘要；超 5 轮回流需求会话。
- 术语一律按 `CONTEXT.md`：本仓库语境「session」只指运行时会话，工程对话称「工作会话」；「tool」指封装操作，不与 DSH 的「技能」混用。
- 生成模型不可手改；若 reqmesh 升级导致快照过期，重新抓取快照 + 重跑生成脚本，并在 PR 说明 diff。
