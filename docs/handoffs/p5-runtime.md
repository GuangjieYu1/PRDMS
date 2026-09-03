# 交接文本：P5 内置运行时（需求会话 → 开发会话）

> 派发时间：2026-09-02。开发会话以此文件为入口。

## 索引

- **Epic**：[#5](https://github.com/GuangjieYu1/PRDMS/issues/5) [P5] 内置运行时：agent loop + DSH provider 适配器
- **Spec**：`docs/specs/p5-runtime.md`
- **Design doc**：`docs/reqmesh-harness-design.md`（§3 D5/D10/D11、§4 P5 行、§5 流程、§6 P5 预置开放问题）
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md)（Consequences：provider 与工具层解耦——P5 即其兑现；`export_openai_functions` 复用）· [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)（P5 无新工具、无动词扩展，**无需回写**）
- **P1–P4 参考（勿重做）**：`docs/specs/p1-tool-layer-mvp.md` · `docs/specs/p2-write-path.md` · `docs/specs/p3-nl-requirements.md` · `docs/specs/p4-traceability-report.md` · `docs/handoffs/p1-tool-layer-mvp.md` · `docs/handoffs/p2-write-path.md` · `docs/handoffs/p3-nl-requirements.md` · `docs/handoffs/p4-traceability-report.md` · `reqmesh-harness/` 现有代码

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#36](https://github.com/GuangjieYu1/PRDMS/issues/36) | provider 契约与 FakeProvider：AgentRequest/RunResult/StreamSink + ProviderError 错误归一 | — |
| [#37](https://github.com/GuangjieYu1/PRDMS/issues/37) | 会话内存：project context + run 事件日志（XDG state）+ resume 两分支 | — |
| [#38](https://github.com/GuangjieYu1/PRDMS/issues/38) | DSH provider 适配器：loopback RPC + WS events.mux 帧解析 + 完成判定/cancel | #36 |
| [#39](https://github.com/GuangjieYu1/PRDMS/issues/39) | 运行时 loop 内核与自驱 executor：RunDriver + 任务指令组装 + registry 工具执行循环 | #36, #37 |
| [#40](https://github.com/GuangjieYu1/PRDMS/issues/40) | `reqmesh-harness run` CLI 与流式渲染：参数契约 + TTY /steer + 审计摘要 | #39 |
| [#41](https://github.com/GuangjieYu1/PRDMS/issues/41) | 审批门交互时序：denied→确认中继→白名单维护→重试；审计双行行为 | #39, #40 |
| [#42](https://github.com/GuangjieYu1/PRDMS/issues/42) | OpenAI 兼容 provider（自驱）：复用 export_openai_functions + 离线 respx | #36, #39 |
| [#43](https://github.com/GuangjieYu1/PRDMS/issues/43) | 离线测试套件：DSH 帧 fixture/FakeProvider 任务用例/审批时序/回归（396 基线不回退） | #36–#42 |
| [#44](https://github.com/GuangjieYu1/PRDMS/issues/44) | cessna-172 live 冒烟：A 段零副作用 + B 段真实任务（SMOKE-P5-001）+ 部署前置记录 | #38, #40, #41, #43 |

frontier 首步：#36、#37（可并行）；随后 #38、#39（#39 待 #37）；#40 后 #41；#42 可随 #39 之后并行推进；#43 收束全部代码；#44 为网络冒烟（A 段立即可跑，B 段按部署前置状态，见下）。

## 本会话决策摘要（开发会话必须遵守）

1. **运行时形态（开放问题①）**：CLI 子命令 `reqmesh-harness run "<任务>"`（薄壳）+ 库接口 `runtime.run()` 双层；**不新增嵌套 agent MCP tool**（无意义递归——DSH 自身即 agent loop 且已能原生消费 40 工具；MCP 工具调用中途不能做终端交互——P2 开放问题②既有结论；60s toolCallTimeoutMs 装不下分钟级任务；provider 依赖进 MCP server 进程违背 D5 解耦）。provider 默认值（design §6 预置问题）落定：`REQMESH_PROVIDER=dsh`（本地 DSH）。
2. **DSH 集成路线（②）**：**路线 A 委托式为 DSH 适配器的唯一实现**；路线 B（自驱式借 DSH 做纯模型推理）经核实**不可行**（UNARY_ROUTES 无 completion/工具往返端点，session.prompt 只收用户内容并派发 agent turn——spec 事实 1）。自驱 planner/executor 由 OpenAI 兼容 provider 承接（#42，离线验证；环境无 key，D5）。**工具执行在 DSH 会话内 = 在 harness MCP server 进程内执行——审批门/审计/dry-run 照常生效，护栏不失效**（dsh-mcp-client 是纯桥接，不代理护栏）。
3. **provider 契约（③）**：`Provider.run_agentic(request, sink, cancel)` + `execution ∈ delegated|tool-loop` 执行所有权语义（DSH=delegated；openai/fake=tool-loop，自驱 executor 执行 `registry.call` 并回灌结果）；错误归一 `ProviderError(kind/code/message)`（errors.py 新增）；FakeProvider 脚本化 turn 序列 + **工具调用序列断言**（顺序失配 → ProviderError(protocol)）。executor **零复制门/审计逻辑**（写工具处理器已含 `_write_common.write_request` 全链路，只 import）。
4. **审批门交互时序（④，design §6 预置问题落定）**：裁决源不变（白名单唯一裁决源、每次调用重读、fail-closed——gate.py/whitelist.py/audit.py **零 diff**）。P5 新增 run 层「确认中继」三通道（优先级：预先白名单 > `--yes` 无头自动 > TTY 逐条 y/N）：denied（ApprovalDeniedError + fix_hint 照旧）→ run CLI `WhitelistStore.append` 维护白名单文件（唯一裁决源，无「本次放行」临时通道）→ 回答 agent 重试一次 / 用户拒绝则放弃。**审计双行**：denied 一行 + 重试 approved 一行（P2 一行一次写尝试；version=1 字段零改动）。审批确认**不**用 DSH 原生 approval 帧承载（MCP 工具不触发它）；`/steer`（session.prompt mode=steer）只作运行中人工干预，不作审批裁决。
5. **会话内存（⑤）**：run 级 project context（--project 显式优先，不启发式猜测）+ run 事件日志（XDG state `runs/run-<ts>-<id8>/`：context.json/run.jsonl/dsn-session.txt，0700/0600）；`--resume <run-id>` 两分支：DSH 会话存活 → session.prompt 追加（DSH 原生历史）；失活 → run.jsonl 重建「此前进展摘要」注入新 DSH 会话并明示。术语：harness 侧称 **run**（运行时会话），DSH 宿主侧一律 **DSH session**（加限定词）。
6. **验收口径（⑥）**：离线 = FakeProvider 任务用例（追踪缺口→评审建议 denied→确认→approved，断言工具序列/审计两行/流式顺序；READ-only 零审计行）+ respx，为必过基线；live 冒烟两段式（A 段适配器机制零副作用——纯回答任务 + cancel，对 reqmesh 零请求，**无需部署前置立即可跑**；B 段真实任务 SMOKE-P5-001——denied→approved 双审计行 + 落库回读 + total 61→62，**需部署前置**）；provider 切换验收 = P5 提交对 P1–P4 资产（registry/groups/export/server/client/guardrails 裁决路径）**零 diff** + 396 基线不回退。OpenAI live 冒烟不在 P5（无 key）。

## 本会话核实的事实（spec「事实核实」节，开发会话以此为准，勿重新猜测）

DSH checkout 只读调查（`/home/user/.npm-global/lib/node_modules/@deepseek-ai/dsh`，v0.1.1-rc.2）+ 运行中宿主 127.0.0.1:8080 只读 live 探针 + harness 源码复核：

1. **RPC 信封**：`POST /api/<method>`，`{type:"client-request",rpcId,method,payload}` → `{type:"server-response",rpcId,result:{ok:true,value}|{ok:false,error}}`；**业务错误也是 HTTP 200**。关键方法 session.list/search/create/history/models/selectModel/rename/fork/prompt/attachment/updateQueue/cancel、subagent.*、workspace.*、skill.list、agentPreset.*、goal.*、llm.providers/models/discoverModels；**无任何 completion/工具往返端点**；session.export = `GET /api/session.export?sessionId=`（JSONL 下载）。
2. **session.create**：`{workspaceId|cwd 二选一, sessionId?, agentPreset?}` → `{sessionId}`；**session.prompt**：`{sessionId, mode:"queue"|"steer", content:[{type:"text",text}], clientTimeZone?}` → `{accepted:true}`——**queue=followup 语义（源码 `agent.followup(message)`）、steer=向运行中 turn 注入**；错误码 session-not-found/model-unavailable/agent-busy/steer-unavailable 等约 30 种。session.cancel → `{accepted:true}`。
3. **events.mux**：本机宿主 **WebSocket-only**（GET 实测 `426 Upgrade Required` + `upgrade: websocket`；dsh-client-connection 注册 upgrade 路由；in-process handler 的 SSE 形态不可达）——**适配器走 WS**（依赖 `websockets`）。帧 = `{type:"server-request",rpcId,method:<帧类型>,payload}`；MuxFrame 10 种：session/event、session/subscribed、approval/requested、approval/resolved、question/requested、question/resolved、session/queue、session/jobs、session/projection、stream/error。（design D10「events.mux SSE」表述与实测不符，按 spec 事实 4 实现 WS 路线；design 注记回写由 P5 开发会话完成后按惯例执行。）
4. **SessionEvent 词汇表 49 类**（envelope 严格 `{type,seq,time,data}`，data 宽）：assistant/chunk（text-delta/reasoning-delta/tool-call-chunks；**存储层打包为 text-chunks 等行，须展开**）、assistant/message（tool-call block 带参数）、tool/call{callId}、tool/result{source.callId, isError}、turn/start、turn/end{reason}、step/*、user/message、approval/asked、approval/decided、approval/policy 等。**完成判定 = turn/end + running=false**（session.list 的 running 字段实测存在）。
5. **认证**：无 token/cookie；`authority:"trusted-host"` 围栏（loopback 或 --trusted-host；--host 0.0.0.0 被显式拒绝）；harness 侧零凭据；DSH 宿主自持 provider 配置（live 实测 llm.providers：deepseek-official active）。
6. **DSH 原生审批/问题机制（与 harness 审批门两层独立）**：approval/requested（dsh-user-approval，覆盖 DSH 自己的工具）、question/requested（dsh-user-questions），均经 `POST /api/respond` 应答（approval: {sessionId,approvalId,outcome:allowed-once|rejected}）；**dsh-mcp-client 不声明 approval policy——MCP 工具不触发 DSH 原生 approval**。
7. **dsh-mcp-client 注册机制**：profile 的 cordis.patch.yml（用户 patch 层——profiles/web/cordis.yml 为「空 entry list + bundles」，文件头注明「Edit cordis.patch.yml, not this file」）追加条目：stdio `{serverName:"reqmesh", command, args:["--transport","stdio"], env, cwd}`；工具注册为 `mcp__reqmesh__<rawName>`；`failOnStartupError` 默认 false、`toolCallTimeoutMs` 默认 60000、自动重连默认开。**本机 web profile 当前无此条目**（B 段冒烟前置，见下）。
8. **harness 现状**：注册表 40 行（`registry.call` 统一入口）；审批门 fail-closed/每次重读/fix_hint；审计 version=1 一行一次写尝试（denied 也记）；`WhitelistStore.append`（规范化 TOML、原子 rename、0600）与 `approvals` CLI 同源；`export_openai_functions`（$defs 内联）即自驱 provider 的 tools 来源；cli.py 子命令分发可扩 `run`。**离线基线实测复跑：396 passed / 3 skipped / 2 deselected**。
9. **cessna-172**：total=61（P4 基线）；服务账号 reqmesh-harness（maintainer，P2 结论）；is_repo=false。B 段后 total=62（P1 惯例：P4 记录自此仅作历史快照）。

## P1–P4 复用点（勿重做，勿破坏）

- `tools/registry.py` / `tools/__init__.py`：`build_registry().all()` → ToolHint 清单（name/description 首行/level）与自驱 executor 的 `registry.call`；**零修改**。
- `tools/export.py`：`export_openai_functions` 被 #42 import 复用；**零修改**（对账测试保持 40 工具不变）。
- `guardrails/gate.py` + `whitelist.py` + `audit.py` + `approvals_cli.py`：确认中继只 import `WhitelistStore`/读审计文件；**三个模块零 diff**（#41 硬验收）。
- `_write_common.py`/写工具处理器：executor 经 `registry.call` 间接复用其门/审计/dry-run 全链路，**不复制**。
- `client/session.py`/`config.py`：XDG state/config 惯例与 `resolved_*` 模式沿用（#37 内存与 #38 适配器均用 Settings）；`errors.py` 仅新增 ProviderError。
- `server.py`/MCP 双 transport：不动；DSH 侧的 mcp__reqmesh__* 工具即现有 server 的 stdio 形态（部署步骤中的 command 即 console script）。
- 测试惯例：respx + fixture 文件化 + network-tagged 冒烟 + `docs/smoke/` 记录落盘（P1–P4 模式）；`.env` 凭据不落盘。

## DSH 部署步骤（显式部署输入，属 P6；**本 phase 只记录、不执行**）

B 段冒烟与「DSH 会话内驱动 40 工具」的前置（硬约束：不得修改运行中 DSH 宿主配置——8080 上正在运行的 Web 宿主即方向层工作环境）：

1. 追加到 `/home/user/.dsh/profiles/web/cordis.patch.yml`：

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

2. 重启 web 宿主（patch 是否被 HMR 拾取**未验证**，按需重启；重启会中断 8080 运行中会话，选维护窗口）。
3. 验证 DSH 会话内可见 `mcp__reqmesh__*` 40 工具。
4. 完整步骤落入 P6 部署文档（本交接只作输入记录）。

冒烟 #44：A 段**不需要**该前置（纯回答任务 + cancel，对 reqmesh 零请求）；B 段需前置已应用——未应用时只跑 A 段并在记录注明「B 段待前置后执行」，**开发会话不得自行改宿主配置**。

## 验收标准（epic → spec → tickets）

- provider 契约/FakeProvider/ProviderError（#36）；会话内存与 resume 两分支（#37）
- DSH 适配器契约逐字段 + 帧解析逐类型 + 完成判定/超时/cancel + 错误码映射（#38）
- loop 内核/指令模板/自驱 executor/两 execution 分支同 StreamSink（#39）
- run CLI 参数契约/流式渲染/TTY 与 --yes//steer/退出码/审计摘要（#40）
- 审批时序三通道 + 审计双行 + guardrails 三模块零 diff（#41）
- OpenAI 兼容 provider 请求形状与 40 工具 1:1 + 离线 respx（#42）
- 离线全绿 + 396 基线不回退 + P1–P4 资产零 diff（#43）
- 冒烟 A 段零副作用 + B 段（前置满足后）双审计行/落库回读/total 62 + 记录落盘（#44）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。

## 硬约束

- **本地提交，禁止 git push**（推送是方向层唯一职责，design §5）。
- 术语遵循 `CONTEXT.md`（审批门/权限层级/dry-run/审计/工作会话/认证会话；harness 侧运行时会话称 run，DSH 侧一律 DSH session）；与 ADR 冲突须显式指出（本会话：与 ADR-0001/0002 均无冲突，ADR-0001 的 Consequences 即 P5 的验收边界——工具层零改动）。
- 不动 `reqmesh/` 目录；**不修改 DSH checkout 与运行中 DSH 宿主配置**（部署步骤只记录）；不破坏 P1–P4 资产（registry/groups/export/server/client/guardrails 裁决路径零 diff，396 基线不回退）。
- 审批门 fail-closed 语义不变：agent 触达未白名单写工具 → 既有拒绝语义（denied 审计行 + fix_hint），确认通道只维护白名单文件（唯一裁决源），无临时放行通道。
- 凭据边界：harness 侧对 DSH 零凭据；REQMESH_OPENAI_API_KEY 为 SecretStr 且仅离线测试使用；凭据不进日志/审计/run 日志。

## 开发会话开场（可直接作为新工作会话的首条消息）

你是 P5 的「开发会话」——PRDMS 工程流程模型（docs/reqmesh-harness-design.md §5）中 P5 phase 的实施工作会话。只做实现与验证，不做需求决策；需求已由需求会话定案，规格即契约。

### 入口（先读，按顺序）
1. `docs/handoffs/p5-runtime.md` —— 本会话唯一交接索引：epic #5、tickets #36–#44 阻塞边与 frontier、需求会话决策摘要①–⑥、核实事实 9 条、P1–P4 复用点、DSH 部署步骤、硬约束。
2. `docs/specs/p5-runtime.md` —— 实施契约：事实核实 12 条、Implementation Decisions①–⑥、14 条验收标准（逐条挂 ticket）、Testing Decisions、Out of Scope。
3. `docs/reqmesh-harness-design.md`（§3 D5/D10/D11、§4 P5 行、§5 流程）、`CONTEXT.md`（术语，用词必须遵循）、`docs/adr/0001-mcp-core-tool-protocol.md`（Consequences：工具层与 provider 解耦——P5 即其兑现）、`docs/adr/0002-tool-naming-and-grouping.md`。
4. P1–P4 specs/handoffs 与 `reqmesh-harness/` 现有代码（复用，不要重做）；DSH checkout（只读调查，禁止修改）：`/home/user/.npm-global/lib/node_modules/@deepseek-ai/dsh`（v0.1.1-rc.2）；运行中宿主 `http://127.0.0.1:8080`。

### Tickets（frontier 顺序，阻塞边见上文表）
#36、#37 可并行 → #38、#39（#39 待 #37）→ #40 → #41（待 #39/#40）；#42 可随 #39 之后并行推进 → #43 收束全部代码 → #44 网络冒烟（A 段立即可跑，B 段按部署前置状态执行并注明）。

### 必须遵守的需求会话决策与事实（不要重议，spec 为准）
- provider 契约：`execution ∈ delegated|tool-loop` 执行所有权（DSH=delegated，openai/fake=tool-loop）；错误统一归一 `ProviderError(kind/code/message)`。
- DSH 集成：委托式（路线 A）是唯一形态——DSH 无裸推理/工具往返端点（UNARY_ROUTES 已核实）；events.mux 走 WebSocket（GET 实测 426 Upgrade Required，不是 design D10 写的 SSE）；完成判定 = turn/end + running=false。
- 工具层零改动：registry/groups/export/server/client 零 diff；guardrails 三模块（gate/whitelist/audit）零 diff（只 import）；errors.py 仅新增 ProviderError；40 工具注册表/导出对账不动。
- 审批门不变式：fail-closed、白名单唯一裁决源、每次调用重读、denied 审计行 + fix_hint 照旧；确认通道只维护白名单文件（`WhitelistStore.append`），无「本次放行」临时通道；denied→确认→重试 → 审计双行。
- 不修改 DSH checkout 与运行中宿主配置（cordis.patch.yml 注册步骤只记录——spec「DSH 部署步骤」，属 P6 输入）；冒烟 #44 的 B 段按前置状态执行并注明，A 段必须跑。
- 术语 CONTEXT.md：harness 侧称 run（运行时会话），DSH 宿主侧一律「DSH session」；审批门、权限层级、dry-run、审计、工作会话照词表。

### 流程（design §5）
- 用 tdd 技能实施（red-green-refactor，先测试后实现）；单元测试全部离线（FakeProvider + respx + DSH 帧 fixture，`tests/fixtures/dsh/` 新样本）。
- 实施完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话（入口 = 本交接文本）。
- 测试通过后：关 tickets #36–#44 → 产出完成报告（git 历史、测试结果、冒烟记录路径、issue 状态、待需求会话确认的实测偏差清单）→ 实测偏差按惯例回写 spec「实测偏差与决策」节 → 本地提交，禁止 git push。

### 硬约束
- 本地提交，禁止 git push（推送是方向层唯一职责，design §5）。
- 不动 `reqmesh/` 目录；不破坏 P1–P4 资产（离线基线 396 passed / 3 skipped 不回退，P5 提交对 P1–P4 核心资产零 diff）。
- 凭据不进日志/审计/run 日志；`.env` 不落盘；harness 对 DSH 零凭据（宿主自持 provider）。
- 冒烟记录落盘 `docs/smoke/P5-cessna-172.md`（时间戳、实例、DSH URL、帧计数、审计行、残渣清单、部署前置状态）。

### 完成标准（epic #5 底线）
- 内置 loop 能驱动 P1–P4 工具完成一个真实任务：离线 FakeProvider 任务用例（追踪缺口→评审建议 denied→确认→approved，断言工具序列/审计双行/流式顺序）全绿 + live 冒烟 A 段零副作用必过；B 段（SMOKE-P5-001 落库回读、total 61→62）在部署前置满足后通过。
- provider 切换（DSH ↔ Fake/OpenAI）不改工具层：同一注册表、同一审批门，P1–P4 资产零 diff。
- spec 验收标准 1–14 全部满足、无未决项；P1–P4 既有 396 passed 不回退。

## 需求会话回流确认（2026-09-02，开发会话完成报告核实后）

完成报告已实测核验（本会话独立复核，非仅读报告；入口 `docs/handoffs/p5-completion.md`）：

1. **git**：本地 main 领先 origin/main **3 commits**（e34d7fd→8eb24d7→9632874，未 push）；工作树干净；`git diff f8c7ee7..HEAD` 对 P1–P4 资产（tools/ client/ server.py guardrails/ ears/ lint/ report/）**为空**；P5 提交仅白名单内 errors.py/config.py/cli.py/pyproject.toml（+websockets）+ 新 runtime/ 包与测试/fixtures/冒烟/文档；reqmesh/ 上游目录未动；DSH checkout 未动。
2. **测试**：离线复跑 **533 passed / 3 skipped / 2 deselected**（16.7s，P4 基线 396 零回退；新增 137 用例 = 开发会话 115 + 测试子代理 22）。
3. **冒烟**：`docs/smoke/P5-cessna-172.md` 完整——A 段 live 通过（WS 流式 chunk×55、turn/end、running=false、cancel 归闲；对 reqmesh 零请求、审计 0 行、零副作用，且对宿主既有 30+ 会话零触碰）；B 段按部署前置状态记录「待前置后执行」（`REQMESH_P5_SMOKE_B=1` 重跑路径已备），符合 spec ⑥ 与本 phase 硬约束。
4. **issues**：#36–#44 全部 CLOSED（回流结论评论齐全）；epic #5 OPEN（按 design §5 由方向层推送后关闭）。
5. **9 项实测偏差全部确认接受**并回写 spec「实测偏差与决策」节（确认版）：
   - ①②⑤ 记录口径确认（全局 mux 流按 sessionId 过滤、完成判定双条件 + 0.3s 轮询、chunk 断言 >0）；
   - ③ B 段审计断言「恰 2 行」→**基线差 Δ2 行**（共享 XDG 文件下正确口径；B 段启用时 approvals/audit 走真实 XDG 使 run CLI 与 DSH 侧 MCP server 同源）；
   - ⑥ ③ 契约 `run_agentic` 改 **async**（已回写 spec 签名 + 注记；StreamSink 同步回调不变）；
   - ⑦ `--max-rounds` 显式化保留、`--provider fake` 仅库接口、`QuestionOption` wire fidelity；
   - ⑧ 代码标识符沿用 DSH RPC 字段名（协议 fidelity，与 CONTEXT.md 文档用语不冲突）；
   - ⑨ tool-loop 确认触发点 = denial 即确认（`confirm_now`，与 spec ④「同构」语义一致）。
6. **design doc**：D10 实现注记已回写（events.mux WebSocket-only，宿主版本相关）——方向层收口时随推送一并入库。

确认摘要记 #36/#38/#40/#41/#44 comment。方向层可执行：推送 origin（8eb24d7..HEAD）→ 关闭 epic #5。
