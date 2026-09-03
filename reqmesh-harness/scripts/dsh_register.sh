#!/usr/bin/env bash
# dsh_register.sh：幂等注册 mcp-reqmesh（stdio）到 DSH web profile 的 cordis.patch.yml。
#
# 注册条目（spec p6 决策③ 定稿；与 P5 spec「DSH 部署步骤」逐字一致）：
#   serverName=reqmesh / transport=stdio / command=venv console script / args=['--transport','stdio']
#   cwd=reqmesh-harness/（.env 生效）/ env 转发 REQMESH_USERNAME/REQMESH_PASSWORD（!!js process.env，
#   凭据不进 patch 文件）。
#
# 用法：
#   dsh_register.sh --check         报告当前状态（已存在/缺失），exit 0=已存在
#   dsh_register.sh --dry-run（默认）打印将插入的条目与 diff（绝对不写文件）
#   dsh_register.sh --apply         备份后插入；重复执行不产生重复条目（幂等，先检查后插入）
#   --target FILE                   目标 patch 文件（默认 /home/user/.dsh/profiles/web/cordis.patch.yml；
#                                   另设路径用于测试/并行安装验证）
#   --backup-dir DIR                备份目录（默认 <target 同目录>/.dsh-register-backups/）
#
# 责任边界（spec 决策③）：实际应用与重启 DSH 宿主属操作员（本机用户/方向层）维护窗口动作——
# 重启 8080 宿主会中断方向层自身工作 GUI，只有宿主使用者能择机执行；本脚本只产出/预览/受控插入，
# 不承担重启；备份与回滚步骤见 docs/deployment.md「DSH 注册」。
set -u

DEFAULT_TARGET="/home/user/.dsh/profiles/web/cordis.patch.yml"
TARGET="${DEFAULT_TARGET}"
BACKUP_DIR=""
ACTION="dry-run"

# 注册条目（决策③ 片段；缩进与语序保持逐字一致）
ENTRY_BLOCK=$'- id: mcp-reqmesh\n  name: \'@deepseek-ai/dsh-mcp-client\'\n  config:\n    serverName: reqmesh\n    transport: stdio\n    command: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness/.venv/bin/reqmesh-harness\n    args: [\'--transport\', \'stdio\']\n    cwd: /home/user/DeepseekHarnessProjects/PRDMS/reqmesh-harness\n    env:\n      REQMESH_USERNAME: !!js process.env.REQMESH_USERNAME\n      REQMESH_PASSWORD: !!js process.env.REQMESH_PASSWORD'
MARKER='- id: mcp-reqmesh'

# ---- 参数
while [ $# -gt 0 ]; do
  case "$1" in
    --apply) ACTION="apply" ;;
    --dry-run) ACTION="dry-run" ;;
    --check) ACTION="check" ;;
    --target) TARGET="$2"; shift ;;
    --backup-dir) BACKUP_DIR="$2"; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（--help 见用法）" >&2; exit 2 ;;
  esac
  shift
done

if [ -z "${BACKUP_DIR}" ]; then
  BACKUP_DIR="$(dirname "$TARGET")/.dsh-register-backups"
fi

if [ ! -f "$TARGET" ]; then
  echo "错误：patch 文件不存在：$TARGET（--target 可指定；web profile 无此文件时请先按 dsh 说明创建）" >&2
  exit 2
fi

present() {
  grep -qF -- "${MARKER}" "$TARGET"
}

# 插入后内容 → stdout（原样 + 必要时补换行 + 条目块；绝不修改原文件）
emit_new_content() {
  cat "$TARGET"
  if ! present; then
    last_byte_hex="$(tail -c 1 "$TARGET" | od -An -t x1 | tr -d ' \n')"
    if [ "${last_byte_hex}" != "0a" ]; then
      printf '\n'
    fi
    printf '%s\n' "$ENTRY_BLOCK"
  fi
}

# ---- check
if [ "$ACTION" = "check" ]; then
  if present; then
    echo "状态：已存在（$TARGET 含 ${MARKER} 条目）"
    exit 0
  fi
  echo "状态：缺失（$TARGET 无 ${MARKER} 条目）"
  exit 1
fi

# ---- dry-run（默认）：diff 预览
if [ "$ACTION" = "dry-run" ]; then
  if present; then
    echo "dry-run：条目已存在，无变更（幂等）"
    exit 0
  fi
  TMP="$(mktemp)"
  emit_new_content > "$TMP"
  echo "dry-run：将插入以下条目到 $TARGET（条目与 spec 决策③ 逐字一致）："
  echo
  printf '%s\n' "$ENTRY_BLOCK"
  echo
  echo "--- diff（-：现有 / +：插入后）---"
  diff -u "$TARGET" "$TMP" || true
  rm -f "$TMP"
  echo "应用：$0 --apply [--target $TARGET]（应用与重启属操作员维护窗口责任，spec 决策③）"
  exit 0
fi

# ---- apply：备份 + 原子替换（先检查后插入 → 绝不重复）
if present; then
  echo "apply：条目已存在，无变更（幂等）"
  exit 0
fi
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/cordis.patch.yml.$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$TARGET" "$BACKUP"
TMP="$(mktemp)"
emit_new_content > "$TMP"
mv -f "$TMP" "$TARGET"
if present; then
  echo "apply：条目已插入（幂等）；备份：$BACKUP"
  echo "下一步（操作员）：重启 DSH web 宿主 → 验证 40 工具 → B 段冒烟 → evals live（docs/deployment.md）"
  exit 0
fi
# 校验失败：回滚备份
cp -p "$BACKUP" "$TARGET"
echo "错误：插入后校验失败，已回滚备份 $BACKUP" >&2
exit 1
