# reqmesh-harness

reqmesh 需求管理工具的 Agentic 编排运行时（见 `docs/reqmesh-harness-design.md`；P1 范围见 `docs/specs/p1-tool-layer-mvp.md`，P2 范围见 `docs/specs/p2-write-path.md`，P3 范围见 `docs/specs/p3-nl-requirements.md`，P4 范围见 `docs/specs/p4-traceability-report.md`，P5 范围见 `docs/specs/p5-runtime.md`，P6 范围见 `docs/specs/p6-delivery.md`）。
本目录实现：P1 工具层 MVP（认证客户端 + 27 个 READ 工具 + MCP 双 transport + OpenAI 导出）+ P2 受控写路径（7 个 DRAFT + 6 个 MUTATE 工具 + 白名单审批门 + dry-run 预览 + 工具调用级审计日志 + 四级权限元数据 + 服务账号约定）+ P3 复合技能①（`draft_requirement` 自然语言建需求：EARS 五句式 + 本地 quality lint 闭环 + 落库（DRAFT 审批门复用）+ `get_requirement_quality` 需求级品质反馈）+ P4 复合技能②（`get_traceability_gap_report` 追踪/覆盖缺口报告：六源客户端聚合 + 12 类缺口维度 + 规则驱动建议，全 READ 零写）+ P5 内置运行时（planner→executor loop + DSH/OpenAI/Fake provider + 会话内存 + run CLI）+ P6 交付（evals 黄金任务集 + 部署形态 + 文档/版本 0.2.0）。

## 安装

```bash
cd reqmesh-harness
uv sync                      # 开发/运行（uv.lock 锁定；含 pytest/respx/dev 组）
```

- **wheel/sdist 安装**（发布产物）：`pip install dist/reqmesh_harness-0.2.0-py3-none-any.whl`（见 RELEASING.md；dist/ 不入库）。
- **uv tool 安装**：`uv tool install .`（console script `reqmesh-harness` 全局可用；未纳入 CI）。
- **前置**：本地 reqmesh 实例（`REQMESH_BASE_URL`，默认 `http://172.16.100.2:8000`）；演示项目 cessna-172。

> 新会话三步冒烟：`uv sync` → `uv run pytest`（533 passed / 3 skipped / 2 deselected，evals 不在集合）→ `uv run python scripts/smoke_p1.py`（network-tagged；`REQMESH_SMOKE_OUT` 可覆盖记录路径）。

## 认证

凭据仅经环境变量注入：`REQMESH_USERNAME` / `REQMESH_PASSWORD`（或 Bearer 兜底 `REQMESH_TOKEN`）；也可放 `reqmesh-harness/.env`（gitignored，pydantic-settings env_file 自动加载，**不落盘/不进日志**）。
会话（cookie + csrf_token）持久化到 XDG state 目录（`~/.local/state/reqmesh-harness/session.json`，0600），重启免重登。

**服务账号（D7，P2 实测修正）**：harness 以专用账号 `reqmesh-harness`（role=**maintainer**——reqmesh v0.5.0 项目权限层 contributor=propose 仅覆盖风险/评论/决策，requirements 等写面需 edit 层）写入；操作员用 admin 凭据在 reqmesh 一次性创建（人工前置步骤，见 P2 冒烟记录）。未建号时冒烟允许降级 `yugj` 并在记录中显式标注。harness 不自建账号（auth/users 属 ADMIN 层）。

## 审批门与审计（P2）

- 白名单是**唯一裁决源**：`REQMESH_APPROVALS_FILE`（默认 XDG config `~/.config/reqmesh-harness/approvals.toml`，0600）；DRAFT 条目 `project` 可省略（通配），MUTATE/ADMIN 必须指定具体 `project`；`dry_run_only=true` 条目只放行 dry_run。fail-closed：未命中即拒绝（`ApprovalDeniedError` 含修复建议）。
- 每次调用重读白名单（不缓存）；`dry_run=true` 照跑审批门（不是绕过审批的后门）。
- 审计日志：`REQMESH_AUDIT_FILE`（默认 XDG state `~/.local/state/reqmesh-harness/audit.jsonl`，0600，append-only JSONL，`version=1` 字段契约）——全部写工具调用一行（含 denied/dry_run/错误路径）；READ 不记；无 READ 工具读取审计文件。
- ADMIN 层（删除族/CR 执行/publish/用户管理等）**默认不在工具面**：注册表 ADMIN 分区 + `REQMESH_ENABLE_ADMIN=1` 显式开启后才安装（未开启不出现在 tools/list）。

## approvals CLI 与 run CLI（P5）

```bash
uv run reqmesh-harness approvals list                       # 白名单列表
uv run reqmesh-harness approvals add create_requirement --project cessna-172 --yes   # 添加
uv run reqmesh-harness approvals remove create_requirement --yes                     # 删除
uv run reqmesh-harness run "给 cessna-172 建一条需求：…" --project cessna-172 --yes
```

- `run` 参数：`--project`（显式 project context；任务文本命中唯一项目 id 时 fail-fast 提示显式给出）、`--provider dsh|openai|fake`（默认 `REQMESH_PROVIDER=dsh`）、`--resume RUN_ID`（两分支：DSH 会话存活追加 / 失活重建摘要注入）、`--yes`（denied → 自动维护白名单并重试）、`--show-reasoning`、`--max-rounds N`（防御上限，默认 8）。
- 确认中继三通道：预先白名单（approvals CLI）> `--yes` 无头自动 > TTY 逐条 y/N；拒绝路径只记 denied 审计行，批准后重试记 approved 行。
- run 结束打印审计摘要（本地文件，不向 agent 暴露审计内容）。

## MCP 双 transport（ADR-0001）

```bash
uv run python -m reqmesh_harness.server                          # stdio（默认；DSH 注册用）
uv run python -m reqmesh_harness.server --transport http          # streamable-HTTP：默认 127.0.0.1:8081，端点 /mcp
# （--host/--port 覆盖监听地址/端口；REQMESH_HARNESS_HOST/PORT 环境变量同效；优先 CLI）
```

- **stdio**：供 DSH 等 MCP client 进程内消费（零端口零 LAN 面）；DSH 注册见 `scripts/dsh_register.sh` 与 docs/deployment.md。
- **streamable-HTTP**：默认 `127.0.0.1:8081`（P6 收编正式端口；P1 期 8123 仅剩历史语义），stateless（每个请求作用域构建会话，会话文件共享）。
- 工具注册表 = 40 个工具（27 READ + 7 DRAFT + 6 MUTATE）唯一事实源：`tools/list` 与 stdio/OpenAI 导出同源。

## evals（P6 黄金任务集）

```bash
uv run python evals/run_offline.py            # 离线 G1–G5 全绿（零网络；退出码 0 即全绿；--selftest 自证 runner）
uv run python evals/run_live.py               # live G1–G4（network-tagged；前置 = DSH 已注册 mcp__reqmesh__*；
                                              # 记录落盘 docs/smoke/P6-cessna-172.md）
```

- 任务定义 = 数据（`evals/tasks.py`：期望工具序列 + 参数匹配器 + 最终状态断言 + 审计期望）；
  离线（respx + FakeProvider）与 live（DSH 委托路线）共享同一份定义；G5 仅离线（P5 live 已由 smoke_p5 B 段覆盖）。
- evals 不做入 pytest 集合（离线基线计数不变）；发布门 = `evals/run_offline.py` 退出码 0。

## 冒烟（network-tagged 惯例）

```bash
uv run python scripts/smoke_p1.py    # P1 只读链路（login/whoami/list_requirements/coverage/gap/traces）
uv run python scripts/smoke_p2.py    # P2 写路径（审批门/审计/dry-run；真实写，残渣 SMOKE-P2-001）
uv run python scripts/smoke_p3.py    # P3 自然语言建需求（残渣 SMOKE-P3-001）
uv run python scripts/smoke_p4.py    # P4 缺口报告（零副作用）
REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py   # P5 A 段必跑；B 段需 DSH 注册前置
uv run python evals/run_live.py       # P6 evals live（同前置）
```

独立 network-tagged 脚本（不进默认 pytest 集合）；记录经 `REQMESH_SMOKE_OUT` 落盘 `docs/smoke/P*-cessna-172.md`（时间戳/实例/每步结果/残渣清单）。pytest 默认排除 network（`-m "not network"`）。

## 部署（pointer）

- 免 root 启动：`scripts/run_server.sh start|stop|status|logs`（默认 127.0.0.1:8081，pidfile/日志落 XDG state）。
- systemd 主机：`deploy/systemd/reqmesh-harness.service` 模板（sudo 安装属操作员）。
- **完整部署/DSH 注册/LAN 安全口径见 [docs/deployment.md](../docs/deployment.md)**；发布流程见 [RELEASING.md](RELEASING.md)；变更记录见 [CHANGELOG.md](CHANGELOG.md)。

## 目录与管线职责

| 路径 | 职责 |
|---|---|
| `openapi/reqmesh-0.5.0.json` | vendored /openapi.json 快照（契约输入，勿手改；升级时重新抓取） |
| `scripts/gen_models.py` | 确定性模型生成管线：快照 → `client/generated/models.py` |
| `src/reqmesh_harness/client/` | 薄 HTTP 客户端：认证会话（cookie/CSRF）、只读视图（仅 `get()`）、写视图（仅 post/put/patch/delete，构造需 GateToken） |
| `src/reqmesh_harness/client/generated/` | 生成产物（提交入库，**禁止手改**） |
| `src/reqmesh_harness/guardrails/` | 审批门（白名单 fail-closed 裁决 + GateToken 签发）+ JSONL 审计日志 + `approvals` CLI |
| `src/reqmesh_harness/tools/` | 工具注册表（唯一事实源）+ 40 个工具（27 READ + 7 DRAFT + 6 MUTATE；含 P3/P4 复合技能） |
| `src/reqmesh_harness/ears/` | EARS 五句式解析/渲染（P3；纯确定性，无 LLM，英文槽位） |
| `src/reqmesh_harness/lint/` | 本地 quality lint（20 条规则镜像 + 6 类确定性修正表；独立重写，不复制上游 GPL 源码） |
| `src/reqmesh_harness/report/` | 追踪/覆盖缺口报告聚合内核（P4；纯函数零网络，12 类缺口维度 + 建议模板表独立编写） |
| `src/reqmesh_harness/runtime/` | P5 内置运行时：provider 契约（DSH/OpenAI/Fake）+ loop 内核 + 会话内存 + run CLI + 确认中继 |
| `src/reqmesh_harness/server.py` | FastMCP server（stdio + streamable-HTTP 双 transport；默认 127.0.0.1:8081） |
| `evals/` | P6 黄金任务集：`tasks.py`（任务定义数据）+ `run_offline.py`（零网络）+ `run_live.py`（network-tagged） |
| `scripts/smoke_p1.py`–`smoke_p5.py` | cessna-172 冒烟（network-tagged，不进默认 pytest 集合） |
| `scripts/run_server.sh` | 免 root 部署脚本（start|stop|status|logs，P6） |
| `scripts/dsh_register.sh` | DSH stdio 注册幂等脚本（dry-run diff + 备份；应用/重启属操作员） |
| `deploy/systemd/reqmesh-harness.service` | systemd 单元模板（P6；sudo 安装属操作员） |
| `tests/` | 离线单测（respx 打桩 + fixture），见 spec「Testing Decisions」 |

## 常用命令

```bash
uv sync                                                          # 安装依赖（uv.lock 锁定）
uv run python scripts/gen_models.py                              # 重生成模型（重跑后 git diff 应为空）
uv run pytest                                                    # 全部离线单测（533 passed / 3 skipped / 2 deselected）
uv run pytest -m network                                         # 网络冒烟（需 REQMESH_USERNAME/REQMESH_PASSWORD）
uv run python evals/run_offline.py                               # evals 离线 5/5（发布门）
scripts/run_server.sh start              # 免 root 拉起 streamable-HTTP（127.0.0.1:8081）
uv run python -m reqmesh_harness.server --transport http --host 127.0.0.1 --port 8081
```
