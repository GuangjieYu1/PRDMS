# reqmesh-harness 部署文档（操作员长文档）

> 覆盖范围：**只覆盖 reqmesh-harness**（8081 streamable-HTTP MCP server + DSH stdio 注册 + 免 root 脚本 + systemd 模板 + LAN 安全口径）。
> 上游边界：reqmesh 实例（本机 `http://172.16.100.2:8000`，reqmesh v0.5.0）的安装/升级/配置是**前置条件**——引用其部署文档（`reqmesh/DEPLOYMENT.md` 与 `install.sh`，属上游克隆目录，gitignored，本仓库不修改不复制）。
> 术语见 CONTEXT.md；工具与端口事实见 [P6 spec 事实核实](specs/p6-delivery.md)。

## 1. 拓扑与端口

| 端口 | 服务 | 绑定 | 说明 |
|---|---|---|---|
| 8000 | reqmesh（数据层） | 0.0.0.0 | 由 DSH 宿主进程派生（现网）；上游部署面 |
| 8080 | DSH web 宿主 | 0.0.0.0 | `dsh --profile web --no-open --port 8080`；MCP client 侧 |
| 3080 | DSH webserver 插件 | 0.0.0.0 | dsh web profile 配置 |
| **8081** | **reqmesh-harness** | **默认 127.0.0.1** | **P6 收编正式端口**（P1 期 8123 = 开发默认，仅历史语义）；端点 `/mcp` |

8081 与 8080 同属「本机 agentic 工具带」；harness 默认仅本机可达，LAN 暴露须显式操作（§4）。

## 2. 配置（环境变量 / .env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `REQMESH_BASE_URL` | `http://172.16.100.2:8000` | reqmesh 实例 |
| `REQMESH_USERNAME` / `REQMESH_PASSWORD` | — | 服务账号凭据（**只在 shell 环境或 `reqmesh-harness/.env`**，0600；不进脚本/单元文件/文档/日志） |
| `REQMESH_HARNESS_HOST` | `127.0.0.1` | streamable-HTTP 监听地址 |
| `REQMESH_HARNESS_PORT` | `8081` | streamable-HTTP 端口 |
| `REQMESH_APPROVALS_FILE` | XDG config `~/.config/reqmesh-harness/approvals.toml` | 白名单（0600） |
| `REQMESH_AUDIT_FILE` | XDG state `~/.local/state/reqmesh-harness/audit.jsonl` | 审计日志（0600） |
| `REQMESH_PROVIDER` | `dsh` | run CLI provider（dsh/openai/fake） |
| `REQMESH_LINT_MIN_SCORE` / `REQMESH_LINT_MAX_ROUNDS` | `90` / `3` | P3 lint 过线参数 |

CLI 覆盖优先级：`--host/--port` > env（Settings 构造顺序）；`reqmesh-harness/.env` 由 pydantic-settings 自动加载（cwd 生效——启动脚本与 systemd 均以 `reqmesh-harness/` 为 WorkingDirectory/cwd）。

## 3. 免 root 启动（本机默认路径；无用户级 systemd 主机）

```bash
cd /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness
uv sync                                            # 首次
scripts/run_server.sh start                        # nohup 拉起（默认 127.0.0.1:8081）
scripts/run_server.sh status                       # pid 存活 + 端口健康
scripts/run_server.sh logs                         # 日志尾部（LOG_LINES=N 可调；logs --follow）
scripts/run_server.sh stop                         # 终止 + pidfile 清理
```

- pidfile/日志落 XDG state：`~/.local/state/reqmesh-harness/server.pid` / `server.log`。
- 凭据经 shell 环境或 `reqmesh-harness/.env` 注入（脚本不含凭据字面量）；`scripts/run_server.sh` 本身不加载凭据。
- 端口覆盖：`REQMESH_HARNESS_HOST=0.0.0.0 REQMESH_HARNESS_PORT=8081 scripts/run_server.sh start`（LAN 暴露见 §4）。
- 验证 40 工具：

```python
# 任意 MCP client（mcp SDK 安装于 venv）：
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def check():
    async with streamable_http_client("http://127.0.0.1:8081/mcp") as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            assert len(names) == 40, len(names)
            print(f"工具数 {len(names)}（mcp__reqmesh__ 注册面 40：27 READ + 7 DRAFT + 6 MUTATE）")

asyncio.run(check())
```

## 4. LAN 暴露安全口径

- **默认 127.0.0.1 仅本机可达**；`0.0.0.0` 必须显式（`REQMESH_HARNESS_HOST=0.0.0.0` 或 `--host 0.0.0.0`）。无暗含 LAN 面。
- 暴露后的风险与控制：
  1. streamable-HTTP 端点本身无鉴权（MCP 协议无认证层）——READ 工具数据对 LAN 可达客户端可见（与 8000/8080 现网姿态一致，但应知晓）。
  2. 写工具受审批门保护：每次调用重读白名单、fail-closed；`ApprovalDeniedError` + fix_hint 只会返回给客户端；白名单/审计文件是**服务器进程所在主机的本地文件**——LAN 客户端不能绕过裁决、不能伪造白名单。
  3. reqmesh 认证会话（服务账号 cookie）在 harness 进程内——LAN 客户端不接触凭据。
  4. `RT_ALLOWED_HOSTS`（上游 Host-header 校验，code 默认 `["*"]` 关闭）是 **reqmesh 上游部署面**——harness 不代管；需收紧时在 reqmesh 配置（引用上游文档）。
- 建议：LAN 暴露前确认网络信任域；或前置反向代理（如 nginx/Caddy 示例占位：`location /mcp { proxy_pass http://127.0.0.1:8081; }`——不强制）。

## 5. systemd 路径（可装 systemd 的主机）

本机现实：**无用户级 systemd**（`systemctl --user` → No medium found）、uid=1000——免 root 脚本是此机默认路径；单元模板供通用主机。

模板：`reqmesh-harness/deploy/systemd/reqmesh-harness.service`（`User`/`WorkingDirectory`/`ExecStart`/`EnvironmentFile` 四个占位符 + 安装说明；语法校验 `systemd-analyze verify` 已通过）。

```bash
# 安装步骤（sudo 属操作员责任边界——root 操作不得由开发会话/自动化代做）：
sudo cp reqmesh-harness/deploy/systemd/reqmesh-harness.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reqmesh-harness
systemctl status reqmesh-harness
```

- `User`：替换为目标运行用户；`WorkingDirectory`/`ExecStart`：替换为仓库路径与 venv console script。
- 凭据：`EnvironmentFile=-%h/.config/reqmesh-harness/env`（用户环境文件，**0600**；`-` 前缀容忍缺失）——凭据不进单元文件。
- `Restart=on-failure`；日志：`journalctl -u reqmesh-harness -f`。

## 6. DSH 注册（mcp-reqmesh，stdio）——操作员维护窗口

**责任边界（spec 决策③）**：应用与重启 = 操作员（本机用户/方向层），维护窗口执行——重启 8080 宿主会中断方向层自身工作 GUI，只有宿主使用者能择机执行。脚本只产出/预览/受控插入。

```bash
cd reqmesh-harness
scripts/dsh_register.sh --check        # 当前状态（已存在/缺失）
scripts/dsh_register.sh --dry-run      # （默认）条目 + diff 预览，不写文件
scripts/dsh_register.sh --apply        # 备份（.dsh-register-backups/）+ 幂等插入
```

注册条目（与 spec 决策③ 逐字一致；stdio 选型：零端口零 LAN 面、生命周期随 DSH、env 转发凭据）：

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

**验证三步（操作员执行）**：

1. DSH 新会话内可见 `mcp__reqmesh__*` 40 工具（`whoami` 返回 `reqmesh-harness`/maintainer）。
2. `cd reqmesh-harness && REQMESH_P5_SMOKE_B=1 uv run python scripts/smoke_p5.py` → SMOKE-P5-001：落库回读（description == EARS 句、status=proposed）、total 61→62、审计基线差 Δ2 行（denied+approved）、无 approval/requested 帧。
3. `uv run python evals/run_live.py` → G1–G4 全绿（残渣 `SMOKE-EVAL-P6-G1/G3-*` 入残渣清单；记录落盘 `docs/smoke/P6-cessna-172.md`）。

**回滚**：`cp .dsh-register-backups/cordis.patch.yml.<时间戳> /home/user/.dsh/profiles/web/cordis.patch.yml` → 重启宿主 → 验证 40 工具消失。

## 7. 安全边界汇总

- 凭据：只经环境变量/.env（0600）；不进脚本/单元文件/文档/日志/审计。
- 写面：审批门（白名单唯一裁决源）+ 审计（一行一次写尝试）——LAN 客户端只能拿到 denied + fix_hint。
- 上游：`RT_ALLOWED_HOSTS`/reqmesh 实例配置 = 上游部署面，不代管；`reqmesh/DEPLOYMENT.md` 为前置。
- DSH 宿主：注册配置变更 = 操作员维护窗口受控变更（备份 + 幂等脚本 + 验证三步）。
