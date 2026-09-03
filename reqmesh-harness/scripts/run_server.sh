#!/usr/bin/env bash
# run_server.sh：免 root 启动/停止/状态/日志（spec p6 决策②；本机默认部署路径——无用户级 systemd）。
#
# 用法：scripts/run_server.sh <start|stop|status|logs>
#   start    以 nohup 拉起 streamable-HTTP MCP server（默认 127.0.0.1:8081；可经
#            REQMESH_HARNESS_HOST / REQMESH_HARNESS_PORT 覆盖），pidfile + 日志落 XDG state；
#   stop     按 pidfile 终止并清理；
#   status   显示 pid / 存活 / 端口监听（健康探测）；
#   logs     输出日志尾部（LOG_LINES=200 可调；logs --follow 跟踪）。
#
# 凭据边界：凭据只经 shell 环境变量或 reqmesh-harness/.env 注入（pydantic-settings env_file），
# 本脚本不含任何凭据字面量；cwd=reqmesh-harness/ 使 .env 生效。
# 责任边界：实际长期拉起属操作员按 docs/deployment.md 执行；本脚本只管理本进程。
set -u

# ---- 路径（脚本位于 <repo>/reqmesh-harness/scripts/）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_BIN="${HARNESS_DIR}/.venv/bin/reqmesh-harness"

# ---- 监听参数（settings 同名环境变量；默认 127.0.0.1:8081 = P6 正式端口）
HOST="${REQMESH_HARNESS_HOST:-127.0.0.1}"
PORT="${REQMESH_HARNESS_PORT:-8081}"

# ---- XDG state（pidfile + 日志）
XDG_STATE="${XDG_STATE_HOME:-${HOME}/.local/state}/reqmesh-harness"
PIDFILE="${XDG_STATE}/server.pid"
LOGFILE="${XDG_STATE}/server.log"

# ---- 便携端口探测（python3 socket；无 lsof/ss 依赖）
port_open() {
  python3 - "$1" <<'PYEOF'
import socket, sys
host, port = "127.0.0.1", int(sys.argv[1])
try:
    with socket.create_connection((host, port), timeout=1.0):
        sys.exit(0)
except OSError:
    sys.exit(1)
PYEOF
}

pid_alive() {
  local pid="$1"
  kill -0 "$pid" 2>/dev/null
}

read_pid() {
  if [ -f "${PIDFILE}" ]; then
    cat "${PIDFILE}" 2>/dev/null
  fi
}

status_cmd() {
  local pid; pid="$(read_pid)"
  if [ -z "${pid}" ] || ! pid_alive "${pid}"; then
    echo "状态：未运行（pidfile ${PIDFILE} 缺失或进程已退出）"
    return 1
  fi
  if port_open "${PORT}"; then
    echo "状态：运行中 pid=${pid} pidfile=${PIDFILE}；streamable-HTTP 监听 ${HOST}:${PORT}（/mcp 端点）"
    echo "日志：${LOGFILE}"
    return 0
  fi
  echo "状态：进程存活 pid=${pid}，但端口 ${PORT} 未监听（启动失败？见日志 ${LOGFILE}）"
  return 1
}

start_cmd() {
  if [ ! -x "${VENV_BIN}" ]; then
    echo "错误：未找到 venv console script：${VENV_BIN}（先 uv sync）" >&2
    return 2
  fi
  local pid; pid="$(read_pid)"
  if [ -n "${pid}" ] && pid_alive "${pid}"; then
    echo "已在运行（pid=${pid}，${HOST}:${PORT}）；如需重启请先 stop（幂等 start 不重复拉起）"
    return 0
  fi
  mkdir -p "${XDG_STATE}"
  # 凭据经 shell 环境/.env（cwd=HARNESS_DIR）；host/port 经 CLI 覆盖（settings 优先级 CLI > env）
  nohup "${VENV_BIN}" --transport http --host "${HOST}" --port "${PORT}" >>"${LOGFILE}" 2>&1 &
  local new_pid=$!
  echo "${new_pid}" >"${PIDFILE}"
  # 等待端口就绪（≤10s；失败则回滚 pidfile）
  for _ in $(seq 1 20); do
    if port_open "${PORT}"; then
      echo "已启动 pid=${new_pid}；streamable-HTTP 监听 ${HOST}:${PORT}（/mcp）；日志 ${LOGFILE}"
      return 0
    fi
    if ! pid_alive "${new_pid}"; then
      rm -f "${PIDFILE}"
      echo "错误：进程启动即退出（日志末尾见下）：" >&2
      tail -n 20 "${LOGFILE}" >&2 || true
      return 1
    fi
    sleep 0.5
  done
  echo "警告：10s 内未见端口 ${PORT} 监听（进程可能仍在启动，pid=${new_pid}；见日志 ${LOGFILE}）"
  return 0
}

stop_cmd() {
  local pid; pid="$(read_pid)"
  if [ -z "${pid}" ] || ! pid_alive "${pid}"; then
    rm -f "${PIDFILE}"
    echo "未运行（pidfile 已清理）"
    return 0
  fi
  kill "${pid}" 2>/dev/null
  for _ in $(seq 1 20); do
    pid_alive "${pid}" || break
    sleep 0.5
  done
  if pid_alive "${pid}"; then
    echo "警告：pid=${pid} 未在 10s 内退出（可用 kill -9 ${pid} 强制）" >&2
    return 1
  fi
  rm -f "${PIDFILE}"
  echo "已停止（pid=${pid}；pidfile 已清理）"
  return 0
}

logs_cmd() {
  local lines="${LOG_LINES:-200}"
  if [ "${1:-}" = "--follow" ]; then
    tail -f "${LOGFILE}"
  else
    tail -n "${lines}" "${LOGFILE}" 2>/dev/null || echo "日志文件不存在：${LOGFILE}"
  fi
}

case "${1:-}" in
  start)  start_cmd ;;
  stop)   stop_cmd ;;
  status) status_cmd ;;
  logs)   logs_cmd "${2:-}" ;;
  *) echo "用法：$0 <start|stop|status|logs [--follow]>" >&2; exit 2 ;;
esac
