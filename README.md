# PRDMS

PRDMS 是需求管理工具链的主工作区：本地部署 **reqmesh** 作为数据层，自研 **reqmesh-harness** 作为外层 Agentic 编排运行时（把 reqmesh 的 REST API 封装为语义化 MCP 工具供 LLM 调用，并带四级审批门/审计/内置运行时屏障）。

- 术语与设计：`CONTEXT.md` · [`docs/reqmesh-harness-design.md`](docs/reqmesh-harness-design.md)（§5 为工程流程模型）
- 协议决策：[ADR-0001 MCP 核心工具协议](docs/adr/0001-mcp-core-tool-protocol.md) · [ADR-0002 工具命名与分组](docs/adr/0002-tool-naming-and-grouping.md)

## 仓库布局

| 路径 | 职责 |
|---|---|
| `reqmesh-harness/` | 自研编排运行时（Python 包 reqmesh_harness）：工具层/写路径/复合技能/内置运行时/evals/部署脚本 |
| `docs/design.md` 系 | `docs/reqmesh-harness-design.md`（大方向）· `docs/specs/p1–p6-*.md`（逐 phase 规格=契约）· `docs/handoffs/p1–p6-*.md`（需求↔开发会话交接） |
| `docs/smoke/P*-cessna-172.md` | 逐 phase 冒烟/evals live 记录（时间戳/实例/每步结果/残渣清单） |
| `docs/deployment.md` | 部署长文档（8081 服务/免 root 脚本/systemd/DSH 注册/LAN 安全口径/上游边界） |
| `reqmesh/` | 上游 reqmesh 部署克隆（v0.5.0；**gitignored，不进本仓库历史**；安装/升级见其自身文档） |

## Phase 状态（P1–P6）

| Phase | 内容 | Epic | 状态 |
|---|---|---|---|
| P1 | 工具层 MVP（认证客户端 + READ 工具 + MCP 双 transport） | [#1](https://github.com/GuangjieYu1/PRDMS/issues/1) | ✅ 完成 |
| P2 | 写路径（MUTATE 工具 + 四级审批门 + 服务账号） | [#2](https://github.com/GuangjieYu1/PRDMS/issues/2) | ✅ 完成 |
| P3 | 复合技能①（自然语言建需求：EARS + lint 闭环） | [#3](https://github.com/GuangjieYu1/PRDMS/issues/3) | ✅ 完成 |
| P4 | 复合技能②（追踪/覆盖缺口报告） | [#4](https://github.com/GuangjieYu1/PRDMS/issues/4) | ✅ 完成 |
| P5 | 内置运行时（agent loop + DSH/OpenAI/Fake provider） | [#5](https://github.com/GuangjieYu1/PRDMS/issues/5) | ✅ 完成 |
| P6 | 交付（evals + 部署 + 文档/版本 0.2.0） | [#6](https://github.com/GuangjieYu1/PRDMS/issues/6) | 🔄 开发会话实施中 |

## 快速开始

```bash
git clone <repo> /path/PRDMS && cd /path/PRDMS/reqmesh-harness
uv sync                  # 安装依赖（uv.lock 锁定）
uv run pytest            # 离线基线：533 passed / 3 skipped / 2 deselected（evals 不在集合）
```

然后按 [reqmesh-harness/README.md](reqmesh-harness/README.md) 继续：认证（env 凭据）→ 审批门/审计 → `approvals`/`run` CLI → MCP 双 transport → evals → 冒烟；部署见 [docs/deployment.md](docs/deployment.md)。

## 文档索引

- 设计：[docs/reqmesh-harness-design.md](docs/reqmesh-harness-design.md)（决策 D1–D11、phase 计划、工程流程模型 §5、验证基线 §7）
- 规格（逐 phase，需求会话产出）：[p1](docs/specs/p1-tool-layer-mvp.md) · [p2](docs/specs/p2-write-path.md) · [p3](docs/specs/p3-nl-requirements.md) · [p4](docs/specs/p4-traceability-report.md) · [p5](docs/specs/p5-runtime.md) · [p6](docs/specs/p6-delivery.md)
- 交接（开发会话入口）：[p1](docs/handoffs/p1-tool-layer-mvp.md) · [p2](docs/handoffs/p2-write-path.md) · [p3](docs/handoffs/p3-nl-requirements.md) · [p4](docs/handoffs/p4-traceability-report.md) · [p5](docs/handoffs/p5-runtime.md) · [p6](docs/handoffs/p6-delivery.md)
- 冒烟/evals 记录：[P1](docs/smoke/P1-cessna-172.md) · [P2](docs/smoke/P2-cessna-172.md) · [P3](docs/smoke/P3-cessna-172.md) · [P4](docs/smoke/P4-cessna-172.md) · [P5](docs/smoke/P5-cessna-172.md) · [P6](docs/smoke/P6-cessna-172.md)
- 部署：[docs/deployment.md](docs/deployment.md) · 发布：[reqmesh-harness/RELEASING.md](reqmesh-harness/RELEASING.md) · 变更：[reqmesh-harness/CHANGELOG.md](reqmesh-harness/CHANGELOG.md)

## 工程流程（§5）

每个 phase 走「需求会话 → 开发会话 → 方向层收口」：需求会话产出 spec + tickets + 交接文本；开发会话实施并自动启动审核/测试子代理回流，完成后关 tickets、产出完成报告；方向层负责推送、关闭 epic（推送是方向层唯一职责，任何会话不得 push）。
