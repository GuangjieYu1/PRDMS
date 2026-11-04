# 内网主机部署：10.1.19.225（MCP 对外提供，供灵码 / DSH 接入）

> 适用：把 PRDMS + ReqMesh 部署到**内网服务器** `10.1.19.225`，让内网其它机器上的
> 通义灵码 / Qoder CN 或 DSH 通过 MCP 使用。
>
> **本文件只讲"在这台机器上怎么把它变成内网可用的 MCP 服务"**。装依赖、构建前端、
> 生成密钥这些通用步骤见 `docs/deployment-host.md`，不重复。

---

## 0. 与"装在本机自用"的区别

| 项 | 本机自用（deployment-host.md） | **内网服务器（本文件）** |
|---|---|---|
| harness 怎么跑 | DSH 用 **stdio** 起子进程 | **HTTP 常驻服务**，监听 `0.0.0.0:8082` |
| 谁能用 | 只有本机 | 内网所有授权机器 |
| 鉴权 | 不需要（进不了网络） | **必须**配两个 token（否则 28 个只读工具裸奔） |
| 暴露 | 无 | 内网 HTTP（无 TLS） |
| 客户端 | DSH | 灵码走 **SSE**，DSH 走 **streamable-HTTP** |

**为什么必须配鉴权**：MCP 协议本身没有认证层，而 harness 的 28 个 READ 工具**不受
审批门保护**——审批门只管写工具。端点一旦监听 `0.0.0.0`，同网段任何人都能读全部项目数据。

---

## 1. 交付物

| 文件 | 来源 | 说明 |
|---|---|---|
| `prdms-src-<时间戳>.tar.gz` | 在交付方机器上跑 `./scripts/pack-full.sh` | 约 8 MB，含 PRDMS + reqmesh 上游源码（私有仓库，公网拿不到） |
| 该包的 sha256 | 打包脚本输出 | 逐字比对，不一致就不要用 |

**包里刻意不含**：`.venv` / `node_modules` / `frontend/dist`（与 CPU 架构绑定）、
`data/` / `.env` / 密钥（由目标机自己生成）。

---

## 2. 步骤

### 2.1 解包并校验

```bash
sha256sum prdms-src-*.tar.gz          # 与交付方给的 sha256 逐字比对
mkdir -p /opt/prdms && tar -xzf prdms-src-*.tar.gz -C /opt/prdms
cd /opt/prdms/PRDMS
```

### 2.2 预检

```bash
# 必需：python3(>=3.11) / node(>=18) / uv / openssl / curl / git
python3 -V && node -v && uv --version && openssl version && curl --version | head -1
```

`node` 只在**构建前端**时需要；若前端已由交付方构建好并随包带入，可跳过。
（本方案默认在目标机构建，见 `deployment-host.md` §1。）

### 2.3 一键引导（装依赖 + 构建前端 + 生成密钥/种子 + 配服务账号）

```bash
./scripts/bootstrap-host.sh
```

成功后应有：`reqmesh/backend/.venv`、`reqmesh/frontend/dist`、`reqmesh/.rt-secret`、
`reqmesh/.rt-admin-pw`、`reqmesh-harness/.env`，且工具数为 **41**。

> ⚠️ `bootstrap-host.sh` **不会**生成 MCP token、也**不会**把 harness 变成 HTTP 服务
> —— 那是下一步的事。

### 2.4 启动 reqmesh 后端

```bash
./scripts/bootstrap-host.sh --start       # 或按 deployment-host.md §3 手工起
curl -sf http://127.0.0.1:8000/health && echo " reqmesh OK"
```

### 2.5 把 harness 变成 HTTP/SSE 服务（本方案的关键一步）

```bash
./scripts/enable-http-mcp.sh
```

它做四件事，都是幂等的：

1. 生成 **两个 token** 写进 `reqmesh-harness/.env`（0600）：
   - `REQMESH_MCP_TOKEN` —— Bearer 头，给 DSH
   - `REQMESH_MCP_PATH_TOKEN` —— 路径 token，给灵码
2. 设 `REQMESH_HARNESS_HOST=0.0.0.0` / `PORT=8082` / `REQMESH_MCP_ALLOWED_HOSTS=<本机IP,主机名>`
3. 装 systemd 单元 `reqmesh-harness.service` 并启动
4. 跑五项验收（见下）

**如果 8082 已被占用**，加参数换端口：

```bash
ss -lntp | grep 8082 || echo "8082 空闲"
./scripts/enable-http-mcp.sh --port 8092
```

**如果只想绑本机、前面放反代**：

```bash
./scripts/enable-http-mcp.sh --host 127.0.0.1 --allowed-hosts reqmesh.internal
```

### 2.6 开放端口

```bash
# firewalld
sudo firewall-cmd --permanent --add-port=8082/tcp && sudo firewall-cmd --reload
# ufw
sudo ufw allow 8082/tcp
```

> reqmesh 后端（8000）**不要**对外开放，只让 harness 走 127.0.0.1 访问即可。
> 若也需要浏览器看模型，单独为 80/443 配反代，别直接开 8000。

---

## 3. 验收（五项，缺一不可）

`enable-http-mcp.sh` 会自动跑；手工复核：

```bash
B=http://127.0.0.1:8082
TOKEN=$(grep '^REQMESH_MCP_TOKEN=' reqmesh-harness/.env | cut -d= -f2-)
PT=$(grep '^REQMESH_MCP_PATH_TOKEN=' reqmesh-harness/.env | cut -d= -f2-)

# 1) 无凭据必须 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/mcp -H 'content-type: application/json' -d '{}'

# 2) Bearer 头 → 200
curl -s -o /dev/null -w "%{http_code}\n" -X POST $B/mcp \
  -H 'content-type: application/json' -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"v","version":"1"}}}'

# 3) 工具数 = 41
curl -s -X POST $B/mcp -H 'content-type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H "Authorization: Bearer $TOKEN" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | grep -o '"inputSchema"' | wc -l

# 4) SSE 返回 endpoint 事件（灵码靠这个）
curl -s --max-time 4 -H 'Accept: text/event-stream' "$B/mcp/$PT/sse" | head -2

# 5) 错误路径 token → 401
curl -s -o /dev/null -w "%{http_code}\n" -H 'Accept: text/event-stream' "$B/mcp/wrong/sse"
```

期望：`401` / `200` / `41` / 出现 `event: endpoint` / `401`。

**跨机验证**（在另一台内网机器上）：

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://10.1.19.225:8082/mcp \
  -H 'content-type: application/json' -d '{}'      # 期望 401，不是超时
```

---

## 4. 客户端接入

### 4.1 灵码 / Qoder CN（SSE，只能填一个地址）

入口：**个人设置 → MCP 服务 → 添加 → SSE**

| 字段 | 填什么 |
|---|---|
| 名称 | `reqmesh` |
| 类型 | `SSE` |
| 服务地址 | `http://10.1.19.225:8082/mcp/<REQMESH_MCP_PATH_TOKEN>/sse` |

注意：

- 灵码的 SSE 配置**没有自定义请求头**字段（官方文档：仅支持 STDIO 与 SSE），所以
  凭据只能走 URL 路径——这就是 `REQMESH_MCP_PATH_TOKEN` 的用途。
- 需要切到**智能体模式**、并加载了工程目录，否则只走智能问答、不调用 MCP 工具。
- 路径 token 会进灵码的历史与日志，与 Bearer token **分开轮换**。

### 4.2 DSH（streamable-HTTP + 请求头）

`~/.dsh/profiles/desktop/cordis.patch.yml`：

```yaml
- insert:
    - id: mcp-reqmesh
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: reqmesh
        transport: streamable-http
        url: http://10.1.19.225:8082/mcp
        headers:
          Authorization: "Bearer <REQMESH_MCP_TOKEN>"
```

> **为什么 token 明文写在这里**：DSH Desktop 从 Dock/Finder 启动时父进程是 `launchd`，
> 环境为 `PATH=/usr/bin:/bin:/usr/sbin:/sbin`——**不继承 `~/.zshrc`**（实测）。
> 用 `process.env.REQMESH_MCP_TOKEN` 会解析成 `Bearer undefined` → 401。
> 明文写入 + `chmod 600` 是唯一可靠做法。

---

## 5. 写权限（默认全关）

`enable-http-mcp.sh` 建的 `.state/approvals.toml` 是**空文件** → 所有写工具都被拒，
这是安全默认。要开某个项目：

```bash
cat >> /opt/prdms/PRDMS/.state/approvals.toml <<'TOML'
[[approvals]]
tool = "create_requirement"
project = "bfip-reqmesh"
dry_run_only = false
TOML
```

**必须写 `project`**，否则是对全部项目的通配授权。审批门每次调用重读本文件，
改完**无需重启**。

---

## 6. 与阿里云那套的差异

| 项 | 阿里云（已部署） | **内网 225** |
|---|---|---|
| 暴露方式 | Cloudflare Tunnel（公网 HTTPS） | **内网直连 HTTP** |
| TLS | Cloudflare 终结 | **无**（内网信任域） |
| 端口 | 隧道 → 127.0.0.1:8082 | **0.0.0.0:8082** |
| 来源限制 | 隧道 + token | **仅 token + 防火墙** |
| 数据层 | 裸 venv + systemd（8001） | 同（bootstrap 默认 8000） |
| 前端 | 预构建产物搬运 | 目标机构建 |

**内网无 TLS 的含义**：token 在网络上明文传输。这在"受控内网 + 单 token"前提下可
接受，但要知道：**同网段抓包即可拿到 token**。若内网不可信，前面加 nginx + TLS。

---

## 7. 排障

| 现象 | 原因 | 处置 |
|---|---|---|
| `bootstrap-host.sh` 报 `reqmesh/backend 不存在` | 用的是 GitHub 仓库而不是**源码包** | 源码包才有 `reqmesh/`；重新取包 |
| 工具数不是 41 | harness 版本旧 / 包不完整 | 确认包里含 `tools/groups/checks.py` 与 `mcp_auth.py` |
| 跨机访问超时 | 防火墙未开 8082 | `firewall-cmd`/`ufw` 放行 |
| 跨机 421 `Invalid Host header` | `REQMESH_MCP_ALLOWED_HOSTS` 没含客户端用的 Host | 把客户端访问用的 IP/域名加进去，重启服务 |
| 401 | token 不对 / `.env` 未生效 | 核对两端取值；`systemctl restart reqmesh-harness` |
| 灵码连上但工具列表空 | 未切智能体模式 / 未加载工程目录 | 切换模式并打开工作目录 |
| 灵码 SSE 报 404 | 路径 token 错，或 `messages` 前缀重复（历史 bug） | 核对 URL；本仓库 `fab1cd2` 起已修 |
| 写工具报 `dry_run_only` | 白名单里没有该项目条目（**文案有误导**，`67091bb` 起已修） | 检查 `approvals.toml` 的 `project` |
| 工具调用报上游 401 | reqmesh 未启动 / 服务账号密码不匹配 | 看 `/tmp/reqmesh-host.log`；用 admin 在 UI 建 `reqmesh-harness` 账号（maintainer） |

---

## 8. 升级

```bash
# 交付方：改完提交，再打新包
./scripts/pack-full.sh -o /tmp/out

# 目标机：备份状态 → 解包覆盖源码 → 重跑
cp -a /opt/prdms/PRDMS/.state /tmp/state.bak
tar -xzf prdms-src-<新时间戳>.tar.gz -C /opt/prdms
cd /opt/prdms/PRDMS && ./scripts/bootstrap-host.sh && ./scripts/enable-http-mcp.sh
```

`.state/`（白名单与审计）与 `reqmesh-harness/.env`（token）**不在包里**，覆盖源码
不会丢失——但仍建议先备份。
