#!/usr/bin/env bash
# 把 bootstrap-host.sh 装好的 harness 变成**常驻 HTTP/SSE 服务**（供内网客户端接入）。
#
# 与 bootstrap-host.sh 的分工
#   bootstrap-host.sh   建 venv、构建前端、生成密钥、配服务账号 .env、可选启动 reqmesh
#   本脚本               在其基础上补：MCP 两个 token、HTTP 监听、Host 白名单、
#                       systemd 单元、启动与验收
#
# 为什么需要
#   bootstrap-host.sh 的默认路线是让**本机 DSH 用 stdio 起子进程**——只有本机能用。
#   内网其他机器（灵码 / DSH）要走 **HTTP**，而 MCP 协议自身无认证层、harness 的
#   READ 工具又不受审批门保护，所以必须同时配好鉴权再对外开放。两者本脚本一并处理。
#
# 两种凭据，对应两类客户端
#   REQMESH_MCP_TOKEN       Bearer 头。给支持自定义请求头的客户端（DSH streamable-HTTP）。
#   REQMESH_MCP_PATH_TOKEN  路径 token。给只能填"服务地址"的客户端——实测通义灵码 /
#                           Qoder CN 的 SSE 配置只有"名称 + 服务地址"，无 header 字段。
#
# 用法
#   ./scripts/enable-http-mcp.sh                       # 默认 0.0.0.0:8082，自动探测 Host 白名单
#   ./scripts/enable-http-mcp.sh --host 127.0.0.1      # 只绑本机（配合反代时用）
#   ./scripts/enable-http-mcp.sh --allowed-hosts a,b   # 显式指定允许的 Host
#   ./scripts/enable-http-mcp.sh --no-systemd          # 不装服务，只打印启动命令
#
# 幂等：重复执行不会重复追加配置、不会重新生成 token（已存在则沿用）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS_DIR="$ROOT/reqmesh-harness"
ENV_FILE="$HARNESS_DIR/.env"

BIND_HOST="0.0.0.0"
BIND_PORT="8082"
ALLOWED_HOSTS=""
USE_SYSTEMD=1
EXPECTED_TOOLS=41

while [ $# -gt 0 ]; do
  case "$1" in
    --host) BIND_HOST="$2"; shift 2 ;;
    --port) BIND_PORT="$2"; shift 2 ;;
    --allowed-hosts) ALLOWED_HOSTS="$2"; shift 2 ;;
    --no-systemd) USE_SYSTEMD=0; shift ;;
    -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. 前置检查 ─────────────────────────────────────────────────────────────
step "0/6 前置检查"
[ -x "$HARNESS_DIR/.venv/bin/reqmesh-harness" ] || \
  die "reqmesh-harness 尚未安装。请先运行 ./scripts/bootstrap-host.sh"
ok "harness 已安装"
[ -f "$ENV_FILE" ] || die "缺少 $ENV_FILE。请先运行 ./scripts/bootstrap-host.sh"
ok "服务账号配置存在"
command -v openssl >/dev/null || die "缺少 openssl"
command -v curl    >/dev/null || die "缺少 curl"

# reqmesh 是否在跑（harness 只是它的前端；reqmesh 不在，工具调用全失败）
REQMESH_URL="$(grep -E '^REQMESH_BASE_URL=' "$ENV_FILE" | cut -d= -f2- || true)"
REQMESH_URL="${REQMESH_URL:-http://127.0.0.1:8000}"
if curl -sf --max-time 3 "${REQMESH_URL}/health" >/dev/null 2>&1; then
  ok "reqmesh 可达（${REQMESH_URL}）"
else
  warn "reqmesh 不可达（${REQMESH_URL}）——服务能起，但工具调用会失败。先启动 reqmesh。"
fi

# ── 1. 自动推导 Host 白名单 ──────────────────────────────────────────────────
step "1/6 Host 白名单"
if [ -z "$ALLOWED_HOSTS" ]; then
  # SDK 的 DNS 重绑定保护默认只放行 localhost；绑到 0.0.0.0 后客户端带的是本机 IP 或
  # 主机名，必须显式放行，否则一律 421 "Invalid Host header"（实测）。
  DETECTED="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.' | head -1 || true)"
  if [ -z "$DETECTED" ]; then
    DETECTED="$(ip -4 addr show 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' \
                  | grep -v '^127\.' | head -1 || true)"
  fi
  [ -n "$DETECTED" ] || die "无法自动探测本机 IP，请用 --allowed-hosts 显式指定"
  ALLOWED_HOSTS="$DETECTED,$(hostname 2>/dev/null || echo localhost)"
  ok "自动探测：$ALLOWED_HOSTS"
else
  ok "使用指定值：$ALLOWED_HOSTS"
fi

# ── 2. 写入 .env（幂等，已存在则沿用）───────────────────────────────────────
step "2/6 写入 harness 配置（0600）"
touch "$ENV_FILE" && chmod 600 "$ENV_FILE"

append_if_missing() {  # $1=key  $2=value
  if grep -qE "^$1=" "$ENV_FILE"; then
    ok "$1 已存在，沿用"
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV_FILE"
    ok "$1 已生成"
  fi
}

append_if_missing REQMESH_MCP_TOKEN        "$(openssl rand -hex 32)"
append_if_missing REQMESH_MCP_PATH_TOKEN   "$(openssl rand -hex 24)"
append_if_missing REQMESH_HARNESS_HOST     "$BIND_HOST"
append_if_missing REQMESH_HARNESS_PORT     "$BIND_PORT"
append_if_missing REQMESH_MCP_ALLOWED_HOSTS "$ALLOWED_HOSTS"
# 状态文件放在仓库外的 .state/：不污染源码目录，也不随 git 分发
STATE_DIR="$ROOT/.state"
mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR"
append_if_missing REQMESH_APPROVALS_FILE   "$STATE_DIR/approvals.toml"
append_if_missing REQMESH_AUDIT_FILE       "$STATE_DIR/audit.jsonl"
chmod 600 "$ENV_FILE"

# 审批白名单：不存在则建空文件（空 = 全部写工具被拒，只读态；这是安全默认）
if [ ! -f "$STATE_DIR/approvals.toml" ]; then
  : > "$STATE_DIR/approvals.toml"
  chmod 600 "$STATE_DIR/approvals.toml"
  ok "创建空白名单（只读态：所有写工具都会被拒）"
fi

# ── 3. systemd 单元 ─────────────────────────────────────────────────────────
step "3/6 服务托管"
if [ "$USE_SYSTEMD" = 1 ] && command -v systemctl >/dev/null 2>&1 && [ -d /etc/systemd/system ]; then
  UNIT_DIR="/etc/systemd/system"
  cat > "$UNIT_DIR/reqmesh-harness.service" <<UNIT
[Unit]
Description=reqmesh-harness MCP server (HTTP ${BIND_HOST}:${BIND_PORT}, token auth)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${HARNESS_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${HARNESS_DIR}/.venv/bin/reqmesh-harness --transport http --host ${BIND_HOST} --port ${BIND_PORT}
Restart=on-failure
RestartSec=3s

[Install]
WantedBy=multi-user.target
UNIT
  ok "已写 $UNIT_DIR/reqmesh-harness.service"
  if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" != "0" ]; then
    warn "需要 root 生效，请手动执行："
    echo "       sudo systemctl daemon-reload"
    echo "       sudo systemctl enable --now reqmesh-harness"
  else
    systemctl daemon-reload
    systemctl enable --now reqmesh-harness
    ok "已启动 reqmesh-harness"
  fi
else
  warn "未使用 systemd。请自行托管，启动命令："
  echo "       cd $HARNESS_DIR && set -a && . ./.env && set +a && \\"
  echo "         .venv/bin/reqmesh-harness --transport http --host $BIND_HOST --port $BIND_PORT"
fi

# ── 4. 等待就绪 ─────────────────────────────────────────────────────────────
step "4/6 等待服务就绪"
TOKEN="$(grep -E '^REQMESH_MCP_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
PATH_TOKEN="$(grep -E '^REQMESH_MCP_PATH_TOKEN=' "$ENV_FILE" | cut -d= -f2-)"
BASE="http://127.0.0.1:${BIND_PORT}"
for i in $(seq 1 20); do
  if curl -s -o /dev/null --max-time 2 -X POST "$BASE/mcp" \
       -H 'content-type: application/json' -d '{}' 2>/dev/null; then
    ok "服务已监听 ${BASE}"
    break
  fi
  [ "$i" = 20 ] && die "服务未在 ${BASE} 就绪。查看日志：journalctl -u reqmesh-harness -n 50"
  sleep 1
done

# ── 5. 验收（四项，缺一不可）────────────────────────────────────────────────
step "5/6 验收"
fail=0

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$BASE/mcp" \
        -H 'content-type: application/json' -d '{}' || true)"
[ "$code" = "401" ] && ok "无凭据 → 401（鉴权生效）" || { warn "无凭据 → $code（期望 401）"; fail=1; }

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$BASE/mcp" \
        -H 'content-type: application/json' -H "Authorization: Bearer $TOKEN" \
        -H 'Accept: application/json, text/event-stream' \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}' || true)"
[ "$code" = "200" ] && ok "Bearer 头 → 200（streamable-HTTP 可用）" || { warn "Bearer 头 → $code（期望 200）"; fail=1; }

COUNT="$(curl -s --max-time 8 -X POST "$BASE/mcp" \
          -H 'content-type: application/json' -H 'Accept: application/json, text/event-stream' \
          -H "Authorization: Bearer $TOKEN" \
          -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
          | grep -o '"inputSchema"' | wc -l | tr -d ' ' || echo 0)"
[ "$COUNT" = "$EXPECTED_TOOLS" ] && ok "工具数 ${COUNT}" || { warn "工具数 ${COUNT}（期望 ${EXPECTED_TOOLS}）"; fail=1; }

# SSE 是流，curl 会因 --max-time 退出码非 0，但只要拿到 event: endpoint 就说明通了
SSE_OUT="$(curl -s --max-time 4 -H 'Accept: text/event-stream' \
            "$BASE/mcp/${PATH_TOKEN}/sse" 2>/dev/null || true)"
echo "$SSE_OUT" | grep -q '^event: endpoint' \
  && ok "SSE 路径 token → 已返回 endpoint 事件" \
  || { warn "SSE 未返回 endpoint 事件（灵码将无法接入）"; fail=1; }

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -H 'Accept: text/event-stream' \
        "$BASE/mcp/wrong-token/sse" || true)"
[ "$code" = "401" ] && ok "错误路径 token → 401" || { warn "错误路径 token → $code（期望 401）"; fail=1; }

# ── 6. 交付信息 ─────────────────────────────────────────────────────────────
step "6/6 客户端接入信息"
LAN_IP="$(printf '%s' "$ALLOWED_HOSTS" | cut -d, -f1)"
cat <<INFO

  给灵码 / Qoder CN（SSE，只能填一个地址）：
    http://${LAN_IP}:${BIND_PORT}/mcp/${PATH_TOKEN}/sse

  给 DSH / 支持自定义头的客户端（streamable-HTTP + Bearer）：
    http://${LAN_IP}:${BIND_PORT}/mcp
    Authorization: Bearer ${TOKEN}

  两个 token 都在：${ENV_FILE}（0600）
  ⚠️ 路径 token 会进访问日志，与 Bearer token 分开轮换。

  写权限默认全关（approvals.toml 为空）。要开某个项目：
    cat >> ${STATE_DIR}/approvals.toml <<'TOML'
    [[approvals]]
    tool = "create_requirement"
    project = "<项目id>"
    dry_run_only = false
    TOML
  审批门每次调用重读本文件，改完无需重启。

INFO

[ "$fail" = 0 ] && { printf '\033[1;32m验收全部通过。\033[0m\n'; exit 0; }
printf '\033[1;31m有验收项未通过，请按上面的提示排查。\033[0m\n' >&2
exit 1
