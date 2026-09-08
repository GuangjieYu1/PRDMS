# PRDMS 主机部署指南（脱离虚拟机版）

> 适用：把 PRDMS 部署到**你自己的本机**（虚拟机之外）。
> 前置阅读：`docs/manual/MANUAL.md`（功能与手动测试）、`docs/deployment.md`（harness 部署细节，systemd/8081）。
> 包来源：共享文件夹 `mnt/linux_share/prdms-full-*.tar.gz`，或 GitHub `GuangjieYu1/PRDMS`（tag `v0.2.0`）。

## 1. 前置要求（按主机系统）

| 系统 | 结论 | 说明 |
|---|---|---|
| **Windows** | 请用 **WSL2**（Ubuntu 发行版） | 本栈含 weasyprint/pango、POSIX 脚本；VM 包内 `.venv`/`node_modules` 是 aarch64 Linux 二进制，Windows 原生一律不可用。WSL2 内等同 Linux 路线 |
| **macOS** | 原生支持（Apple Silicon 与 Intel 均可） | 用 Homebrew 装 python@3.11、node、pkg-config、pango、cairo（weasyprint 依赖）；其余同 Linux |
| **Linux** | 原生支持 | 发行版需 python3.11+、node 18+、libpango/libcairo 开发包（Debian/Ubuntu：`apt install python3.11-venv libpango-1.0-0 libpangocairo-1.0-0 libcairo2`） |

通用工具：`git`、`curl`、`openssl`、`uv`（`pip install --user uv` 或官网安装脚本）。

## 2. 快速开始（一键引导）

```bash
# 1) 取包（共享文件夹路径，宿主侧自行拷贝；或在 WSL2 内直接访问 /mnt/*）
tar xzf prdms-full-2026-09-03.tar.gz
cd PRDMS

# 2) 一键引导：装依赖 + 构建前端 + 生成密钥/种子 + 配置 harness + 校验 40 工具
./scripts/bootstrap-host.sh

# 3) 引导并立即启动 reqmesh
./scripts/bootstrap-host.sh --start        # http://127.0.0.1:8000
```

引导脚本幂等可重跑；`--skip-ui-build` 复用已有 `dist/`；`--port` 换端口（默认 8000）。

## 3. 分步详解（等价手工步骤）

1. **reqmesh 后端**：`cd reqmesh/backend && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt`
2. **reqmesh 前端**：`cd reqmesh/frontend && npm ci && npm run build`（产物 `dist/`）
3. **密钥/种子**：`reqmesh/.rt-secret`、`.rt-admin-pw`（openssl rand，0600）；`reqmesh/backend/.venv/bin/python reqmesh/seed_cessna.py --data-root reqmesh/data/projects`（首次）
4. **reqmesh-harness**：`cd reqmesh-harness && uv sync`（生成 `.venv`）
5. **服务账号 `.env`**：`reqmesh-harness/.env` 含 `REQMESH_BASE_URL`（本机地址！）、`REQMESH_USERNAME`、`REQMESH_PASSWORD`（0600）
6. **启动 reqmesh**：
   ```bash
   cd reqmesh/backend && RT_PROFILE=personal \
     RT_STATIC_DIR=$(realpath ../frontend/dist) \
     RT_DATA_ROOT=$(realpath ../data/projects) \
     RT_SECRET=$(cat ../.rt-secret) RT_ADMIN_PASSWORD=$(cat ../.rt-admin-pw) \
     RT_BASE_URL=http://127.0.0.1:8000 \
     .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

## 4. 验证清单（按序执行，全绿即部署成功）

| # | 检查 | 命令 | 预期 |
|---|---|---|---|
| 4.1 | 健康 | `curl http://127.0.0.1:8000/health` | `{"status":"ok","version":"0.5.0","profile":"personal"}` |
| 4.2 | UI | 浏览器打开 `http://127.0.0.1:8000` | 项目列表（Cessna 172S）；admin 密码在 `reqmesh/.rt-admin-pw`，首次登录会要求改密 |
| 4.3 | 服务账号 | UI → Users 创建 `reqmesh-harness`（角色 **maintainer**），密码取 `reqmesh-harness/.env` | 写工具的最小权限角色（P2 实测：contributor 不够，必须 maintainer） |
| 4.4 | harness 工具 | 见 §4.4 命令 | 40 个工具 |
| 4.5 | 测试基线 | `cd reqmesh-harness && uv run pytest -q` | 533 passed, 3 skipped, 2 deselected |
| 4.6 | 网络冒烟 | `uv run python scripts/smoke_p1.py` | 通过（requirements total=57 起，视数据而定） |
| 4.7 | 写路径 | `uv run reqmesh-harness approvals add create_requirement --project cessna-172 --yes` 后经 MCP 调一次 dry_run | 返回 `{dry_run:true, would_send:...}` 且不落库 |

**4.4 harness 工具数（零依赖）**：
```bash
cd reqmesh-harness
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"manual","version":"1"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | .venv/bin/reqmesh-harness --transport stdio | tail -1
# → 40 个工具（create_comment 起，含 draft_requirement/get_traceability_gap_report）
```

## 5. DSH 集成（可选：把 harness 变成本机 DSH 的「需求创造模式」）

```bash
# 1) 装 DSH（本机）
npm install -g @deepseek-ai/dsh

# 2) 起 web profile（带 harness 服务账号凭据，供 mcp-client 转发）
REQMESH_USERNAME=reqmesh-harness \
REQMESH_PASSWORD=$(grep REQMESH_PASSWORD reqmesh-harness/.env | cut -d= -f2) \
dsh --profile web --no-open --port 8080

# 3) 注册 MCP server（脚本自定位：路径随本机位置自动推导，无需改任何硬编码）
cd reqmesh-harness && ./scripts/dsh_register.sh --check   # 缺失
./scripts/dsh_register.sh --apply                          # 幂等插入 + 备份

# 4) 重启 8080 宿主 → 新对话里 mcp__reqmesh__* 40 工具可用（stdin 子进程由宿主托管）
```

验证：新对话问「列出你的 mcp__reqmesh__* 工具」，或按 `docs/manual/MANUAL.md` §4.4 的
转换 agent 开场文本直接投入需求文档。

## 6. 与 VM 版的关键差异（务必阅读）

1. **不要复用 VM 的 `.venv` / `node_modules`**：包内这些目录是 aarch64 Linux 二进制，
   在本机（尤其 Windows/macOS）会直接失败——一律重跑引导脚本重建。
2. **密钥建议重生成**：`.rt-secret`/`.rt-admin-pw` 与 `reqmesh-harness/.env` 随包分发过，
   敏感环境请删除后重跑引导（脚本发现缺失会自动生成）。
3. **路径全部参数化**：`dsh_register.sh` 已改为自定位（本提交起）；`run_server.sh`、
   smoke 脚本均为相对路径；唯一需要改的是各 URL 配置（`REQMESH_BASE_URL`、`RT_BASE_URL`）。
4. **端口冲突**：8000/8080/8081 被占用时用 `--port` / 环境变量换端口，并同步
   `RT_BASE_URL` 与 `REQMESH_BASE_URL`。
5. **systemd/守护化**：`reqmesh-harness/deploy/systemd/reqmesh-harness.service` 是模板，
   路径按本机改；`scripts/run_server.sh` 是免 root 的轻量替代。
6. **DSH 注册脚本旧条目**：若此前已按 VM 绝对路径注册过（`/home/user/...`），
   本机重跑 `--apply` 会因 MARKER 存在而跳过——请先删除 patch 中的 `- id: mcp-reqmesh`
   整段（含 `insert:` 块）再 `--apply`，或直接手改 command/cwd 为本机路径。

## 7. 故障排查

| 症状 | 处理 |
|---|---|
| pip 装 weasyprint 相关失败 | 缺 pango/cairo 系统库（§1 表格）；Linux 装 lib 包、macOS brew 装后重试 |
| `npm run build` OOM 或卡死 | Node 版本 <18 或内存不足；升级 Node、加 `NODE_OPTIONS=--max-old-space-size=4096` |
| 引导后 health 404/Not Found | 启动命令漏了 `RT_STATIC_DIR`；按 §3.6 完整命令重启 |
| harness 写工具 401 | `REQMESH_BASE_URL` 指向不对、或服务账号未建/角色不是 maintainer（§4.3） |
| DSH 新对话没有 mcp 工具 | 宿主启动早于 patch 应用（重启即可）；或宿主进程环境没有 `REQMESH_*`（§5 第 2 步） |
| 端口被占 | `ss -ltnp | grep -E ':(8000|8080|8081)'` 找占用者；换端口并同步两个 BASE_URL |
