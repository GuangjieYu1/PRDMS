# 交接文本：P1 工具层 MVP（需求会话 → 开发会话）

> 派发时间：2025-09-01。开发会话以此文件为入口。

## 索引

- **Epic**：[#1](https://github.com/GuangjieYu1/PRDMS/issues/1) [P1] 工具层 MVP：认证客户端 + READ 工具 + MCP 骨架
- **Spec**：`docs/specs/p1-tool-layer-mvp.md`
- **Design doc**：`docs/reqmesh-harness-design.md`
- **相关 ADR**：[0001 MCP 核心协议](docs/adr/0001-mcp-core-tool-protocol.md) · [0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)
- **已入库工件**：`reqmesh-harness/openapi/reqmesh-0.5.0.json`（模型生成快照，来自 `http://172.16.100.2:8000`）

## Tickets（阻塞边已声明，frontier 顺序）

| Ticket | 标题 | Blocked by |
|---|---|---|
| [#7](https://github.com/GuangjieYu1/PRDMS/issues/7) | 工程骨架与 OpenAPI 模型生成管线 | — |
| [#8](https://github.com/GuangjieYu1/PRDMS/issues/8) | 认证客户端（登录 + Cookie/CSRF 会话维护） | #7 |
| [#9](https://github.com/GuangjieYu1/PRDMS/issues/9) | 首个端到端切片：list_requirements 经 MCP stdio 可调用 | #7, #8 |
| [#10](https://github.com/GuangjieYu1/PRDMS/issues/10) | 认证/项目 + 需求域 READ 工具组（8 工具） | #9 |
| [#11](https://github.com/GuangjieYu1/PRDMS/issues/11) | 追踪/覆盖域 READ 工具组（5 工具） | #9 |
| [#12](https://github.com/GuangjieYu1/PRDMS/issues/12) | 风险/决策/验证/分析/规格/定义域 READ 工具组（7 工具） | #9 |
| [#13](https://github.com/GuangjieYu1/PRDMS/issues/13) | 组件/基线/变更请求/报告域 READ 工具组（4 工具） | #9 |
| [#14](https://github.com/GuangjieYu1/PRDMS/issues/14) | MCP streamable-HTTP transport | #9 |
| [#15](https://github.com/GuangjieYu1/PRDMS/issues/15) | OpenAI function JSON 导出 | #10–#13 |
| [#16](https://github.com/GuangjieYu1/PRDMS/issues/16) | cessna-172 冒烟（登录→查需求→查覆盖率） | #10, #11 |

frontier 首步：#7、#8；随后 #9；再后 #10–#14 可并行；#15 收尾；#16 为网络冒烟。

## 本会话决策摘要（开发会话必须遵守）

1. **工具集定案 25 个**（epic 预估「约 22」）：映射表即契约，见 spec「Implementation Decisions」表格；84 个 GET 中延后包装的清单见 spec「Out of Scope」（管理/系统域→P6，执行/产出型→P3/P4，写流程辅助→P2/P3）。
2. **模型生成（开放问题①）**：`datamodel-code-generator`（dev 依赖，uv.lock 锁版）+ vendored 快照 + 产物提交禁手改。关键事实：reqmesh openapi 响应体 schema 为空 `{}`，生成模型只用于请求体/实体（79 个）与 fixture 校验；**P1 工具层响应为原始 JSON 透传**。
3. **命名（开放问题②，ADR-0002）**：server 名 `reqmesh`；`<verb>_<entity>` snake_case；无权限前缀；层级在注册表 + `readOnlyHint` + description（`READ-ONLY` 开头，中文）；合并模式（可选 id / enum 参数）按 ADR-0002。
4. **只读护栏**：工具层结构上仅暴露 `get()`（无非 GET 路径）+ 测试断言 HTTP 方法 ⊆ {GET}。
5. **认证**：登录 → cookie(`token`/`csrftoken`) + body `csrf_token` 持久化（XDG state）；401 重登一次；凭据仅环境变量（`REQMESH_USERNAME`/`REQMESH_PASSWORD`）。
6. **分页**：`offset`/`limit` 透传（默认 500/上限 2000），不自动翻页（P3/P4 事）。

## 验收标准（epic → spec）

- 登录失败/成功路径测试通过（#8）
- 每个 READ 工具 schema 校验通过、只读无副作用（#9–#13）
- MCP stdio 与 streamable-HTTP 均可启动并可列出工具（#9、#14）
- 冒烟通过记录落盘 `docs/smoke/P1-cessna-172.md`（#16）

## 回流规则（design §5）

开发会话完成后自动启动审核子代理与测试子代理；每轮循环结论摘要记入对应 ticket comment；超过 5 轮仍失败 → 回到需求会话重新对齐（入口本文件）。
