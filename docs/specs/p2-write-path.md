# P2 spec：reqmesh-harness 写路径（MUTATE/DRAFT 工具 + 审批门 + dry-run + 审计）

> 状态：需求会话产出，待开发会话实施。
> 入口：design [`docs/reqmesh-harness-design.md`](../reqmesh-harness-design.md) · epic [#2](https://github.com/GuangjieYu1/PRDMS/issues/2) · 术语 [`CONTEXT.md`](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md) · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md) · P1 spec [`docs/specs/p1-tool-layer-mvp.md`](p1-tool-layer-mvp.md)
> 交接：见 [`docs/handoffs/p2-write-path.md`](../handoffs/p2-write-path.md)

## Problem Statement

P1 交付了认证客户端 + 25 个 READ 工具 + MCP 双 transport，但工具层结构上只有 GET：模型可以读需求、算覆盖率，却无法创建/更新任何实体，且没有任何写护栏。P2 要为 reqmesh-harness 增加受控写路径：DRAFT/MUTATE 写工具（design D6 四级权限中除 ADMIN 外的两层）+ 审批门（fail-closed）+ dry-run 预览 + 工具调用级审计日志，并接通 D7 的专用 contributor 服务账号。ADMIN 层（删除、执行变更请求、freeze 基线、git push/restore、publish 等）默认不在 P2，但须落好「显式开启」的预留机制。

## Solution

在 P1 的 reqmesh-harness 上新增四块：

1. **写路径客户端**：`AuthSession` 增 post/put/patch/delete（挂 `X-CSRF-Token`）；`WriteClient` 写视图需要审批门签发的 GateToken 才能构造（与 P1 只读视图对称的结构护栏）；PUT 复用 P1 生成模型按 `exclude_unset` 语义发部分更新。
2. **12 个写工具**（6 DRAFT + 6 MUTATE，见映射表）：经工具注册表（唯一事实源，level 字段已预留四级）统一驱动 MCP 注册、OpenAI 导出与测试；每个写工具统一 `dry_run` 参数。
3. **guardrails 模块**：白名单审批门（fail-closed）+ `approvals` CLI 子命令（交互式维护白名单）+ ADMIN 显式开启预留 + JSONL 审计日志。
4. **服务账号**：约定专用账号 `reqmesh-harness`（role=contributor），凭据仅环境变量注入。

冒烟：对 `http://172.16.100.2:8000` 的 cessna-172 项目跑两段式验证（A 段全量 dry_run 断言 + B 段最小真实写闭环），记录落盘。

## User Stories

1. As an LLM agent, I want a `create_requirement` tool, so that I can draft a new requirement in a project (P3 自然语言建需求的前置)。
2. As an LLM agent, I want a `review_item` tool, so that I can submit review on a requirement (P3 EARS/quality lint 闭环的一环)。
3. As an LLM agent, I want `update_requirement` / `set_relations` / `set_allocation` tools, so that I can maintain requirement content, the trace matrix and allocations (P4 追踪维护的前置)。
4. As an LLM agent, I want `create_component` / `update_component` tools, so that I can maintain the component hierarchy.
5. As an LLM agent, I want `create_verification_case` / `update_verification_case` / `run_verification` tools, so that I can register verification and record executions.
6. As an LLM agent, I want a `create_risk` tool, so that I can add risk entries to the register.
7. As an LLM agent, I want a `create_comment` tool, so that I can attach discussion context to any entity.
8. As an operator, I want every DRAFT/MUTATE call to be checked against an approval whitelist before any HTTP request leaves the harness, so that unapproved writes are blocked by construction.
9. As an operator, I want an interactive `approvals` CLI to add/remove whitelist entries, so that I never edit TOML by hand.
10. As an operator, I want `dry_run=true` on every write tool to compute and show what would be sent without writing to reqmesh, so that I can preview writes (including git impact: none) before approval.
11. As an auditor, I want every write tool call recorded in an append-only JSONL audit log with tool name, parameter summary, dry-run flag, gate decision and result status, so that every write attempt is traceable.
12. As an operator, I want the harness to write as a dedicated `reqmesh-harness` contributor account whose credentials live only in environment variables, so that the harness never uses personal or admin accounts.
13. As a developer, I want the ADMIN layer to be absent from the tool surface unless `REQMESH_ENABLE_ADMIN=1` is set, so that destructive endpoints are opt-in by construction.

## Implementation Decisions

### 开放问题①：MUTATE 工具细分清单（已决策）

**P2 圈定 12 个写工具**（6 DRAFT + 6 MUTATE），从 design §4 候选清单中按「P3/P4 旗舰用例的写依赖 + 危险度」圈定：

- 层级语义（写入 spec，审批门按此裁决）：
  - **DRAFT**：新建实体/提交评审——只增不改，不改动既有内容，git 影响为新增文件，撤销成本低。
  - **MUTATE**：修改既有实体、重写关系矩阵/分配、追加执行记录——影响追踪/覆盖计算结果，git 影响为既有文件改写。
  - **ADMIN**：删除、执行变更请求、freeze 基线、git push/restore、publish 等不可逆/管理动作（默认不在 P2，预留机制见下）。

#### 映射表（实现契约）

| # | 工具名 | 端点 | 方法 | 层级 | 请求体模型（P1 生成） | 参数（除 `project_id`*、`dry_run`? 统一外） | 冒烟断言点（cessna-172） |
|---|--------|------|------|------|------------------------|---------------------------------------------|--------------------------|
| 1 | `create_requirement` | `/api/projects/{project_id}/requirements` | POST | DRAFT | `RequirementCreate` | `id`* `name`? `description`? `type`? `priority`? `status`? `parent`? `attributes`? `parameters`? `relations`? 等（按生成模型） | dry_run 返回 would_send + id 冲突检查；真实写后 `get_requirement` 回读一致 |
| 2 | `create_component` | `/api/projects/{project_id}/components` | POST | DRAFT | `ComponentCreate` | `id`* `name`? `description`? `type`? `parent`? 等 | dry_run；真实写后 `list_components` 可见 |
| 3 | `create_verification_case` | `/api/projects/{project_id}/verification` | POST | DRAFT | `VerificationCaseCreate` | `id`* `name`? `description`? `method`? `case_type`? 等 | dry_run；真实写后 `list_verification_cases` 可见 |
| 4 | `create_risk` | `/api/projects/{project_id}/risks` | POST | DRAFT | `RiskCreate` | `id`* `title`? `failure_mode`? `effect`? `cause`? `severity`? `likelihood`? | dry_run；真实写后 `list_risks` 可见 |
| 5 | `create_comment` | `/api/projects/{project_id}/comments` | POST | DRAFT | `CommentCreate` | `entity_kind`* `entity_id`* `text`*（工具层强制；上游 schema 未标 required） | dry_run；真实写后 `list_comments` 可见该条 |
| 6 | `review_item` | `/api/projects/{project_id}/requirements/{req_id}/review` | POST | DRAFT | `ReviewRequest` | `req_id`* `comment`? | dry_run；真实写后 `get_unreviewed_requirements` 不含该需求 |
| 7 | `update_requirement` | `/api/projects/{project_id}/requirements/{req_id}` | PUT | MUTATE | `RequirementUpdate` | `req_id`* `reason`* + 全部可空字段（`exclude_unset`） | dry_run；真实改 `description` 后回读生效 |
| 8 | `set_relations` | `/api/projects/{project_id}/traces` | PUT | MUTATE | `TraceMatrix` | `links`*（`reason`*） | dry_run；真实写读-改-写回放（追加 SMOKE 链接后 `get_traces` 可见） |
| 9 | `set_allocation` | `/api/projects/{project_id}/allocation` | POST | MUTATE | `AllocationRequest` | `req_id`* `row_id`? `row_kind`? `target_id`? `component_id`? `axis`? `allocated`?（`reason`*） | dry_run；真实写后 `get_allocation_matrix` 回读 |
| 10 | `update_component` | `/api/projects/{project_id}/components/{component_id}` | PUT | MUTATE | `ComponentUpdate` | `component_id`* `reason`* + 可空字段 | dry_run；真实改 `description` 后回读生效 |
| 11 | `update_verification_case` | `/api/projects/{project_id}/verification/{vc_id}` | PUT | MUTATE | `VerificationCaseUpdate` | `vc_id`* `reason`* + 可空字段 | dry_run；真实改后回读生效 |
| 12 | `run_verification` | `/api/projects/{project_id}/verification/{vc_id}/run` | POST | MUTATE | `RunVerification` | `vc_id`* `status`* `notes`? `step_results`?（`reason`*） | dry_run；真实跑后 case 的 `execution_history` 追加记录 |

- 约定：`?` 可选、`*` 必填；**所有写工具统一携带 `dry_run: bool = False`**；**所有 MUTATE 工具统一携带必填 `reason: str`**（记入审计日志，不进 reqmesh 数据）。create 类工具的 `id` 由调用方给定（reqmesh 契约如此；`next-uid`/`next-id` 端点仍延后，见下）。
- 请求体序列化统一走 P1 生成的 pydantic 模型（`RequirementCreate/Update`、`TraceMatrix`、`AllocationRequest`、`ReviewRequest`、`RunVerification`、`ComponentCreate/Update`、`VerificationCaseCreate/Update`、`RiskCreate`、`CommentCreate`——openapi 快照内全部齐备，已核实）。

#### 延后清单（明确写出端点去向，开发会话不得擅自加工具）

- **同框架后续行（P3/P4 按需，只加注册行、零新门代码）**：`update_risk`（PUT `/risks/{risk_id}`）、`create/update_decision`、`create/update_analysis_case`、`create/update_specification`、`create/update_definition`、`create/update_change_request`、`review_all`（P3 quality lint 用循环 `review_item` 替代）。
- **bulk/结构操作**（影响面大，P3/P4 按需）：`requirements/bulk`、`bulk-reparent`、`bulk-delete`、`components/bulk`、`risks/bulk`、`verification/bulk`、`specifications/bulk`、各 `rename`、`cascade`/`break-cascade`、`history restore`、`suspect-links/clear`、`system-states` 写族、`parameters rename`。注：`BulkReparentRequest` 与两个 import 端点原生带 `dry_run` 布尔参数（已核实 openapi）——未来包装这些端点时**优先复用原生 dry_run 参数**而非本地组装。
- **预览端点（dry-run 对齐时优先复用）**：CR `redline`（GET）、baseline `diff`（GET）——P3/P4 引入对应写工具时按「原生预览端点优先」规则对齐，见 dry-run 语义节。
- **ADMIN 层（默认不在 P2，显式开启预留）**：全部 16 个 DELETE（requirement/component/verification/risk/decision/analysis/specification/definition/comment/change-request/baseline/system-states/项目/用户）、CR `execute`/`reject`、baseline `freeze`、baselines `create`/`order`、`git/init|push|restore|key|key/rotate|remote|test-remote`、`publish`/`download`、`import`、`test-results/import`、projects `create`/`update`/`delete`、`auth/users/*` 管理族、`system/*` 设置/更新/重启/reseed、`hooks/*`。
- **写流程辅助 READ 端点**：`requirements/next-uid`、`{kind}/next-id`（P1 已延后至 P2/P3）——P3 建需求技能如需唯一 id 再按需包装（P2 不包）。
- **认证写端点**（`register`/`guest`/`forgot`/`reset`/`verify` 等）：永不工具化——认证状态是客户端层的职责（P1 契约），不暴露给模型。

#### ADMIN「显式开启」预留设计（P2 实现机制，不注册任何 ADMIN 工具）

1. 注册表增加**分区**概念：ADMIN 行的 `level="ADMIN"` 且落在独立 section；`build_registry()` 默认**不安装** ADMIN 行——`REQMESH_ENABLE_ADMIN=1` 时才安装。
2. 未开启时 ADMIN 工具**不出现在 `tools/list`**（协议层不存在，而非调用时才拒绝）；开启后仍卡两道（D6「危险操作卡两道」= D7「admin 动作显式开启」+ 白名单条目，缺一不可）。
3. `annotations_for("ADMIN")` → `readOnlyHint=False, destructiveHint=True`（`ToolAnnotations.destructiveHint` 已核实存在于 mcp SDK）。
4. 未来 phase 上线 ADMIN 工具 = spec 映射表加行 + 注册表加行，审批门零改动。

### 开放问题②：审批门交互形态（已决策）

**决策：两者分层组合——配置文件白名单是唯一裁决源（P2 落地），CLI 交互确认的形态是独立子命令 `reqmesh-harness approvals`（交互式维护白名单），「调用中途弹窗确认」延后到 P5。**

- **理由**：
  1. MCP stdio 的 stdin/stdout 是 JSON-RPC 协议通道，服务器在工具调用中途向终端索要确认会破坏协议流；streamable-HTTP 是无终端的无头服务。纯「调用中途 CLI 确认」对双 transport 结构上不可行，不能作为唯一机制。
  2. 无头确定性（白名单裁决）保证 P5 agent loop 与冒烟/测试可重复执行；审批门每次调用时按当前白名单 fail-closed 裁决。
  3. 白名单文件是持久化的操作员意图；CLI `approvals add` 子命令带 TTY 时交互询问 y/N（`--yes` 供脚本），与手改 TOML 同源同文件——两个入口、一个裁决源，没有双轨漂移。
  4. MCP elicitation（client 弹窗）依赖 experimental API 与客户端支持（DSH 未验证），且 design §6 已把「审批门交互时序」列为 P5 开放问题——届时在 agent loop 里评估，P2 不做。
- **DRAFT 与 MUTATE 两层差异处理**：

| 维度 | DRAFT | MUTATE |
|---|---|---|
| 语义 | 新建实体/提交评审（只增不改） | 修改既有实体/矩阵/分配/执行记录 |
| 白名单条目 | `tool` 必填；`project` 可省略（=通配全部项目） | `tool` 必填 + `project` 必填具体 `project_id`（禁止通配） |
| `reason` 参数 | 不强制 | 必填（记入审计日志） |
| `dry_run` | 支持（默认 false） | 支持（默认 false） |
| `dry_run_only` 条目 | 支持 | 支持（强制仅预览，灰度上线用） |
| 卡数 | 一道（白名单命中） | 一道（白名单命中且 project 匹配） |
| 未命中 | `ApprovalDeniedError`，错误含修复建议 | 同左 |

- 白名单文件格式（TOML，默认 XDG config `~/.config/reqmesh-harness/approvals.toml`，`REQMESH_APPROVALS_FILE` 可覆盖；0600）：

```toml
[[approvals]]
tool = "create_requirement"   # 必填：工具名
# project = "cessna-172"      # 可选；省略 = DRAFT 通配全部项目；MUTATE 必填
# dry_run_only = false        # 可选；true = 只放行 dry_run 调用
```

### 写路径客户端契约

- `AuthSession` 增 `post/put/patch/delete`（P2 复用其登录/Cookie+CSRF 持久化/401 重登/Bearer 兜底）：所有写请求挂 `X-CSRF-Token`（`_csrf_headers()` 已就绪）；**连接错误不重试**（非幂等）；**401 重登一次并重试**（重放安全：登录成功前请求未被上游接受；重试后仍 401 抛 `SessionExpiredError`）。Bearer 兜底路径下写请求同 `Authorization` 头。
- **PUT = 部分更新**：请求体用 P1 生成模型 `model_dump(exclude_unset=True)` 语义——未提供的字段不进入请求体；**显式 None 原样发送**（清空字段，与 reqmesh PUT 契约一致）。工具参数 schema 允许可空字段显式传 null 并区分「未提供」。
- **错误透传**：上游错误两种形状（`detail` 字符串 / `{error, message, ...}` envelope）归一化为 `UpstreamError(status_code, detail)` 向上抛（MCP tool error 显示状态码与摘要）；写工具不吞错误。新增错误类型：`ApprovalDeniedError`、`AdminDisabledError`、`ApprovalConfigError`（白名单文件损坏），均为 `HarnessError` 子类（P1 errors.py 扩展）。
- **结构护栏（与 P1 只读护栏对称）**：`WriteClient` 只暴露 `post/put/patch/delete`，构造函数要求审批门签发的 `GateToken`（不可自行伪造）；工具层经 `runtime.writer(...)` 取写视图，未过门的调用拿不到写视图——未批准即结构性无写路径。

### 审批门（guardrails）

- **层级来源**：注册表 `ToolSpec.level`（ADR-0002：绝不解析工具名推断层级）。
- **裁决流程**（每次调用执行，白名单文件每次调用时重新读取，不缓存）：
  1. `READ` → 直通（不审计，见审计节）；
  2. `DRAFT`/`MUTATE` → 按上表规则匹配白名单；未命中 → `ApprovalDeniedError`（fail-closed），错误信息给出精确的 `reqmesh-harness approvals add <tool> [--project P]` 命令与 TOML 片段；
  3. `ADMIN` → 先查 `REQMESH_ENABLE_ADMIN=1`（否则 `AdminDisabledError`），再查白名单（双卡）。
- **dry-run 不是绕过审批的后门**：`dry_run=true` 照跑审批门；未批准照样阻断并记审计。
- 配置项（环境变量，pydantic-settings）：`REQMESH_APPROVALS_FILE`（默认 XDG config 如上）、`REQMESH_AUDIT_FILE`（默认 XDG state `~/.local/state/reqmesh-harness/audit.jsonl`）、`REQMESH_ENABLE_ADMIN`（默认 `0`）。

### dry-run 语义

- 全部 12 个写工具统一 `dry_run: bool = False` 参数。
- `dry_run=true` 且审批通过时：**不发写请求**，组装并返回 `{"dry_run": true, "would_send": {"method", "path", "body"}, "checks": [...]}` 包裹——`checks` 为本地前置校验（create 类：目标 `id` 已存在（GET 单条 200）→ 冲突提示；引用 id 不存在 → 提示），不写库。
- **dry_run 不产生 git 提交**（reqmesh git 自动提交只在真实写时发生）——冒烟 B 段以 git 提交计数断言。
- **对齐规则**：reqmesh 原生带 `dry_run` 参数的端点（import、test-results/import、bulk-reparent，已核实 openapi）或原生预览端点（CR `redline`、baseline `diff`）在未来被包装时，**优先复用原生 dry_run/预览端点**，不用本地组装——此规则写入本 spec 供后续需求会话遵守。
- `dry_run=true` 的调用同样进审计日志（`dry_run=true` 字段）。

### 审计日志（工具调用级，JSONL）

- 范围：**全部写工具调用**（批准/拒绝/dry_run/失败路径都记，一行一次调用）；READ 工具不记（噪声控制，READ 层调用可经 MCP 侧日志观察）。
- 文件：`REQMESH_AUDIT_FILE`（默认 XDG state，如上）；append-only、0600；写入失败不得阻断工具调用（降级告警日志）。审计日志**不提供 READ 工具**（不向模型暴露；本地文件供操作员/审计方查阅）。
- 字段（`version: 1`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts` | string | ISO8601 UTC 时间戳 |
| `tool` | string | 工具名（注册表 name） |
| `level` | string | DRAFT/MUTATE/ADMIN |
| `project_id` | string | 项目上下文 |
| `dry_run` | bool | 本次调用是否 dry_run |
| `params_summary` | object | 参数摘要：标量原值截断 200 字符；容器记类型与长度；**绝不含凭据**（凭据不进工具参数，双保险） |
| `reason` | string | MUTATE 必填的变更理由（DRAFT 为空串） |
| `decision` | string | `approved` / `denied` / `admin_disabled` |
| `approved_by` | string \| null | 命中的白名单条目（`tool[+project]`）；未批准为 null |
| `deny_reason` | string \| null | 未命中的规则描述；已批准为 null |
| `upstream` | object \| null | `{method, path}`；dry_run 记 would_send 同字段；被拒为 null |
| `http_status` | int \| null | 上游状态码；未发请求为 null |
| `result` | string | `ok` / `upstream_error` / `transport_error` / `blocked` |
| `duration_ms` | int | 工具调用耗时 |
| `version` | int | 固定 1（预留演进） |

### 服务账号（D7 落地）

- **决策：约定新建专用账号 `reqmesh-harness`（role=contributor）**，由操作员用 admin 凭据在 reqmesh 一次性创建（人工前置步骤，写入冒烟前置与 README）。不复用 P1 冒烟用过的 `yugj`——那是个人账号，其密码/权限变更会击穿 harness，违背 D7 最小权限语义；harness 自身不含用户管理工具（`auth/users` 域属 ADMIN 层且不在 P2），不能自建账号。
- **凭据注入**：`REQMESH_USERNAME` / `REQMESH_PASSWORD` 环境变量（沿用 P1 `Settings`，`.env` 已 gitignore）——不落库、不入 repo、不进日志与审计。
- **冒烟断言**：`whoami` 返回 username==`reqmesh-harness` 且 role==`contributor`；若操作员未建号，允许降级为 `yugj`（现有 contributor）并在冒烟记录中显式标注降级。
- **匿名只读验证**：不带凭据的客户端调用 READ 工具 → 上游 401/403 经 `UpstreamError` 透传为工具错误（断言错误形状与「不含凭据信息」）。「服务账号可写」由冒烟 B 段真实写闭环验证（contributor 角色对 P2 全部 12 个端点的写权限即冒烟断言点）。

### 注册表与导出扩展

- `ToolSpec.level` 四级 Literal 已预留（P1 即存在），P2 投入使用 DRAFT/MUTATE；`annotations_for` 扩展：READ → `readOnlyHint=True`；DRAFT/MUTATE → `readOnlyHint=False, destructiveHint=False`；ADMIN → `destructiveHint=True`（预留）。
- 写工具 description 前缀约定：DRAFT 工具以 `DRAFT` 开头、MUTATE 工具以 `MUTATE` 开头（READ 层保持 `READ-ONLY` 开头，P1 惯例）；description 注明 `dry_run` 语义与「未批准将被拒绝」。中文书写（ADR-0002）。
- 注册表从 25 行增至 37 行（25 READ + 12 写）；`tests/mapping.py` 增写工具映射行（method/path/请求体形状/`reason`/`dry_run` 参数），映射表即契约。
- OpenAI 导出同源（注册表驱动）：37 个工具 1:1 对账（P1 测试模式），写工具参数 schema 含 `dry_run`（与 `reason`）。
- **ADR-0002 回写**：verb 词汇表按 ADR 已预告的「P2 起新增写动词」扩展为 `create`/`update`/`set`/`run`/`review`（`delete` 属 ADMIN，P2 不启用但词汇表预留）——开发会话完成后与 P1 同款「实现注记」回写 ADR-0002。这是 ADR 预告内的扩展，不是冲突。

### 冒烟（两段式，network-tagged）

- 脚本 `scripts/smoke_p2.py`（不进默认 pytest 集合，模式沿用 `smoke_p1.py`）：
  - **A 段（cessna-172，全量 dry_run，零副作用）**：临时空白名单下 `create_requirement` 被阻断（断言 `ApprovalDeniedError` 形状 + 审计记 `denied`）→ 添加白名单后 12 个工具逐一 `dry_run=true`，断言返回 `dry_run:true + would_send` 包裹、`checks` 正确、**全程 git 提交数不变**（冒烟脚本经客户端直连 `GET /api/projects/{project_id}/git/log` 计数断言——不经工具层，git 域 READ 工具仍延后）。
  - **B 段（最小真实写闭环，SMOKE-P2- 前缀固定 id）**：`create_requirement(SMOKE-P2-001)` → `get_requirement` 回读断言 → `review_item`（断言后 `get_unreviewed_requirements` 不含该需求）→ `update_requirement`（改 description 回读生效）→ `create_risk`/`create_component`/`create_verification_case`/`create_comment` 各自回读可见 → `run_verification`（断言 execution_history 追加）→ `set_relations`/`set_allocation` 读-改-写回放（先 GET 现状再追加 SMOKE 条目写回，回读断言）。断言：**git 新提交数 == 真实写调用数**（dry_run 不产生提交）；**审计日志行数 == 全部写调用数**且字段齐全。
  - 记录落盘 `docs/smoke/P2-cessna-172.md`：时间戳、实例 URL、服务账号与角色、每步结果与关键计数、**残渣清单**（新增实体 id 列表与 git 提交数）。注明：P1 冒烟的 `total==57` 断言自此只作为历史快照（P2 真实写后 `list_requirements` total 变为 58，P1 冒烟记录不再作为重跑断言）。

## Testing Decisions

- 好测试的标准沿用 P1：只测外部行为——写请求挂 `X-CSRF-Token`、PUT 部分更新语义、审批门裁决、dry_run 不发写请求、审计字段、错误透传；不测内部实现。
- 全部单元测试离线运行：`respx` 打桩 + fixture 文件（写请求体形状、上游错误两种形状、审计行样本）。
- 模块级测试职责：
  - 写客户端：post/put/patch/delete 挂 `X-CSRF-Token`；PUT 仅含已提供字段、显式 null 原样发送；连接错误不重试、401 重登一次；两种错误形状归一化 `UpstreamError`；`WriteClient` 无 GateToken 不可构造。
  - 审批门：fail-closed（无条目拒绝）；DRAFT 通配生效、MUTATE project 必匹配；`dry_run_only` 条目行为；`REQMESH_ENABLE_ADMIN` 开关（tools/list 不含 ADMIN 工具；开启 + 白名单双卡）；白名单每次调用重读；`approvals add/list/remove` CLI（交互与 `--yes` 同文件）。
  - 工具：12 个写工具逐一 schema 校验（与映射表一致，含 `dry_run`/`reason`）；打桩断言 method/path/body；被拒/批准/dry_run 三态；`mapping.py` 对账（25 READ + 12 写）。
  - 审计：每次写调用一行（含 denied/dry_run/错误路径）、READ 零行；字段齐全且类型正确；参数摘要截断/脱敏；文件 0600 append-only。
  - 导出：OpenAI 37 工具 1:1 对账、名称合规、parameters 过 `jsonschema` 校验。
  - 冒烟：A/B 两段断言见上；network-tagged。

## Out of Scope

- ADMIN 工具本体（删除族、execute/reject CR、freeze 基线、git push/restore、publish、import、用户/系统管理）——P2 只落「显式开启」机制，见延后清单。
- 延后写工具清单（update_risk、decision/analysis/specification/definition/change-request 写族、bulk/rename/cascade 族等）——P3/P4 按需加注册行。
- 调用中途交互式确认（MCP elicitation）与审批门在 agent loop 中的交互时序——P5 开放问题。
- 审计日志轮转/检索工具/远端上报——P6 运维范围。
- 自然语言建需求、追踪/覆盖缺口报告（P3/P4）；内置运行时、project context（P5）；部署/evals（P6）。

## Further Notes

- 术语一律按 `CONTEXT.md`：审批门、权限层级、dry-run、认证会话（与运行时会话区分）、工作会话等；「tool」不与 DSH 技能混用。
- 所有新配置均为 `REQMESH_*` 环境变量（pydantic-settings，`.env` 已 gitignore）；白名单与审计文件属 XDG config/state，0600。
- 开发会话按 design §5：实施后自动启动审核子代理与测试子代理；每轮循环结论记对应 ticket comment；超 5 轮仍失败回到需求会话（入口即交接文本）。
- P1 资产不动：25 个 READ 工具、注册表结构、双 transport、OpenAI 导出保持现状（P2 只在注册表加行、扩展 `annotations_for` 与 errors.py，不重构 P1 行为）。
- 白名单/审计文件不进 git（属运行时状态）；spec、tickets、交接文本照常入仓。
