# P5 开发会话完成报告：内置运行时（agent loop + provider 可插拔 + DSH 适配器 + 会话内存）

> 产出时间：2026-09-02（开发会话收口）；依据 design §5 流程：本地提交，**未推送**（推送是方向层唯一职责）。

## 1. 入口与范围

- Epic：#5；Tickets：#36–#44（状态见 §6）
- Spec：docs/specs/p5-runtime.md；交接：docs/handoffs/p5-runtime.md
- 硬约束核对：未 push；P1–P4 资产零 diff（见 §3 核对表）；未修改 DSH checkout 与运行中 DSH 宿主配置
  （B 段部署前置只记录，spec「DSH 部署步骤」属 P6 输入）；未动 reqmesh/ 目录。

## 2. 交付物

| 产物 | 路径 |
|---|---|
| provider 契约（#36） | `runtime/provider.py`（AgentRequest/RunResult/StreamSink/Provider/ProjectContext/ToolHint/Question/ToolCallRequest）+ `errors.ProviderError`（kind/code/message） |
| FakeProvider（#36） | `runtime/fake.py`（脚本化步骤 Text/Tool/Question/End + 顺序断言 → ProviderError(protocol)） |
| 会话内存（#37） | `runtime/memory.py`（RunRecorder：run-<ts>-<id8>(-resume)/context.json/run.jsonl/dsn-session.txt，0700/0600；rebuild_summary；LoggingSink） |
| DSH 适配器（#38） | `runtime/dsh_provider.py`（DshRpcClient 信封/respond；parse_frame 10 种 MuxFrame；chunk 打包行展开；MuxHandler；完成判定 turn/end+running=false；空闲超时；session.cancel；steer(mode=steer)；cancel_remote） |
| loop 内核（#39） | `runtime/loop.py`（assemble_request/指令模板/executor/run_task/RunDriver 两执行所有权分支） |
| run CLI（#40） | `runtime/run_cli.py` + cli.py 分发（参数/流式渲染/重试/审计摘要/退出码 0/1/130；TTY /steer） |
| 确认中继（#41） | `runtime/confirm.py`（ConfirmationRelay 三通道 + ConfirmedToolExecutor；规则与 approvals CLI 同源） |
| OpenAI provider（#42） | `runtime/openai_provider.py`（tools=export_openai_functions 1:1、SSE 流解析、防御轮数、无 key→unavailable） |
| 配置（P5 Settings） | `config.py`（provider/dsh_*/runs_dir/openai_*；保留 P1–P4 全部既有项） |
| 离线测试（#43） | 新增 9 个测试文件 + tests/fixtures/dsh/（帧样本 21 个）+ tests/fixtures/openai/（SSE 样本 2 个）；测试子代理补 4 个边缘用例文件 |
| 冒烟（#44） | `scripts/smoke_p5.py`（A 段必跑/B 段按前置状态）；记录 `docs/smoke/P5-cessna-172.md`（live 通过） |
| 文档回写 | design「D10 实现注记」（events.mux WebSocket-only）；spec「实测偏差与决策」节（8 条待需求会话确认） |

## 3. P1–P4 资产零 diff 核对（验收 12）

`git diff HEAD -- reqmesh-harness/src/reqmesh_harness/tools/ reqmesh-harness/src/reqmesh_harness/guardrails/reqmesh-harness/src/reqmesh_harness/client/ reqmesh-harness/src/reqmesh_harness/server.py` — 为空。
改动文件仅白名单：`errors.py`（+ProviderError）、`config.py`（+P5 配置）、`cli.py`（+run 分发）、`pyproject.toml`（+websockets 依赖）。
`gate.py/whitelist.py/audit.py` 三模块零 diff（确认中继只 import `WhitelistStore`/`AuditLog`/`approvals_cli` 常量与 `summarize_params`）。

## 4. 测试结果

- 全量离线：**533 passed / 3 skipped / 2 deselected（network 冒烟）**；P1–P4 既有 396 零回退；
  新增 137 个用例（开发会话 115 + 测试子代理 22）。
- 离线覆盖（对应验收 1–11）：provider 契约字面量；FakeProvider 脚本/顺序失配/取消；run 目录权限与 resume 两分支；
  DSH 帧解析逐类型 + 打包行展开 + 错误码映射表 + 完成判定/超时/cancel/steer；指令模板关键句；executor 错误回灌/未知工具名；
  audit 双行（denied+approved）与 READ-only 零审计；CLI 参数/渲染/退出码/审计摘要；OpenAI 请求形状 1:1/SSE/防御轮数。
- 测试真实性（测试子代理核验）：离线无隐藏网络依赖；断言均为外部行为（respx 打桩 + fixture + capsys）。

## 5. 冒烟（#44）

- **A 段（live 通过）**：session.create → session.prompt（纯回答任务）→ WS 帧断言（session/subscribed、
  assistant/chunk >0、turn/end）→ session.list running=false；慢任务 session.cancel accepted + 归闲；
  对 reqmesh **零请求**、审计 **0 行**、零副作用。
- **B 段（SMOKE-P5-001）**：部署前置未满足（`/home/user/.dsh/profiles/web/cordis.patch.yml` 无 mcp-reqmesh 条目；
  本 phase 硬约束不得修改运行中 DSH 宿主配置）→ 按 spec ⑥ 记录「待前置后执行」；
  前置应用后 `REQMESH_P5_SMOKE_B=1 python scripts/smoke_p5.py` 全量重跑（断言：denied→approved 双审计行、
  落库回读 description 相等 + status=proposed、total 61→62、流式帧顺序、无 approval/requested 帧）。

## 6. Issue 状态

- ✅ #36 provider 契约与 FakeProvider · ✅ #37 会话内存 · ✅ #38 DSH provider 适配器 ·
  ✅ #39 loop 内核与自驱 executor · ✅ #40 run CLI 与流式渲染 · ✅ #41 审批门交互时序 ·
  ✅ #42 OpenAI 兼容 provider · ✅ #43 离线测试套件（含回归） · ✅ #44 冒烟（A 段通过，B 段按前置状态记录）
- Epic #5：保持 open（按 design §5：epic 在方向层推送后关闭）。

## 7. 回流记录

- 第 1 轮（审核 + 测试子代理并行）：见 §8 与对应 ticket comments。测试子代理补充 22 个边缘用例（全绿）并提出两项建议，均已落实：① `record_text` 截断 2000（run.jsonl 无界增长防御）；② tool-loop 路线 TTY 确认通道补 `confirm_now` 触发点（denial 即确认，spec 偏差表第 9 行）。
  审核：Standards 7 项判断项（重复：`_summarize`/`_level_of`/`_LEVELS_NEEDING_PROJECT`/denied 嗅探、
  `_DSN_FILE` 笔误、测试戳私有字段、死代码；max-rounds=8 两处字面量接受并注明）——已修复除
  max-rounds/QuestionOption 外的全部；Spec 5 项轻微（async run_agentic 字面偏差等 → 记 spec 偏差节待确认）。
  测试子代理：补 22 个边缘用例（全部通过），覆盖 prompt 载荷逐字段/多问题逐 id 应答/approval 帧不代答/
  reasoning 折叠与展开/损坏 context.json fail-fast/截断/审计摘要计数/openai SSE 空行与非对象参数等。
- 第 2 轮（核验）：全量 533 passed；审核修复项 1–5 逐条复验通过（5 的最后一处私有字段访问随后收口），3 个非阻塞剩余项全部落实：① test_dsh_provider 取消用例改 `on_session=` 构造注入；② `confirm_now` 的 tool-loop 同步确认已记 spec 偏差表第 9 行（与 spec ④「同构」语义一致，待需求会话确认）；③ spec/completion 测试计数校正为 533/137。

## 8. 实测偏差（待需求会话确认——完成报告不代做决策）

见 `docs/specs/p5-runtime.md`「实测偏差与决策」小节（8 条）。要点：
（1）events.mux 为 WebSocket-only（设计 D10 的 SSE 表述修正——design 实现注记已回写）；
（2）events.mux 为全局多路复用流（连接级回放 subscribed/projection，适配器按 sessionId 过滤）；
（3）B 段基线差断言口径（共享 XDG 文件下「恰 2 行」改为「delta 2 行」——run CLI 与 DSH 侧 MCP server 进程共享审批/审计文件）；
（4）run_agentic 实现为 async（③ 的字面 sync 偏差）；
（5）`--max-rounds`/`--provider fake` 拒绝/QuestionOption 为显式附加（wire fidelity）；
（6）代码标识符沿用 DSH RPC 契约字段名（文档层面已用「DSH session」限定词）。

## 9. 后续演进提示

- P6 部署输入：DSH 部署步骤（cordis.patch.yml 注册 mcp-reqmesh）已记录在 spec/交接；B 段冒烟随部署后执行。
- OpenAI 兼容 provider 的 live 冒烟与恢复（无 key 环境，D5）——P6 供 key 后复用 smoke 变体。
