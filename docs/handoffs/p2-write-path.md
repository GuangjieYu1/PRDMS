# 交接文本：P2 写路径（需求会话 → 开发会话）

> 派发时间：2026-09-01。开发会话以此文件为入口。

## 索引

- **Epic**：[#2](https://github.com/GuangjieYu1/PRDMS/issues/2) [P2] 写路径：MUTATE 工具 + 四级审批门 + 专用服务账号
- **Spec**：`docs/specs/p2-write-path.md`
- **Design doc**：`docs/reqmesh-harness-design.md`（§3 D6/D7、§5 流程、§7 验证基线）
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md) · [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)（P2 将回写 verb 词汇表实现注记）
- **P1 参考（勿重做）**：`docs/specs/p1-tool-layer-mvp.md` · `docs/handoffs/p1-tool-layer-mvp.md` · `reqmesh-harness/` 现有代码

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#17](https://github.com/GuangjieYu1/PRDMS/issues/17) | 写路径客户端：POST/PUT/PATCH/DELETE + X-CSRF-Token + PUT 部分更新语义 | — |
| [#18](https://github.com/GuangjieYu1/PRDMS/issues/18) | 审批门与白名单：fail-closed 裁决 + approvals CLI + ADMIN 显式开启预留 | — |
| [#19](https://github.com/GuangjieYu1/PRDMS/issues/19) | 首个写切片：create_requirement 经 MCP 可调用（dry_run + 审批门接线） | #17, #18 |
| [#20](https://github.com/GuangjieYu1/PRDMS/issues/20) | DRAFT 工具组（5 工具：component/verification/risk/comment/review） | #19 |
| [#21](https://github.com/GuangjieYu1/PRDMS/issues/21) | MUTATE 工具组（6 工具：update/set_relations/set_allocation/run_verification…） | #19 |
| [#22](https://github.com/GuangjieYu1/PRDMS/issues/22) | 工具调用级审计日志（JSONL + 字段契约） | #18, #19 |
| [#23](https://github.com/GuangjieYu1/PRDMS/issues/23) | 注册表扩展与 OpenAI 导出对账（37 工具 + 层级元数据 + ADR 回写） | #20, #21 |
| [#24](https://github.com/GuangjieYu1/PRDMS/issues/24) | cessna-172 冒烟：dry_run 全量 + 最小真实写闭环 | #20, #21, #22 |

frontier 首步：#17、#18（可并行）；随后 #19、#22；再后 #20、#21、#23 可并行；#24 收尾（网络冒烟）。

## 本会话决策摘要（开发会话必须遵守）

1. **开放问题① MUTATE 工具细分（12 个 = 6 DRAFT + 6 MUTATE）**：
   - DRAFT（新建/评审，只增不改）：`create_requirement`、`create_component`、`create_verification_case`、`create_risk`、`create_comment`、`review_item`。
   - MUTATE（修改既有，影响追踪/覆盖）：`update_requirement`、`set_relations`（PUT /traces）、`set_allocation`（POST /allocation）、`update_component`、`update_verification_case`、`run_verification`。
   - 全部写工具统一 `dry_run` 参数；MUTATE 统一必填 `reason`（只进审计，不进 reqmesh 数据）；create 类 `id` 由调用方给定；请求体复用 P1 生成模型。
   - 延后清单见 spec：`update_risk`、decision/analysis/specification/definition/change-request 写族、bulk/rename/cascade 族、`review_all`、system-states 写族、baselines create/order、`next-uid`/`next-id` → P3/P4 按需只加注册行；CR `redline`/baseline `diff` 预览端点 → P3/P4 dry-run 对齐时优先复用。
   - **ADMIN 层默认不在 P2**（全部 DELETE、CR execute/reject、freeze 基线、git push/restore、publish、import、用户/系统管理、项目建删）：预留机制 = 注册表 ADMIN 分区 + `REQMESH_ENABLE_ADMIN=1` 才安装（未开启不出现在 tools/list）+ 白名单双卡（D6「两道卡」= D7「显式开启」+ 白名单）。
2. **开放问题② 审批门交互形态（分层组合）**：**配置文件白名单是唯一裁决源（P2 落地）+ CLI 子命令 `reqmesh-harness approvals {list,add,remove}` 作为交互式维护入口**（TTY 下 y/N 确认、`--yes` 供脚本；与手改 TOML 同源同文件）。「调用中途弹窗确认」（MCP elicitation）延后 P5——stdio 的 stdin/stdout 是协议通道不可弹窗，streamable-HTTP 无终端，design §6 已把交互时序列为 P5 开放问题。
   - 差异处理：DRAFT 条目 project 可省略（通配全部项目）；MUTATE 条目 tool+project 必填（禁通配）；`dry_run_only` 条目只放行 dry_run；fail-closed，拒绝错误含精确 `approvals add` 命令与 TOML 片段；白名单每次调用重读。
3. **dry-run 语义**：统一 `dry_run: bool=False`；审批门照跑（dry-run 不是绕过审批的后门）；批准后不发写请求，返回 `{dry_run:true, would_send:{method,path,body}, checks}`；**不产生 git 提交**（冒烟以 git 提交计数断言）；未来包装原生 `dry_run` 参数端点（import/bulk-reparent）或预览端点时优先复用原生能力。
4. **审计日志**：JSONL append-only、0600，`REQMESH_AUDIT_FILE`（默认 XDG state）；每次写工具调用一行（含 denied/dry_run/错误路径），READ 不记；字段契约 version=1 见 spec 审计节（tool/参数摘要/decision/result 等）；参数摘要脱敏、不含凭据；无 READ 工具读取审计文件。
5. **服务账号（D7）**：约定新建专用账号 `reqmesh-harness`（role=contributor），操作员用 admin 凭据一次性创建（人工前置，写入 README 与冒烟前置）；不复用 yugj（个人账号违背最小权限）。凭据仅环境变量 `REQMESH_USERNAME`/`REQMESH_PASSWORD`（沿用 P1，`.env` 已 gitignore）。冒烟 whoami 断言；未建号允许降级 yugj 并在记录显式标注。匿名只读验证：无凭据调用 READ 工具 → 上游 401/403 经 `UpstreamError` 透传。
6. **写客户端契约**：写请求挂 `X-CSRF-Token`（`_csrf_headers` 已就绪）；连接错误不重试、401 重登一次并重试；PUT 部分更新 = `exclude_unset` 语义、显式 null 清空字段；错误两种形状归一化 `UpstreamError`；`WriteClient` 构造需 GateToken（结构护栏，与 P1 只读护栏对称）。
7. **ADR-0002 回写**：verb 词汇表扩展 `create/update/set/run/review`（`delete` 词汇表预留 ADMIN）——ADR 预告内的扩展，开发会话完成后按 P1 同款「实现注记」回写，非冲突。

## P1 复用点（勿重做，勿破坏）

- `client/session.py` `AuthSession`：登录/Cookie+CSRF 持久化/401 重登/Bearer 兜底/`_csrf_headers()`——P2 只增写方法。
- `client/reader.py` `ReadOnlyClient` 护栏模式 → `client/writer.py` `WriteClient` 对称实现。
- `tools/registry.py`：`ToolSpec.level` 四级 Literal 已预留、`meta.domain/permission`、`annotations_for`——P2 扩展 DRAFT/MUTATE/ADMIN 映射与 ADMIN 分区，不改 READ 行为。
- `client/generated/models.py`：请求体模型齐备（`RequirementCreate/Update`、`TraceMatrix`、`AllocationRequest`、`ReviewRequest`、`RunVerification`、`ComponentCreate/Update`、`VerificationCaseCreate/Update`、`RiskCreate`、`CommentCreate`）——PUT 序列化复用，禁手改生成产物。
- `tools/export.py` OpenAI 导出、`server.py` 双 transport 装配、`tests/mapping.py` 可执行映射表、`tests/support/stub_server.py` 与 respx fixture 模式、`scripts/smoke_p1.py` 冒烟模式。
- `config.py` `Settings`：新增 `REQMESH_APPROVALS_FILE` / `REQMESH_AUDIT_FILE` / `REQMESH_ENABLE_ADMIN` 三个环境变量。

## 验收标准（epic → spec → tickets）

- 未批准写操作被阻断（fail-closed + 结构护栏；#18、#19、单测）
- dry_run 不产生 git 提交（#24 冒烟 git 提交计数断言）
- 审计日志含工具名/参数摘要/结果状态等指定字段（#22）
- 服务账号可写、匿名只读（#24 whoami/真实写/匿名透传断言）
- 每类工具对 cessna-172 的冒烟断言点见 spec 映射表末列（#24）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。

## 硬约束

- **本地提交，禁止 git push**（推送是方向层唯一职责，design §5）。
- 术语遵循 `CONTEXT.md`（审批门/权限层级/dry-run/认证会话等）；与 ADR 冲突须显式指出。
- 不动 `reqmesh/` 目录（上游部署克隆）；不动已关闭的 P1 资产（只扩展、不重构）。
