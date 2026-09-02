# reqmesh-harness 设计文档

> 状态：大方向定稿（需求澄清完成）。实现细节由各 phase 的需求会话产出 spec 细化。
> 术语见 [`CONTEXT.md`](../../CONTEXT.md)；工具协议决策见 [`docs/adr/0001-mcp-core-tool-protocol.md`](../adr/0001-mcp-core-tool-protocol.md)。

## 1. 背景与目标

PRDMS 在本地部署了 reqmesh v0.5.0（`http://172.16.100.2:8000`，需求管理工具，git 原生 YAML 存储）。本仓库自研 **reqmesh-harness**：一个外层 Agentic 编排运行时，把 reqmesh 的 REST API（约 180 个端点）封装成语义化工具供 LLM 调用，实现自然语言管需求、自动追踪/审查/分析，并带权限护栏。

## 2. 架构总览

```
LLM Host (DSH MCP client / Claude Desktop / 自建 chat)
   ── MCP (stdio | streamable-HTTP) ── 或 ── OpenAI function calling ──
              │ 工具调用 (JSON Schema)
reqmesh-harness (独立 Python 服务, PRDMS 仓库内 reqmesh-harness/)
  ├─ tools/        语义工具 + MCP schema（按权限分层）
  ├─ runtime/      planner→executor loop（可插拔 LLM provider，P5 落地）
  ├─ client/       类型化 HTTP 客户端（httpx + cookie/CSRF）
  ├─ guardrails/   权限策略 + 审批门 + dry-run + 审计日志
  └─ memory/       运行时会话态：project context、历史、游标
              │ REST + Cookie(CSRF)
        reqmesh :8000  (git 原生自动提交, 172.16.100.2)
```

## 3. 决策记录

| # | 决策 | 结论 | 依据 |
|---|------|------|------|
| D1 | 代码归属 | PRDMS 仓库内 `reqmesh-harness/` 子目录 | 一个仓库一个 tracker；`reqmesh/` 为上游部署克隆，gitignored |
| D2 | 首期形态 | 本会话只定大方向；按 P1–P6 拆分实施 | 每 phase 走需求会话 + 开发会话（含审核/测试子代理） |
| D3 | 技术栈 | Python 3.11 | 与 reqmesh 同栈；`openapi.json` → pydantic 复用契约；`mcp` SDK 成熟 |
| D4 | 对外协议 | MCP 为核（stdio + streamable-HTTP），再导出 OpenAI function JSON | 见 ADR-0001；DSH 可作 MCP client 直接消费 |
| D5 | MVP 是否内置 agent loop | 不内置；provider 留接口，P5 再落地 | MCP server 无 provider 依赖；环境无现成 API key |
| D6 | 权限模型 | READ / DRAFT / MUTATE / ADMIN 四级审批门 + dry-run | 读多写少；写卡确认、危险操作卡两道；reqmesh git 历史第三道兜底 |
| D7 | reqmesh 身份 | 专用服务账号（contributor）；admin 动作显式开启 | 最小权限；与 D6 分层对齐 |
| D8 | 旗舰用例顺序 | ① 自然语言建需求（EARS + quality lint 闭环）② 追踪/覆盖缺口报告 | 直观价值 + 全部落在 READ/DRAFT 层，风险最低 |
| D9 | 命名 | 目录/服务 `reqmesh-harness`，Python 包 `reqmesh_harness` | — |
| D10 | DSH 集成路线（事实核实） | DSH 暴露 loopback HTTP RPC（`/api/session.create`、`session.prompt` + `events.mux` SSE，无认证）；DSH 是 MCP **client**，可通过 `cordis.patch.yml` 注册外部 server | P5 的默认 provider 适配器走 loopback RPC；harness 的 MCP server 可直接被当前 DSH 消费 |
| D11 | 会话术语 | `session` 只指运行时会话；工程对话叫「工作会话」（需求/开发） | 用户用法与运行时概念冲突，已拆分并写入 CONTEXT.md |

### 实现注记（P2 开发会话核实后回写）

- **D7 角色细化**：reqmesh v0.5.0 将账号角色映射到项目权限层（`backend/app/core/dependencies.py`：`contributor→propose`、`maintainer→edit`、`admin→admin`）；propose 层仅可写 风险/评论/决策/变更请求，P2 写面其余 10 个端点要求 edit 层。故 P2 专用服务账号取 **maintainer**（能覆盖 P2 全部写工具的最小角色，非 admin）——D7 表中「contributor」指非 admin 专用账号语义，「admin 动作显式开启」不变；具体角色以 [`docs/specs/p2-write-path.md`](specs/p2-write-path.md) 为准。

### 实现注记（P5 开发会话核实后回写）

- **D10 路线细节修正（宿主版本相关）**：P5 适配器按本地宿主（v0.1.1-rc.2）实测实现——`events.mux` **WebSocket-only**（GET `/api/events.mux` 实测 `426 Upgrade Required` + `upgrade: websocket`；in-process handler 的 SSE 形态不可达）；D10 文中的「events.mux SSE」表述在该宿主版本不成立，已按 P5 spec 事实 4 走 WS 路线（依赖 `websockets`）。其余 D10 不变：loopback HTTP RPC（`/api/session.create|prompt|cancel|list`、`/api/respond`）零凭据 + `authority: trusted-host` 围栏；DSH 是 MCP **client**（dsh-mcp-client 注册 `mcp__reqmesh__*` 工具，工具执行在 harness MCP server 进程内，审批门/审计/dry-run 照常生效）。详见 [`docs/specs/p5-runtime.md`](specs/p5-runtime.md)「事实核实」。

## 4. 阶段计划（epic 已建）

| Phase | 内容 | Epic |
|---|---|---|
| P1 | 工具层 MVP：认证客户端 + READ 工具 + MCP 骨架（双 transport），cessna-172 冒烟 | [#1](https://github.com/GuangjieYu1/PRDMS/issues/1) |
| P2 | 写路径：MUTATE 工具 + 四级审批门 + 专用服务账号 | [#2](https://github.com/GuangjieYu1/PRDMS/issues/2) |
| P3 | 复合技能①：自然语言建需求（EARS + quality lint 闭环） | [#3](https://github.com/GuangjieYu1/PRDMS/issues/3) |
| P4 | 复合技能②：追踪/覆盖缺口报告 | [#4](https://github.com/GuangjieYu1/PRDMS/issues/4) |
| P5 | 内置运行时：agent loop + DSH provider 适配器（loopback RPC） | [#5](https://github.com/GuangjieYu1/PRDMS/issues/5) |
| P6 | 交付：evals + 部署（端口/systemd/LAN）+ 文档 | [#6](https://github.com/GuangjieYu1/PRDMS/issues/6) |

## 5. 工程流程模型（每个 phase 通用）

1. **需求会话**（单独对话，以 design doc + epic 为入口）：
   - 产出 `spec.md`（**本地提交，不推送**）+ 细粒度 tickets（GitHub，带 epic 引用）
   - 产出**交接文本**：epic #、ticket #、spec 路径、design doc 路径
   - 派发 = 交接文本落盘；开发会话以此开场
2. **开发会话**（单独对话，以交接文本为入口）：
   - 开发（tdd/implement 技能）→ 完成后**自动启动**审核子代理与测试子代理
   - **回流循环**：有阻塞项/失败用例则开发会话继续修；**每轮循环记录**在对应 ticket 的 comment（结论摘要）；**超过 5 轮仍失败 → 需求会话介入**重新对齐
   - 测试通过 → 开发会话关 tickets → 产出**完成报告**（git 历史、测试结果、冒烟记录路径、issue 状态）；**本地提交，不推送**
3. **方向层收口（本对话）**：
   - 核验完成报告（实测 git 历史 / 测试 / 冒烟记录 / issue 状态）→ **统一推送 origin** → 关闭 epic
   - **推送是方向层唯一职责**：需求/开发/审核/测试任何会话都不得 push；epic 只在代码已推送之后关闭

## 6. 各 phase 开放问题（由对应需求会话决策）

- **P1**：~~`openapi.json` → pydantic 模型生成方案（datamodel-code-generator 等）；工具命名前缀与分组方式~~ → 已决策：datamodel-code-generator + vendored 快照（见 P1 spec）；命名/分组见 [ADR-0002](adr/0002-tool-naming-and-grouping.md)
- **P2**：MUTATE 工具细分清单；审批确认的交互形态（CLI 确认 / 配置文件白名单）
- **P5**：provider 默认值（本地 DSH；DeepSeek API 需另供 key）；流式输出与审批门交互时序
- **P6**：部署端口与是否独立 systemd 单元；eval 集形态（脚本化断言）

## 7. 验证基线

- 目标实例：`http://172.16.100.2:8000`（`RT_PROFILE=personal`）
- 演示项目：`cessna-172`（57 条需求，参数化 + 风险登记册齐备）
- 认证机制（已核实源码）：`/api/auth/login` 返回 `Set-Cookie: token`(HttpOnly JWT) + `csrftoken` + body `csrf_token`；写请求带 `X-CSRF-Token`；无 `token` cookie 时 CSRF 中间件放行，`Authorization: Bearer <token>` 亦受支持
