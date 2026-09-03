# Changelog

本项目的所有显著变更都记录在此文件（Keep a Changelog 格式；语义化版本）。
版本号唯一事实源：[pyproject.toml](pyproject.toml)（project.version）；发布流程见 [RELEASING.md](RELEASING.md)。

## [Unreleased]

### 变更

- 无。

## [0.2.0] - 2026-09-03

P1–P6 里程碑首个可发布版本（大方向：reqmesh 工具层 + 写路径/审批门/审计 + 复合技能 + 内置运行时 + 交付）。

### P1 工具层 MVP（ticket 集 #7–#14）

- 类型化 HTTP 客户端：认证会话（cookie/CSRF + Bearer 兜底 + 401 重登）、只读视图（仅 get）、写视图（仅 post/put/patch/delete，构造需审批门 GateToken）。
- MCP server 双 transport（stdio + streamable-HTTP，ADR-0001）：27 个 READ 工具 + OpenAI function JSON 导出。
- 工具注册表唯一事实源（ADR-0002 命名 verb_entity；description 唯一来源 = 处理器 docstring；25 READ 工具 + schema/只读对账）。

### P2 写路径（ticket 集 #15–#24）

- 12 个写工具（6 DRAFT + 6 MUTATE）+ dry_run 预览（写负载形状 + 本地 checks，不写库）。
- 四级审批门（READ/DRAFT/MUTATE/ADMIN 预留）：白名单唯一裁决源、每次调用重读、fail-closed、MUTATE 要求具体 project、dry_run_only 灰度条目。
- 工具调用级审计日志（JSONL append-only、0600、version=1 字段契约、一行一次写尝试含 denied/dry_run/错误路径）。
- reqmesh-harness approvals <list|add|remove> CLI（白名单维护）；专用服务账号（maintainer 角色约定）。
- ADMIN 分区 + REQMESH_ENABLE_ADMIN=1 显式开启（未开启不在 tools/list）。

### P3 复合技能①（ticket 集 #25–#30）

- draft_requirement：自然语言 → EARS 五句式（模板 auto/ubiquitous/event/unwanted/state/optional）→ 本地 quality lint 迭代（≤N 轮确定性修正）→ 过线后经审批门落库；绝不编造内容（占位符即拒绝）；get_requirement_quality 需求级品质反馈。
- EARS 解析/渲染（纯确定性英文槽位）与本地 lint 引擎（20 条规则镜像 + 6 类修正表；独立重写，不复制上游源码）。

### P4 复合技能②（ticket 集 #31–#35）

- get_traceability_gap_report：单次调用聚合六源（coverage/gap-analysis/traces/suspect-links/unreviewed/allocation-matrix）→ summary/chapters/gaps/meta 结构化报告；12 类缺口维度 + 规则驱动建议（纯建议不执行）；全 READ 零写。
- 报告聚合内核（纯函数零网络）+ 建议模板表（12 类维度）。

### P5 内置运行时（ticket 集 #36–#44）

- provider 契约（AgentRequest/StreamSink/RunResult/ProviderError）与三种实现：DSH（默认，委托路线：loopback RPC + WS events.mux）、OpenAI 兼容（自驱）、Fake（脚本化离线测试）。
- 会话内存：run 目录（XDG state、0700/0600）+ context.json/run.jsonl/dsn-session.txt；resume 两分支（DSH 会话存活追加 / 失活重建摘要）。
- reqmesh-harness run CLI：流式渲染、TTY /steer、确认中继三通道（预先白名单 > --yes 自动 > TTY 逐条）、run 结束审计摘要。
- loop 内核：任务指令模板（工具清单 + 三条规则 + 轮次上限）、自驱 executor（registry.call 全链路、ApprovalDeniedError 文本回灌含 fix_hint）、确认重试时序。

### P6 交付（ticket 集 #45–#51）

- evals 黄金任务集：evals/tasks.py（G1–G5 任务定义 = 数据：期望工具序列 + 参数匹配器 + 最终状态断言 + 审计期望）+ evals/run_offline.py（零网络，退出码 0 即全绿）+ evals/run_live.py（network-tagged，DSH 委托路线 G1–G4）。
- 部署形态：正式端口收编 8081（默认 127.0.0.1；REQMESH_HARNESS_HOST/PORT + CLI --host/--port）；免 root scripts/run_server.sh（start|stop|status|logs）；systemd 单元模板 deploy/systemd/reqmesh-harness.service。
- DSH 集成：scripts/dsh_register.sh（幂等 + dry-run diff + 备份；stdio 注册条目按 spec 决策③；应用/重启责任 = 操作员维护窗口）。
- 文档：仓库根 README.md（项目地图 + phase 状态表）、reqmesh-harness/README.md 扩充（八节结构）、docs/deployment.md（部署/DSH 注册/LAN 安全口径/上游边界）。
- 同步：uv.lock 版本同步 0.2.0（uv lock --check 通过；P5 遗留的 websockets 漂移已由父提交修复）。

[Unreleased]: https://github.com/GuangjieYu1/PRDMS/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/GuangjieYu1/PRDMS/releases/tag/v0.2.0
