# reqmesh-harness

reqmesh 需求管理工具的 Agentic 编排运行时（见 `docs/reqmesh-harness-design.md`；P1 范围见 `docs/specs/p1-tool-layer-mvp.md`，P2 范围见 `docs/specs/p2-write-path.md`）。
本目录实现：P1 工具层 MVP（认证客户端 + 25 个 READ 工具 + MCP 双 transport + OpenAI 导出）+ P2 受控写路径（12 个 DRAFT/MUTATE 工具 + 白名单审批门 + dry-run 预览 + 工具调用级审计日志 + 四级权限元数据 + 服务账号约定）。

## 目录与管线职责

| 路径 | 职责 |
|---|---|
| `openapi/reqmesh-0.5.0.json` | vendored /openapi.json 快照（契约输入，勿手改；升级时重新抓取） |
| `scripts/gen_models.py` | 确定性模型生成管线：快照 → `client/generated/models.py` |
| `src/reqmesh_harness/client/` | 薄 HTTP 客户端：认证会话（cookie/CSRF）、只读视图（仅 `get()`）、写视图（仅 post/put/patch/delete，构造需 GateToken） |
| `src/reqmesh_harness/client/generated/` | 生成产物（提交入库，**禁止手改**） |
| `src/reqmesh_harness/guardrails/` | 审批门（白名单 fail-closed 裁决 + GateToken 签发）+ JSONL 审计日志 + `approvals` CLI |
| `src/reqmesh_harness/tools/` | 工具注册表（唯一事实源）+ 25 个 READ 工具 + 12 个写工具（6 DRAFT + 6 MUTATE） |
| `src/reqmesh_harness/server.py` | FastMCP server（stdio + streamable-HTTP） |
| `scripts/smoke_p1.py` / `scripts/smoke_p2.py` | cessna-172 冒烟（network-tagged，不进默认 pytest 集合） |
| `tests/` | 离线单测（respx 打桩 + fixture），见 spec「Testing Decisions」 |

## 常用命令

```bash
uv sync                       # 安装依赖（uv.lock 锁定）
uv run python scripts/gen_models.py   # 重生成模型（重跑后 git diff 应为空）
uv run pytest                 # 全部离线单测
uv run pytest -m network      # 网络冒烟（需 REQMESH_USERNAME/REQMESH_PASSWORD）
uv run python -m reqmesh_harness.server                       # stdio transport
uv run python -m reqmesh_harness.server --transport http      # streamable-HTTP transport
# （可加 --host/--port 覆盖监听地址/端口；默认见 REQMESH_HARNESS_HOST/PORT）
uv run reqmesh-harness approvals list                    # 审批白名单维护（P2）
uv run reqmesh-harness approvals add create_requirement --project cessna-172 --yes
uv run reqmesh-harness approvals remove create_requirement --yes
```

## 认证

凭据仅经环境变量注入：`REQMESH_USERNAME` / `REQMESH_PASSWORD`（或 Bearer 兜底 `REQMESH_TOKEN`）。
会话（cookie + csrf_token）持久化到 XDG state 目录（`~/.local/state/reqmesh-harness/session.json`，0600），重启免重登。

**P2 服务账号（D7）**：harness 以专用账号 `reqmesh-harness`（role=contributor）写入；操作员用 admin 凭据在 reqmesh 一次性创建（人工前置步骤，见 P2 冒烟记录）。未建号时冒烟允许降级 `yugj` 并在记录中显式标注。harness 不自建账号（auth/users 属 ADMIN 层）。

## 审批门与审计（P2）

- 白名单是**唯一裁决源**：`REQMESH_APPROVALS_FILE`（默认 XDG config `~/.config/reqmesh-harness/approvals.toml`，0600）；DRAFT 条目 `project` 可省略（通配），MUTATE/ADMIN 必须指定具体 `project`；`dry_run_only=true` 条目只放行 dry_run。fail-closed：未命中即拒绝（`ApprovalDeniedError` 含修复建议）。
- 每次调用重读白名单（不缓存）；`dry_run=true` 照跑审批门（不是绕过审批的后门）。
- 审计日志：`REQMESH_AUDIT_FILE`（默认 XDG state `~/.local/state/reqmesh-harness/audit.jsonl`，0600，append-only JSONL，`version=1` 字段契约）——全部写工具调用一行（含 denied/dry_run/错误路径）；READ 不记；无 READ 工具读取审计文件。
- ADMIN 层（删除族/CR 执行/publish/用户管理等）**默认不在 P2 工具面**：注册表 ADMIN 分区 + `REQMESH_ENABLE_ADMIN=1` 显式开启后才安装（未开启不出现在 tools/list）。
