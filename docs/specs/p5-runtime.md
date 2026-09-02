# P5 spec：内置运行时（agent loop + provider 可插拔 + DSH 适配器 + 会话内存）

> 状态：需求会话产出，待开发会话实施。
> 入口：design [docs/reqmesh-harness-design.md](../reqmesh-harness-design.md)（§3 D5/D10/D11、§4 P5 行、§5 流程、§6 P5 预置开放问题） · epic [#5](https://github.com/GuangjieYu1/PRDMS/issues/5) · 术语 [CONTEXT.md](../../CONTEXT.md) · 协议 [ADR-0001](../adr/0001-mcp-core-tool-protocol.md)（Consequences：provider 与工具层解耦） · 命名 [ADR-0002](../adr/0002-tool-naming-and-grouping.md) · P1–P4 specs（[p1](p1-tool-layer-mvp.md)/[p2](p2-write-path.md)/[p3](p3-nl-requirements.md)/[p4](p4-traceability-report.md)）
> 交接：见 [docs/handoffs/p5-runtime.md](../handoffs/p5-runtime.md)

## Problem Statement

P1–P4 交付了 40 个工具（25 READ + 12 写 + 2 P3 + 1 P4）、四级审批门、审计与双 transport MCP server，但 harness 本身仍是被动工具层：多步任务（如「用自然语言建一条需求并核对其 quality」「读缺口报告后修复追踪」）需要调用方（另一个 agent）自己编排工具序列。design D5 的收口是 P5：给 harness 加**内置 agent loop**（planner/executor、流式输出、会话内存），LLM provider 可插拔；默认适配器走**本地 DSH 的 loopback HTTP RPC**（design D10 已核实的集成路线）。epic #5 验收底线：内置 loop 能驱动 P1–P4 工具完成一个真实任务；provider 切换（DSH ↔ 其他）不改工具层（ADR-0001 后果）。

本会话核实的关键事实（见「事实核实」节）：DSH 的 loopback RPC 只有「整个 agent 会话」粒度的接口（session.create/prompt/cancel + events.mux 事件流），**没有**裸模型补全/工具调用往返端点——纯自驱代理路线（harness 只借 DSH 做模型推理）对 DSH 不可行；DSH 是 MCP **client**（dsh-mcp-client 插件，`mcp__reqmesh__*` 工具注册），工具执行天然发生在 DSH 会话内、harness MCP server 进程内——审批门与审计在 harness 进程照常生效；events.mux 在本机宿主（127.0.0.1:8080，v0.1.1-rc.2）实测为 **WebSocket-only**（GET 返回 426 Upgrade Required），帧为 server-request 信封。据此本 spec 定案：DSH 适配器 = 委托式（路线 A）；自驱 planner/executor 由 OpenAI 兼容 provider 承接（ADR-0001 的第二个消费面，环境无 key 故仅离线验证）；离线验收用 FakeProvider 断言工具调用序列。

## 事实核实（本会话，证据留档，不拍脑袋）

DSH checkout 只读调查（`/home/user/.npm-global/lib/node_modules/@deepseek-ai/dsh`，v0.1.1-rc.2；未做任何修改）+ 对运行中宿主 `http://127.0.0.1:8080` 的只读 live 探针 + harness 源码复核：

### DSH 集成面（dsh-host-apiproxy）

1. **RPC 信封与路由**（`lib/types/api/rpc.schema.js`、`lib/index.js` `UNARY_ROUTES` 4576–4785 行）：
   - 请求 `POST /api/<method>`，信封 `{"type":"client-request","rpcId","method","payload"}`；响应 `{"type":"server-response","rpcId","result":{ok:true,value}|{ok:false,error}}`；**业务错误也是 HTTP 200 + ok:false**（HTTP 状态只表达载体层：404 未知路径 / 415 非 JSON / 400 坏信封）。
   - 本会话可用的关键方法：`session.list` / `session.search` / `session.create` / `session.history` / `session.models` / `session.selectModel` / `session.rename` / `session.fork` / `session.prompt` / `session.attachment` / `session.updateQueue` / `session.cancel`、`subagent.list/history/prompt/interrupt`、`host.*`、`workspace.*`、`skill.list`、`agentPreset.*`、`goal.*`、`settings.*`、`credentials.*`、`llm.providers/models/discoverModels`。**没有**任何 completion/chat/tool-call 往返端点（路线 B 对 DSH 不可行的直接证据）。
   - `session.export` 不在 unary 路由：`GET /api/session.export?sessionId=<id>`（sessionLogQuerySchema），下载会话 JSONL 日志（存证用）。
   - 错误码（`rpcErrorSchema`，约 30 种）：`bad-request` / `session-not-found` / `model-unavailable` / `agent-busy` / `session-conflict` / `steer-unavailable` / `queue-item-not-found` / `fork-unavailable` / `internal` 等——provider 适配器按此归一。

2. **session.create**（`sessions.schema.js`）：payload `{workspaceId?|cwd?, sessionId?, agentPreset?}`（workspaceId 与 cwd **二选一**，refine 校验）→ value `{sessionId, agentPreset?}`。cwd 可选；本机宿主当前 profile 默认 agentPreset=standard（live 探针 `session.list` 实测）。

3. **session.prompt**（`sessions.schema.js` + `index.js` 2733–2782 行）：payload `{sessionId, mode: "queue"|"steer", content: [{type:"text",text}|{type:"image",…}], clientTimeZone?}` → value `{accepted:true, command?}`。**mode 语义（源码核实）：`steer` → `agent.steer(message)`；否则（queue）→ `agent.followup(message)`**——即 queue=followup 追加轮次、steer=向运行中 turn 注入指导。错误路径：`model-unavailable`（无适配器服务当前 provider）、`agent-busy`（prompt rejected）、`invalid-time-zone`。`session.updateQueue` 的 `steer` action 只对「运行中 + next-turn」队列项有效（`steer-unavailable` 否则）。`session.cancel` → `{accepted:true}`。

4. **events.mux 事件流**（`events.schema.js`、`index.js` 5013–5084/4853–4884/5307–5359 行；live 实测）：同一路径双形态——in-process handler 支持 GET SSE（`data: <server-request JSON>\n\n`），**但本机 web 宿主把 `/api/events.mux` 注册为 WebSocket upgrade 路由**（dsh-client-connection `this.upgrade(req, socket, head, ...)`），GET 实测返回 `426 Upgrade Required` + `upgrade: websocket`；WS 连接后每帧为 server-request 信封 `{"type":"server-request","rpcId","method":<帧类型>,"payload":{...}}`（本会话 WS 探针实测收到 `session/subscribed` 帧）。**P5 适配器走 WebSocket**（python `websockets` 依赖）。**与 design D10 的差异显式标注**：D10「`events.mux` SSE」表述在本机宿主（v0.1.1-rc.2）上不成立（GET 426）——开发会话按本 spec 事实 4 实现 WebSocket 路线；design doc 的注记回写按惯例由 P5 开发会话完成后执行。MuxFrame 帧类型 10 种：`session/event`（含 SessionEvent）、`session/subscribed`{lastSeq}、`approval/requested`、`approval/resolved`、`question/requested`、`question/resolved`、`session/queue`、`session/jobs`、`session/projection`、`stream/error`。

5. **SessionEvent 词汇表**（dsh-session `KNOWN_SESSION_EVENT_TYPES`，49 类；envelope 严格 `{type,seq,time,data[,sourceEventSeqs,surfaceOp,ignorable]}`，data 宽放行）：流式/工具相关——`assistant/chunk`（chunk.type ∈ text-delta/reasoning-delta/tool-call-chunks；存储层会把连续 delta 打包为 text-chunks/reasoning-chunks/tool-call-chunks 行，**适配器须按行展开**）、`assistant/message`（content 含 tool-call block，带参数）、`tool/call`{data.callId}、`tool/result`{data.message.source.callId, content[tool-result block], isError}、`turn/start`、`turn/end`{data.reason}、`step/start`、`step/end`、`user/message`、`approval/asked`、`approval/decided`、`approval/policy`、`todo/write`、`session/title`、`goal/change`、`plan/mode`、`sandbox/mode` 等。**完成判定 = 该 session 的 `turn/end` 帧 + 宿主侧 running=false**（`session.list` 的 `running` 字段实测存在，或 events.host 的 `host/session-status` 帧）。

6. **认证与信任围栏**：无 token/cookie。dsh-api-gateway 对 `/api` RPC 拦截声明 `authority: "trusted-host"`（loopback 或 `--trusted-host` 名单）；web-app 显式拒绝 `--host 0.0.0.0`。**harness 侧零凭据**；DSH 宿主自身持有 LLM provider 配置（live 探针 `llm.providers`：deepseek-official active）——DSH 适配器不需要也不应接触任何模型 key。

7. **DSH 侧原生审批/问题机制（与 harness 审批门相互独立的两层，勿混淆）**：`approval/requested`/`approval/resolved`（dsh-user-approval，覆盖 DSH 自己的工具如 bash；策略 ask/never）、`question/requested`/`question/resolved`（dsh-user-questions，即 agent 的 ask_user_question）。两者都经 **`POST /api/respond`** 应答（client-response；approval 应答 payload `{sessionId,approvalId,outcome: allowed-once|rejected}`；question 应答 payload 为 answer 批次，逐 id 校验）。**dsh-mcp-client 不声明 approval policy**——MCP 工具不触发 DSH 原生 approval 帧。

### DSH 会话内工具暴露（dsh-mcp-client）

8. **注册机制**（`@deepseek-ai/dsh-mcp-client` README + 本机 profile 实测）：在 profile 的 **cordis.patch.yml**（用户 patch 层——`profiles/web/cordis.yml` 是空 entry list + bundles dsh-base/dsh-web-app，文件头注明「Edit cordis.patch.yml, not this file」）追加一行插件条目；stdio 配置 `{serverName,command,args,env,cwd}` 或 streamable-http `{serverName,url,headers}`。工具注册为 `mcp__<serverName>__<rawName>`（≤64 字符规范化，冲突时确定性 hash 后缀）。连接后 `listTools()` 完成前工具不可用；`failOnStartupError`（默认 false）、`toolCallTimeoutMs`（默认 60000）、自动重连（默认开）。**本机 web profile 的 cordis.patch.yml 当前只有 webserver 条目——注册 reqmesh 需追加条目 + 重启/重载宿主（见「DSH 部署步骤」）**。harness MCP server 的 stdio 入口 = console script `reqmesh-harness --transport stdio`（pyproject `[project.scripts]`）；`cwd` 指向 `reqmesh-harness/` 使 `.env`（Settings `env_file=".env"`）生效。

9. **「工具执行在 DSH 会话内」路线可行性（判定：可行且护栏不失效）**：DSH agent 调用 `mcp__reqmesh__<tool>` → 该调用在 **harness MCP server 进程**内执行（stdio 子进程由 DSH spawn）→ 审批门/审计/dry-run 在该进程照常裁决（白名单与审计文件按同一 XDG 路径）→ 被拒时返回 MCP tool error（isError=true，文本含 `ApprovalDeniedError` 消息 + fix_hint 的 `approvals add` 命令）→ 该错误经 `tool/result` 帧回传 DSH 会话。**拒绝语义与 P2 完全一致，无需跨进程协议**；工具调用参数与结果在事件流的 `assistant/message`（tool-call block）与 `tool/result` 中可见。

### harness 现状（本会话源码复核 + 离线测试实测）

10. **工具层与护栏现状**：注册表 40 行（`tools/__init__.py` `build_registry`；`registry.call(tool_name, **kwargs)` 已是统一入口）；`ApprovalGate.decide` 每次调用重读白名单、fail-closed、`ApprovalDecision.fix_hint` 给出精确 `approvals add` 命令（`guardrails/gate.py`）；审计 `version=1` 字段契约（`guardrails/audit.py`，写尝试一行一次，denied 也记）；`approvals` CLI 与 `WhitelistStore.append/remove`（规范化 TOML 写回、0600、每次调用重读不缓存）；错误类型 `errors.py`（`HarnessError` 族，`ApprovalDeniedError`/`UpstreamError`/`TransportError`/`AdminDisabledError`/`ApprovalConfigError`/`InputParseError`）；`config.py` pydantic-settings + XDG config/state 惯例（`resolved_*` 方法）；`cli.py` 子命令分发（`approvals` 之外透传 server main）。`tools/export.py` `export_openai_functions(registry)`（$defs 内联、OpenAI 子集）——ADR-0001「自建运行时使用」的预留消费面，P5 自驱 provider 直接复用。
11. **测试基线（本会话实测复跑）**：`396 passed, 3 skipped, 2 deselected`——P1–P4 离线套件全绿（与 P4 交接文本基线一致）。
12. **cessna-172 现状**：P4 基线 total=61（2026-09-02 实测）；服务账号 `reqmesh-harness`（maintainer，P2 实测偏差 1 结论）；`is_repo=false`（git 断言条件化惯例）。P5 B 段冒烟后 total 变 62（P1/P2/P3 同款漂移注记惯例）。

### live 探针记录（本会话，只读）

- `POST /api/session.list` → 200，返回 items（含本工作会话所在 session：running=true、agentPreset=standard、projections 齐全）——信封与值 schema 实测吻合。
- `GET /api/events.mux` → `426 Upgrade Required`（upgrade: websocket）；`ws://127.0.0.1:8080/api/events.mux` 连接成功并连续收到 `session/subscribed` server-request 帧。
- `POST /api/llm.providers` → deepseek-official active（host 侧持 key）。

## Solution

在 P4 的 reqmesh-harness 上新增 **runtime 包 + CLI 子命令**（工具层与护栏裁决语义零改动）：

1. **provider 契约 + FakeProvider**（`src/reqmesh_harness/runtime/provider.py` + `fake.py`）：可插拔抽象（③），错误归一 `ProviderError`（errors.py 扩展）。
2. **会话内存**（`runtime/memory.py`）：project context + run 事件日志（XDG state，与 AuthSession 同惯例）+ 跨 run 恢复语义（⑤）。
3. **DSH provider 适配器**（`runtime/dsh_provider.py`）：loopback RPC client（httpx）+ WS events.mux 帧解析（websockets）+ 流式/工具事件/完成判定/cancel（②）。
4. **运行时 loop 内核 + 自驱 executor**（`runtime/loop.py`）：RunDriver（任务指令组装 → provider 驱动 → 结果归一）+ 自驱工具执行循环（registry.call + 既有审批门/审计/dry-run 全链路，零复制门逻辑）（①③）。
5. **`reqmesh-harness run` CLI**（`runtime/run_cli.py` + `cli.py` 分发）：流式渲染、审批确认中继、`--project/--provider/--resume/--yes`、TTY `/steer`（①④）。
6. **OpenAI 兼容 provider**（`runtime/openai_provider.py`）：自驱 planner/executor 的第二个 provider（复用 `export_openai_functions`；环境无 key，仅离线验证）（②）。
7. **DSH 部署步骤**（显式，属 P6 部署输入；本 phase 只记录、不执行——见「DSH 部署步骤」节）。

冒烟（scripts/smoke_p5.py，network-tagged）：A 段 = DSH 适配器机制（纯回答任务 + cancel，零工具调用、对 reqmesh 零请求）；B 段 = 真实任务「用自然语言给 cessna-172 建一条需求」（SMOKE-P5-001，denied→确认→approved 双审计行 + 落库回读），**B 段需 DSH 部署步骤已应用**（记录状态，见 ⑥）。

## User Stories

1. As an operator, I want `reqmesh-harness run "<自然语言任务>"` to drive P1–P4 tools through the built-in loop with live streaming output, so that multi-step reqmesh tasks work without an external agent host.
2. As a developer, I want the loop to consume a `Provider` interface with FakeProvider in offline tests, so that loop logic is testable without DSH or any API key.
3. As an operator, I want the default provider to be the local DSH host (loopback RPC + WS event stream, zero credentials on the harness side), so that the harness reuses the already-configured local LLM host.
4. As a developer, I want a self-driven planner/executor path (OpenAI-compatible provider) that reuses `export_openai_functions` and the existing gate/audit/dry-run machinery, so that switching provider never touches the tool layer (ADR-0001).
5. As an operator, I want the run to remember project context and persist its event log under XDG state, and `--resume` to continue a previous run, so that interrupted work is recoverable.
6. As an operator, I want an approval-denied write inside the loop to surface as an interactive confirmation (or automatic in headless `--yes` mode) that only maintains the whitelist file, so that P2 fail-closed semantics hold unchanged.
7. As an auditor, I want every denied and approved write attempt inside the loop to produce its own audit line exactly as P2 requires, so that agent-driven writes are indistinguishable from manual tool calls in the audit trail.
8. As an operator, I want a repeatable live smoke (A 段零副作用 + B 段真实任务) with the record on disk, so that P5's acceptance is verifiable.

## Implementation Decisions

### 开放问题①：运行时形态（已决策）

**决策：CLI 子命令 `reqmesh-harness run "<任务>"` + 库接口 `runtime.run()` 双层；不新增嵌套 agent MCP tool。**

- CLI 是薄壳：解析参数 → 装配 run → 流式渲染（stdout 文本、工具行摘要、审批确认提示）→ 退出码与最终文本；库接口 `runtime.run()`（内部 RunDriver 驱动 provider，见 ③/⑥）供测试/嵌入（FakeProvider 离线测试走库）。
- **拒绝嵌套 MCP tool**（把内置 loop 再注册为工具给 DSH 用）的理由：① 无意义递归——DSH 自身就是 agent loop，且已能经 mcp-client 原生消费 40 个工具，harness 再嵌一层 loop 工具是 agent 套 agent；② P1/P2 已证明 MCP 工具调用中途不能做终端交互（P2 开放问题②理由 1：stdio 是 JSON-RPC 通道），而审批确认（④）需要终端交互通道——run CLI 是唯一自然宿主；③ 工具调用时限（dsh-mcp-client `toolCallTimeoutMs` 60s 默认）装不下分钟级任务；④ provider 依赖进 MCP server 进程违背 D5 解耦（无 provider 的纯工具层部署必须继续可用）。
- provider 选择与参数：环境变量 `REQMESH_PROVIDER`（`dsh` 默认 | `openai` | `fake`）+ 各 provider 专属配置（Settings 扩展，见「配置项」）。设计 §6「provider 默认值」预置问题落定：**默认 dsh（本地 DSH）**。

### 开放问题②：DSH 集成路线（已决策）

**决策：路线 A（委托式）是 DSH 适配器的唯一实现；路线 B（自驱式借 DSH 做纯模型推理）经本会话核实不可行（事实 1：UNARY_ROUTES 无 completion/工具往返端点，session.prompt 只收用户内容并派发 agent turn）；自驱 planner/executor 由 OpenAI 兼容 provider 承接（ADR-0001 第二个消费面，环境无 key 仅离线验证）。工具层零改动（ADR-0001 后果兑现）。**

- **DSH 适配器（委托式）协议**（全部字段经本会话 schema/源码/live 核实）：
  1. `session.create({cwd})` → sessionId（cwd 默认 `REQMESH_DSH_CWD`（默认当前目录）；不传 workspaceId/agentPreset——用宿主 profile 默认）。
  2. 任务指令 = 首条 `session.prompt({sessionId, mode:"queue", content:[{type:"text", text:<任务指令+任务>}]})`；DSH 会话没有可写的 system 通道，**指令放首条 user content 开头**（与 OpenAI 路线的 system role 同文不同位，见 ③）。
  3. `ws://<host>/api/events.mux` 订阅：按 sessionId 过滤帧；流式渲染 = `session/event` 的 `assistant/chunk`（展开 text-chunks 行取 text-delta；reasoning-delta 折叠，`--show-reasoning` 展开）；工具事件 = `tool/call` + `tool/result`（isError 时提取错误文本）；`question/requested`/`approval/requested` 帧交审批/问题中继（④）。
  4. **完成判定**：收到本 session 的 `turn/end` 后轮询 `session.list`（running=false）或订阅 events.host 的 `host/session-status`；防御超时 `REQMESH_DSH_IDLE_TIMEOUT`（默认 600s，自最后一帧起计）。
  5. `session.cancel` 支持 Ctrl-C；`session.history`（beforeSeq/maxMessages）与 `GET /api/session.export` 用于 resume 存证/重建（⑤）。
  6. 错误归一：rpcError code → `ProviderError`（表：`session-not-found`/`model-unavailable`/`agent-busy`/`steer-unavailable`/`session-conflict` → 语义化中文消息 + code 保留；`internal`/连接失败/WS 断开 → unavailable）。
- **任务指令模板（DSH 委托路线）**（内容为契约，测试断言包含关键句）：
  - 「你是 reqmesh-harness 的内置 agent，运行任务由 harness 委派。project context：…（⑤）。可用工具仅限 `mcp__reqmesh__*`（清单：<工具名 + 首行 description>）。规则：① 只允许调用 mcp__reqmesh__* 工具完成本任务，不得使用 bash/文件工具修改任何文件；② 写工具被审批门拒绝时（错误含 `approvals add` 修复建议），用提问机制向用户确认是否批准，得到批准后**重试一次**；用户拒绝则放弃该写操作并在最终总结中说明；③ 最终总结须列出你调用过的工具名与关键结果。」
- **DSH 会话内工具执行**（事实 9）：审批门/审计在 harness MCP server 进程内生效，护栏不失效；run CLI 与 MCP server 共享同一 XDG 白名单/审计文件（同一 Settings 惯例）。
- **工具清单进指令**：从 `build_registry().all()` 派生（name + description 首行）——DSH 侧 mcp__reqmesh__* 工具的 schema 由 dsh-mcp-client 自行同步，harness 指令只做「哪些工具存在」的提示（名字映射 `mcp__reqmesh__<name>` 一致，ADR-0001）。

### 开放问题③：provider 接口契约（已决策）

```python
# runtime/provider.py（抽象，P5 新包）
@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    base_url: str
    created_at: str

@dataclass(frozen=True)
class ToolHint:
    name: str          # 注册表名；DSH 路线映射为 mcp__reqmesh__<name>
    description: str   # description 首行
    level: str         # READ/DRAFT/MUTATE（指令内提示哪些工具会触发审批门）

@dataclass(frozen=True)
class AgentRequest:
    task: str
    project_context: ProjectContext | None
    history: list[dict[str, str]]   # 会话内存摘要（resume 重建/DSH 会话自带历史时为空）
    tools: list[ToolHint]
    max_rounds: int                 # 防御上限（默认 8）

class StreamSink(Protocol):         # 流式回调（CLI 渲染与测试断言共用）
    def on_text(self, text: str) -> None: ...
    def on_tool_call(self, name: str, args: dict) -> None: ...
    def on_tool_result(self, name: str, ok: bool, summary: str) -> None: ...
    def on_question(self, q: Question) -> None: ...   # 审批/问题中继入口（④）
    def on_turn_end(self, reason: str) -> None: ...

class Provider(Protocol):
    name: str
    execution: Literal["delegated", "tool-loop"]  # 执行所有权：DSH=delegated；openai/fake=tool-loop
    def run_agentic(self, request: AgentRequest, sink: StreamSink, *,
                    cancel: threading.Event) -> RunResult: ...

@dataclass(frozen=True)
class RunResult:
    status: Literal["completed", "failed", "cancelled"]
    final_text: str
    tool_calls: int
    questions: int
    error: ProviderError | None
```

- **执行所有权语义（provider 契约的核心）**：`delegated`（DSH）——provider 全权执行工具并在会话内闭环，harness loop 只做指令装配/流式中继/审批确认/完成判定；`tool-loop`（openai/fake）——provider 产出文本与 tool_calls（`ToolCallRequest` 序列），由 harness 自驱 executor 执行（见 ①/④），结果回灌 provider 继续。
- **FakeProvider**（`runtime/fake.py`，测试资产）：脚本化 turn 序列——预置文本块/工具调用/工具错误/问题；**断言能力**：按脚本顺序消费 executor 回灌的工具结果（`next_result` 期望匹配，不匹配即 `AssertionError` 归一为 ProviderError(protocol)）——「含工具调用序列断言」落在此处；无网络、无随机。
- **错误归一**：`errors.py` 新增 `ProviderError(HarnessError)`：`kind ∈ {unavailable, timeout, protocol, busy, denied_answer}` + `code`（DSH rpcError code 原样保留）+ 中文 message；所有 provider 异常（httpx/websockets/DSH error/OpenAI 错误响应）一律归一后抛出，run CLI 只处理 `ProviderError` 与既有 HarnessError。
- **自驱 executor 契约（loop 内核）**：`execute_tool(name, args, project_context) -> ToolResult(ok, text)`——`registry.call` 执行；HarnessError → 错误文本（与 DSH 侧 MCP tool error 同形态，`ApprovalDeniedError` 文本含 fix_hint）；**executor 零复制门/审计逻辑**（写工具处理器内部已含 `_write_common.write_request` 全链路，P2/P3 事实）。**P5 全程不新增注册表行、不改任何工具处理器。**

### 开放问题④：流式输出与审批门交互时序（已决策）

**决策：审批裁决源不变（白名单唯一裁决源、每次调用重读、fail-closed——P2 不变式零改动）；P5 新增的是 run 层的「确认中继」：三种通道并存、明确定序；审计行为 = 每次写尝试一行（denied 与重试 approved 各一行）。**

- **时序（默认 DSH 委托路线；tool-loop 路线同构）**：
  1. agent 调写工具 → harness MCP server 审批门裁决（或自驱 executor 内裁决）；
  2. 未命中 → 该次调用返回工具错误（`ApprovalDeniedError` 文本 + fix_hint），**同时写 denied 审计行**（P2 既有行为，`tool/result` isError 回传）；
  3. run 的事件循环收到 isError 且识别 `ApprovalDeniedError` → 进入确认通道（下）；
  4. 确认通过 = **run CLI 调 `WhitelistStore.append`（guardrails 既有公开 API）维护白名单文件**，并向 agent 回答问题「已批准，请重试」；
  5. agent 重试 → 白名单命中 → 写入 + **approved 审计行**（`approved_by` = 条目 label，P2 语义）。
- **三条确认通道（并存，优先级：预先白名单 > 无头自动 > TTY 逐条）**：
  1. **预先白名单**：run 前操作员 `reqmesh-harness approvals add <tool> --yes`（既有 CLI）——run 全程无交互（无头/确定性首选）；
  2. **无头自动确认**：`run --yes`——denied 时 run CLI 自动 `WhitelistStore.append`（DRAFT/MUTATE 规则与 approvals CLI 完全一致，MUTATE 必须带 project）并回答 agent；**冒烟 B 段与脚本化场景用此通道**；
  3. **TTY 逐条确认**（默认）：denied 时 stdout 呈现 `审批确认：tool=<tool> project=<project> level=<level> dry_run=<bool> —— 批准将写入白名单条目并重试 [y/N]`；y → append + 回答；N → 回答「用户拒绝」，agent 按任务指令放弃该写并说明。
  - **明确不做**：① 不提供「仅本次放行」的临时通道（违背 P2「白名单是唯一裁决源」，会引入双轨）；② 不把审批确认放 DSH 原生 approval/requested 帧上（那是 DSH 工具的机制，MCP 工具不触发，事实 7）；③ **不修改 gate.py/whitelist.py/audit.py 的裁决语义**。
- **steer 回问（独立于审批）**：`run` TTY 交互支持 `/steer <文本>` → `session.prompt(mode="steer")`（运行中）；`session.updateQueue` 的 steer 仅作队列项重定向备选，P5 实现 mode=steer 一路即可。审批裁决**不**用 steer 承载（steer 是指导注入，不是裁决）。
- **流式与审批的时序关系**：审批确认发生在 isError 工具结果帧之后、agent 下一次工具调用之前；确认等待期间不阻塞 DSH 文本流（question/requested 帧到达即暂停正文输出，属 DSH agent 行为）；run 事件循环单线程顺序处理帧，无并发写入白名单的竞态（append 是原子 rename 写回，WhitelistStore 既有实现）。
- **审计行为（验收断言点）**：空白名单下 B 段任务产生 **2 行审计**（denied：decision=denied + deny_reason；approved：approved_by=`draft_requirement`）；用户拒绝场景 1 行（denied）。run 结束 CLI 打印审计摘要（读 `REQMESH_AUDIT_FILE`，本地文件，不向 agent 暴露——P2 契约）。审计字段契约 version=1 **零改动**。
- **DSH 会话内意外触发 DSH 原生 approval/requested 帧**（agent 违反指令用了 bash 等）：run CLI **默认不代答**——将帧内容以警告呈现并继续；任务指令①已约束「只用 mcp__reqmesh__* 工具」，冒烟断言全程无 approval/requested 帧。

### 开放问题⑤：会话内存（已决策）

**决策：run 级会话内存 = project context + run 事件日志（JSONL），XDG state 持久化（与 AuthSession 同惯例）；跨 run 恢复 = `--resume <run-id>`，DSH 会话存活时依赖其原生历史、失活时从 run 日志重建摘要注入。**

- **project context**：`{project_id, base_url, created_at}`。来源：`--project` 参数优先；未给出且任务文本含唯一匹配 `list_projects` 的项目 id → 报错提示显式给出（**不做启发式猜测**，fail-fast）；仍无 → project_context=None（纯只读任务可用）。
- **run 目录**（`REQMESH_RUNS_DIR`，默认 XDG state `~/.local/state/reqmesh-harness/runs/`；目录 0700、文件 0600）：
  - `run-<YYYYmmddTHHMMSS>-<id8>/context.json`——AgentRequest 快照（任务、project context、provider、时间戳）；
  - `run.jsonl`——run 事件日志：每行 `{ts, kind, ...}`，kind ∈ `task`（任务与指令）| `text`（流式文本增量）| `tool_call`（name/args 摘要）| `tool_result`（name/ok/summary）| `question`（审批/问题 + 用户答复）| `turn_end` | `error` | `done`（final_text/status/tool_calls 计数）——**审计日志与 run 日志是两个文件、两种语义**：审计只记写工具尝试（P2），run 日志记整个 run 的编排轨迹；run 日志不提供工具面（本地文件）。
  - `dsn-session.txt`——DSH sessionId 映射（resume 用）。
- **resume 语义**：`run --resume <run-id>`：① `session.list` 查 sessionId 仍存在 → `session.prompt(queue)` 追加（DSH 会话自带完整历史，history 字段传空）；② 不存在（宿主重启）→ 从 run.jsonl 重建「此前进展摘要」（final text + 工具调用序列 + 未决问题），作为历史摘要注入新 DSH 会话首条消息（`history` 字段承载），并在指令中明示「历史由 harness 内存重建」；③ 同 run-id 恢复产生新 run 目录（`run-<ts>-<id8>-resume`）并在 context.json 记录 `resumed_from`。
- **术语边界**（CONTEXT.md 遵守）：harness 侧一次 `run` = 一个运行时会话（`session` 词条所指）；DSH 宿主侧的会话一律称「DSH session」（外部宿主概念，加限定词），不得裸称 session。

### 开放问题⑥：验收口径（已决策）

**决策：离线（FakeProvider 任务用例 + respx，工具序列断言）为必过基线；live 冒烟两段式（A 段 DSH 适配器机制零副作用 + B 段真实任务）；B 段依赖「DSH 部署步骤」前置（本 phase 只记录、不执行）；A 段零副作用照旧。**

- **离线任务用例（FakeProvider）**：① 「读追踪缺口并写评审建议」：脚本 `get_traceability_gap_report` → `review_item`（denied → 确认通道（fake 问答）→ approved 重试）→ 断言工具调用序列、审计两行、流式事件顺序（text→tool_call→tool_result→…→turn_end）；② READ-only 任务（`get_coverage` → 完成）断言零审计行；③ FakeProvider 脚本顺序不匹配 → ProviderError(protocol)。HTTP 用 respx 打桩（P1–P4 模式），全程离线。
- **live 冒烟（scripts/smoke_p5.py，network-tagged）**：
  - **A 段（无需 DSH 部署前置，可立即执行）**：`session.create` → `session.prompt`（纯回答任务「请只回答一行：P5-A 冒烟正常；不要调用任何工具」）→ WS 订阅断言：收到 session/subscribed、assistant/chunk 帧数 >0、turn/end、`session.list` running=false；另起一个慢任务（「先思考再输出」类）验证 `session.cancel` → accepted + running 归 false。**全程对 reqmesh 零请求、零工具调用、零审计行、零副作用**。
  - **B 段（需部署前置：web profile 已注册 mcp__reqmesh__* 工具）**：任务「用自然语言给 cessna-172 建一条需求：When the landing gear is down and locked, the aircraft shall display a gear-down indication within 1 s.（id 用 SMOKE-P5-001，project cessna-172）」。流程：先临时空白名单 → `run --yes` → 断言：① 事件流含 `tool/call`（draft_requirement，denied isError → question/requested + question/resolved answered → 再次 tool/call → tool/result ok）；② 审计恰 2 行（denied + approved，tool=draft_requirement，approved_by=draft_requirement）；③ 落库回读：`get_requirement(SMOKE-P5-001)` description 与 EARS 句文本相等、status=proposed；④ `list_requirements.total` 61→62；⑤ assistant/chunk 帧数 >0 且流式顺序（chunk 先于 tool/call）；⑥ 冒烟脚本自身 HTTP 方法 ⊆ {GET}（登录与任务写除外，写均经审计可查）；⑦ 无 approval/requested 帧（agent 未用 DSH 工具）。残渣清单落盘（SMOKE-P5-001；P1 惯例：P5 冒烟后 total==62，P4 记录仅作历史快照）。
  - B 段**部署前置未满足时**：冒烟只跑 A 段并在记录注明「B 段待部署前置后执行（步骤见 spec）」——本 phase 不得修改运行中 DSH 宿主配置（硬约束）；部署步骤应用后重跑 smoke_p5.py 全量。
- **provider 切换验收（epic 底线）**：同一任务文本跑 FakeProvider（离线）与 DSH（live）→ 两者消费同一 `build_registry()` 与同一审批门/审计文件；验收断言 = P5 提交对 P1–P4 资产（registry/groups/guardrails 裁决/export/server/client）**零 diff**（仅 errors.py 加 ProviderError、config.py 加 P5 配置、cli.py 加 run 分发）。OpenAI 兼容 provider 的 live 冒烟不在 P5（环境无 key，D5）——离线 respx 验证请求形状与流式解析，key 由操作员按 P6/配置节提供后可复用 smoke 变体。

## 工具层与 ADR 关系（显式声明）

- **ADR-0001 无冲突，本 spec 即其 Consequences 的兑现**：P5 不触碰 40 个工具的注册表/导出契约（registry/groups/export/server 零修改；`export_openai_functions` 仅被 import 复用）；provider（DSH 委托 / OpenAI 自驱 / Fake）与工具层经同一注册表与同一审批门对接。
- **ADR-0002 无影响**：P5 无新工具、无动词扩展、无命名变更——不需要回写词汇表注记。
- **P2/P3 不变式**：审批门 fail-closed/白名单唯一裁决源/每次重读；审计「一行一次写尝试、denied 也记、READ 不记、写失败不阻断」；dry-run 不是绕过审批的后门；`ApprovalDeniedError` + fix_hint 形状不变——全部原样继承，P5 新增代码不复制裁决逻辑（只 import）。

## DSH 部署步骤（显式部署输入，属 P6；本 phase 只记录、不执行）

注册 harness MCP server 到本机 DSH 宿主（使 DSH 会话内可用 `mcp__reqmesh__*` 40 工具，B 段冒烟前置）：

1. 追加到 `/home/user/.dsh/profiles/web/cordis.patch.yml`（用户 patch 层；「Edit cordis.patch.yml, not this file」）：

   ```yaml
   - id: mcp-reqmesh
     name: '@deepseek-ai/dsh-mcp-client'
     config:
       serverName: reqmesh
       transport: stdio
       command: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness/.venv/bin/reqmesh-harness
       args: ['--transport', 'stdio']
       cwd: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness
       env:
         REQMESH_USERNAME: !!js process.env.REQMESH_USERNAME
         REQMESH_PASSWORD: !!js process.env.REQMESH_PASSWORD
   ```

   （`cwd` 指向 `reqmesh-harness/` 使 `.env` 生效；凭据经宿主环境变量转发，不写进 patch 文件。）
2. 重启 web 宿主（patch 层变更是否被 HMR 拾取**未验证**——按需重启；**重启会中断 8080 上正在运行的 Web 会话，选择维护窗口执行**）。
3. 验证：DSH 会话内可见 `mcp__reqmesh__list_requirements` 等 40 个工具；`whoami` 返回 `reqmesh-harness`（maintainer）。
4. 完整步骤落入 P6 部署文档（本 spec 只作输入记录）。

## 配置项（Settings 新增，环境变量，pydantic-settings）

- `REQMESH_PROVIDER`：`dsh`（默认）| `openai` | `fake`。
- `REQMESH_DSH_URL`：默认 `http://127.0.0.1:8080`；`REQMESH_DSH_CWD`：session.create 的 cwd（默认当前目录）；`REQMESH_DSH_IDLE_TIMEOUT`：默认 600（秒，流空闲防御）；`REQMESH_DSH_MAX_ROUNDS`：默认 8（委托路线的防御上限=任务指令内明示轮次约束）。
- `REQMESH_RUNS_DIR`：默认 XDG state `reqmesh-harness/runs/`（⑤）。
- `REQMESH_OPENAI_BASE_URL` / `REQMESH_OPENAI_API_KEY`（SecretStr）/ `REQMESH_OPENAI_MODEL`：openai provider（P5 仅离线验证；DeepSeek API 同 OpenAI 协议）。
- 其余全部沿用 P1–P4（`REQMESH_BASE_URL`、凭据、审批/审计文件、lint 参数等）——审批门/审计路径在 run CLI 与 MCP server 间共享同一 XDG 文件。

## 验收标准（逐条可测试；括号为归属 ticket）

1. provider 契约按 ③ 实现：AgentRequest/RunResult/StreamSink/Provider/ProjectContext/ToolHint 类型与字面量（execution ∈ delegated|tool-loop）逐项存在；`ProviderError` 在 errors.py 且带 kind/code/message（#36）。
2. FakeProvider 脚本化 turn 序列：文本→工具调用→错误→问题，顺序断言失败 → ProviderError(protocol)；无网络依赖（#36、#43）。
3. 会话内存：run 目录/context.json/run.jsonl/dsn-session.txt 按 ⑤ 落盘（XDG state、0600）；resume 两分支（DSH 会话存活追加 / 失活重建摘要注入新会话）各有用例（#37、#43）。
4. DSH 适配器：session.create/prompt/cancel/list 请求体与响应解析按事实 1–3 契约；WS events.mux 帧解析（10 种 MuxFrame + text-chunks 展开 + tool/call、tool/result、turn/end 判定）；rpcError → ProviderError 映射表逐码测试（session-not-found/model-unavailable/agent-busy 等）（#38、#43）。
5. 完成判定：turn/end + running=false 两条件齐备才返回 RunResult；空闲超时（REQMESH_DSH_IDLE_TIMEOUT）与 cancel（Ctrl-C → session.cancel）路径各自成立（#38、#40、#43）。
6. loop 内核：RunDriver 任务指令模板按 ② 组装（project context、工具清单、三条规则、max_rounds）；delegated 与 tool-loop 两执行所有权分支都通同一 StreamSink（#39）。
7. 自驱 executor：tool_calls 经 registry.call 执行；ApprovalDeniedError/UpstreamError → 工具错误文本回灌（含 fix_hint）；写工具不复制门逻辑（import 复用既有处理器）；未知工具名 → ProviderError(protocol)（#39、#43）。
8. `reqmesh-harness run` CLI：`--project/--provider/--resume/--yes` 参数契约；流式渲染（text 逐块 stdout、工具行摘要、推理折叠/--show-reasoning）；TTY `/steer` 走 session.prompt(mode=steer)；退出码（completed 0 / failed 非 0 / cancelled 130）（#40）。
9. 审批门交互时序：denied → 确认通道（TTY y/N 或 --yes 自动）→ WhitelistStore.append → agent 重试 → approved；拒绝路径只记 denied 行；空白名单 B 段断言审计恰 2 行（denied+approved，字段按 P2 version=1）（#41、#43）。
10. run 结束审计摘要打印（读 REQMESH_AUDIT_FILE，不向 agent 暴露审计文件内容）；run 日志与审计日志分文件分语义（#40、#41）。
11. OpenAI 兼容 provider：请求体（system 指令 + 历史 + tools=export_openai_functions(registry) 的 schema）与流式响应解析按 OpenAI 协议；离线 respx 全绿；无 key 时启动报 ProviderError(unavailable)（#42、#43）。
12. provider 切换不改工具层：P5 提交对 registry/groups/export/server/client/guardrails 裁决路径零 diff（仅 errors/config/cli 白名单内新增）；396 基线测试不回退且新增全绿（#43）。
13. live 冒烟 A 段：session.create/prompt/WS 流式/turn-end/取消全部断言通过；对 reqmesh 零请求、零审计行、零副作用；记录落盘 docs/smoke/P5-cessna-172.md（#44）。
14. live 冒烟 B 段（部署前置满足后）：SMOKE-P5-001 落库回读（description 文本相等、status=proposed）、total 61→62、审计 2 行、流式帧断言、无 approval/requested 帧；残渣清单落盘；部署前置未满足时记录注明「待前置后执行」（#44）。

## Testing Decisions

- 标准沿用 P1–P4：只测外部行为（契约类型、帧解析、工具序列、审计行、落库回读、流式顺序）；不测内部实现细节。
- 全部单元测试离线：FakeProvider + respx（reqmesh HTTP 打桩）+ 录制的 DSH 帧 fixture（`tests/fixtures/dsh/`：server-request 信封样本——session/subscribed、assistant/chunk（含 text-chunks 打包行）、tool/call、tool/result、question/requested、turn/end、stream/error、session.list 值）+ OpenAI API 请求/响应样本。
- 模块级测试职责：
  - provider/fake：脚本序列消费与断言、顺序失配、问题应答；
  - memory：落盘/0600/重建摘要/resume 两分支/损坏文件 fail-fast；
  - dsh_provider：请求体逐字段（按 facts 契约）、帧解析逐类型、text-chunks 展开、错误码映射表、完成判定与超时/cancel；
  - loop：指令模板、两 execution 分支、executor 工具错误回灌、max_rounds 防御；
  - run_cli：参数契约、渲染输出（capsys）、TTY 确认 y/N 与 --yes、退出码；
  - approval seam：denied→append→重试→approved 全链（fake）+ 审计两行断言（复用 test_audit 模式）；
  - openai_provider：请求形状与注册表 schema 1:1（export 复用）、SSE 解析、错误归一；
  - 回归：P1–P4 既有 396 passed 不回退（本会话实测基线）。
- 冒烟：smoke_p5.py network-tagged（A 段必跑；B 段按部署前置状态），记录落盘 docs/smoke/P5-cessna-172.md（时间戳、实例、DSH URL、每步结果、流式帧计数、审计行、残渣清单、部署前置状态）。
- 生成模型不重跑（无新请求体）；runtime 为手写纯函数/薄 IO（无生成代码）。

## Out of Scope

- DSH 原生 approval/requested 代答、DSH 宿主配置的自动管理（部署步骤属 P6；本 phase 只记录）。
- OpenAI 兼容 provider 的 live 冒烟（环境无 key，D5；离线验证 + P6/操作员供 key 后复用 smoke 变体）。
- 多 provider 组合/回退、并行 run、run 队列、run 日志的检索工具与远端上报（P6 运维范围）。
- agent 记忆的向量化/长期记忆（P5 只做 run 级 project context 与事件日志）。
- MCP elicitation（client 弹窗）——确认通道按 ④ 三通道落地，elicitation 不启用（P2 同款结论）。
- ADMIN 层、bulk/rename 族、其余延后写工具——维持 P2 延后清单不变；P1–P4 资产不重构。

## Further Notes

- 术语一律按 CONTEXT.md：审批门、权限层级、dry-run、审计、project context、认证会话；harness 侧运行时会话称「run」，DSH 宿主侧一律「DSH session」（加限定词，不裸称 session）；「工作会话」指工程对话。
- 与 ADR 的关系：ADR-0001 无冲突（本 spec 即其 Consequences 兑现）；ADR-0002 无影响（无新工具/动词）；P2/P3 不变式原样继承（见「工具层与 ADR 关系」）。
- 硬约束遵守：不动 reqmesh/ 目录；不修改 DSH checkout 与运行中 DSH 宿主配置（部署步骤只记录，冒烟 B 段按前置状态执行）；不破坏 P1–P4 资产（验收 12 的零 diff 断言）。
- 开发会话按 design §5：实施后自动启动审核子代理与测试子代理；每轮循环结论记对应 ticket comment；超 5 轮仍失败回到需求会话（入口即交接文本）。
- 实测偏差回写惯例：开发会话对真实 DSH 宿主/实例实测的偏差（如帧形状、完成判定时序、部署前置状态）记入 docs/smoke/P5-cessna-172.md「实测偏差」节，需求会话确认后回写本 spec「实测偏差与决策」节（P1–P4 同款流程）。

## 实测偏差与决策（开发会话核实后回写，待需求会话确认）

（占位：开发会话完成后由需求会话确认并回写。）
