#!/usr/bin/env bash
# bootstrap-host.sh — PRDMS 主机一键引导（Linux / macOS 原生；Windows 请使用 WSL2）
#
# 职责：把从共享文件夹或 GitHub 取到的 PRDMS 目录，在「本机」就地完成：
#   reqmesh 后端 venv + 前端构建 + 密钥/种子数据 + reqmesh-harness uv 环境 + 服务账号 .env
# 不负责：守护化（systemd 模板见 docs/deployment.md）、DSH 注册（见 docs/deployment-host.md §5）。
#
# 用法：
#   ./scripts/bootstrap-host.sh                 # 全量引导（校验+构建+配置，不启动）
#   ./scripts/bootstrap-host.sh --start         # 引导后立即后台启动 reqmesh + 打印验证结果
#   ./scripts/bootstrap-host.sh --skip-ui-build # 跳过前端构建（已有 dist/ 时）
#   ./scripts/bootstrap-host.sh --port 8000     # reqmesh 监听端口（默认 8000）
set -u

PORT=8000
SKIP_UI=0
DO_START=0

while [ $# -gt 0 ]; do
  case "$1" in
    --start) DO_START=1 ;;
    --skip-ui-build) SKIP_UI=1 ;;
    --port) PORT="$2"; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help）" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

log() { printf '\033[1;34m[bootstrap]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }

# ── 0. 平台检查 ──────────────────────────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  MINGW*|MSYS*|CYGWIN*) die "Windows 原生不支持本栈（weasyprint/pango 依赖、POSIX 脚本、VM 包内 aarch64 产物均不适用）。请在 Windows 上启用 WSL2，把 PRDMS 目录放进 WSL 文件系统后重跑本脚本（详见 docs/deployment-host.md §1）。" ;;
  Linux|Darwin) log "平台：$OS（$(uname -m)）" ;;
  *) die "不支持的操作系统：$OS" ;;
esac

# ── 1. 工具检查 ──────────────────────────────────────────────────────────────
need() { command -v "$1" >/dev/null 2>&1 || die "缺少 $1 —— 安装方法见 docs/deployment-host.md §1（$2）"; }
need python3 "Python 3.11+"
need node "Node 18+"
need npm "Node 18+"
need git "git"
need openssl "openssl"
PY_MAJOR="$(python3 -c 'import sys;print(sys.version_info[1])' 2>/dev/null || echo 0)"
[ "$PY_MAJOR" -ge 11 ] 2>/dev/null || die "Python 3.11+ 必需（当前 3.$PY_MAJOR）"
command -v uv >/dev/null 2>&1 || { log "未装 uv —— 尝试 python3 -m pip install --user uv"; python3 -m pip install --user uv >/dev/null 2>&1 || die "uv 安装失败，请手动安装（docs/deployment-host.md §1）"; }
export PATH="$HOME/.local/bin:$PATH"

# ── 2. reqmesh 后端 venv ─────────────────────────────────────────────────────
log "[1/6] reqmesh 后端依赖"
cd "$ROOT/reqmesh/backend" || die "reqmesh/backend 不存在"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || die "venv 创建失败"
  .venv/bin/python -m pip install -q -r requirements.txt || die "后端依赖安装失败（重试或看 §7 故障排查）"
else
  log "  已存在 .venv，跳过（如需重装：rm -rf .venv 后重跑）"
fi

# ── 3. reqmesh 前端构建 ──────────────────────────────────────────────────────
log "[2/6] reqmesh 前端"
cd "$ROOT/reqmesh/frontend" || die "reqmesh/frontend 不存在"
if [ "$SKIP_UI" = 0 ]; then
  [ -d node_modules ] || { npm ci --silent || npm install --silent || die "npm 依赖安装失败"; }
  npm run build || die "前端构建失败（node 版本或网络问题，见 §7）"
else
  log "  --skip-ui-build：复用现有 dist/"
fi
[ -f dist/index.html ] || die "dist/index.html 不存在，前端不可用"

# ── 4. 密钥与种子数据 ────────────────────────────────────────────────────────
log "[3/6] 密钥与数据"
cd "$ROOT/reqmesh" || exit 1
[ -f .rt-secret ] || { openssl rand -hex 32 > .rt-secret && chmod 600 .rt-secret && log "  生成 .rt-secret"; }
[ -f .rt-admin-pw ] || { openssl rand -base64 12 > .rt-admin-pw && chmod 600 .rt-admin-pw && log "  生成 .rt-admin-pw（admin 初始密码）"; }
mkdir -p data/projects
if [ -z "$(ls -A data/projects 2>/dev/null)" ]; then
  backend/.venv/bin/python seed_cessna.py --data-root data/projects || die "演示项目播种失败"
  log "  播种 cessna-172 演示项目"
fi

# ── 5. reqmesh-harness（uv 环境 + 服务账号 .env）────────────────────────────
log "[4/6] reqmesh-harness"
cd "$ROOT/reqmesh-harness" || die "reqmesh-harness 不存在"
uv sync || die "uv sync 失败"
if [ ! -f .env ]; then
  SERVICE_PW="$(openssl rand -base64 16)"
  umask 077
  cat > .env <<EOF
REQMESH_BASE_URL=http://127.0.0.1:${PORT}
REQMESH_USERNAME=reqmesh-harness
REQMESH_PASSWORD=${SERVICE_PW}
EOF
  chmod 600 .env
  log "  生成 .env（服务账号 reqmesh-harness 随机密码）。启动后请用 admin 登录 UI 创建该账号（角色 maintainer），密码取自此 .env —— 见 docs/deployment-host.md §4.3"
fi
log "[5/6] 校验：harness 工具数"
.venv/bin/reqmesh-harness --help >/dev/null 2>&1 || die "reqmesh-harness 入口不可用"
TOOL_COUNT="$(printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"bootstrap","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | .venv/bin/reqmesh-harness --transport stdio 2>/dev/null \
  | tail -1 | python3 -c "import json,sys; print(len(json.loads(sys.stdin.read())['result']['tools']))" 2>/dev/null || echo 0)"
log "  MCP 工具数：${TOOL_COUNT}（预期 40）"

# ── 6. （可选）启动 ──────────────────────────────────────────────────────────
if [ "$DO_START" = 1 ]; then
  log "[6/6] 启动 reqmesh"
  cd "$ROOT/reqmesh/backend" || exit 1
  RT_PROFILE=personal \
  RT_STATIC_DIR="$(realpath ../frontend/dist)" \
  RT_DATA_ROOT="$(realpath ../data/projects)" \
  RT_SECRET="$(cat ../.rt-secret)" \
  RT_ADMIN_PASSWORD="$(cat ../.rt-admin-pw)" \
  RT_BASE_URL="http://127.0.0.1:${PORT}" \
    nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" \
    > /tmp/reqmesh-host.log 2>&1 &
  sleep 3
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    log "  reqmesh 已启动：http://127.0.0.1:${PORT}（日志 /tmp/reqmesh-host.log；admin 密码见 reqmesh/.rt-admin-pw）"
    curl -s "http://127.0.0.1:${PORT}/health"
    printf '\n'
  else
    log "  启动失败，查看 /tmp/reqmesh-host.log" >&2
  fi
else
  log "[6/6] 未加 --start：启动命令见 docs/deployment-host.md §3.6"
fi

log "完成。下一步：docs/deployment-host.md §4（验证清单）"
