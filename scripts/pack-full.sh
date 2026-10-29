#!/usr/bin/env bash
# 打包可交付的「源码包」：prdms-src-<日期>.tar.gz
#
# 为什么需要这个脚本
#   reqmesh/ 是独立的**上游克隆**（有自己 .git），被 PRDMS 的 .gitignore 排除，
#   GitHub 上从来没有它。只把 PRDMS 仓库给一台新机器，`bootstrap-host.sh` 会在
#   第 1 步报 "reqmesh/backend 不存在"。所以交付物必须是「PRDMS + reqmesh 源码」
#   合成的源码包，本脚本负责生成它。
#
# 打包什么
#   PRDMS 已跟踪文件（git archive） + reqmesh 已跟踪文件（工作树版本，含本地补丁）
#
# **不**打包什么（刻意的）
#   .venv / node_modules / dist   —— 与 CPU 架构绑定。预编译产物跨平台不可用
#                                    （Windows/WSL2 用不了 aarch64 Linux 二进制），
#                                    由目标机的 bootstrap-host.sh 自行构建
#   data/ / .rt-secret / .rt-admin-pw / .env / deployment.local
#                                 —— 业务数据与凭据。目标机自己生成，不允许跨机搬运
#
# 用法
#   ./scripts/pack-full.sh                  # 输出到当前目录
#   ./scripts/pack-full.sh -o /tmp/out      # 指定输出目录
#
# 提示：打包前建议先把改动提交，否则包里会混入未提交内容（脚本会显式记录并告警）。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$PWD"
STAMP="$(date +%Y%m%d-%H%M%S)"

while [ $# -gt 0 ]; do
  case "$1" in
    -o|--out) OUT_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

die() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 1; }
log() { printf '\033[1;36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
warn() { printf '\033[1;33m[注意]\033[0m %s\n' "$*"; }

[ -d "$ROOT/reqmesh/backend" ] || die "找不到 $ROOT/reqmesh —— 本机没有 reqmesh 上游克隆，无法打包。请在一台已有 reqmesh/ 的机器上运行本脚本。"
[ -d "$ROOT/reqmesh-harness" ] || die "找不到 $ROOT/reqmesh-harness"
command -v git >/dev/null 2>&1 || die "缺少 git"
command -v tar >/dev/null 2>&1 || die "缺少 tar"

mkdir -p "$OUT_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/PRDMS"

# ── 1. PRDMS 已跟踪文件 ──────────────────────────────────────────────────────
log "[1/4] 导出 PRDMS 已跟踪文件"
( cd "$ROOT" && git archive HEAD ) | tar -x -C "$STAGE/PRDMS" || die "git archive 失败"
PRDMS_HEAD="$( cd "$ROOT" && git rev-parse --short HEAD )"
PRDMS_DIRTY="$( cd "$ROOT" && git status --porcelain | wc -l | tr -d ' ' )"
[ "$PRDMS_DIRTY" != "0" ] && warn "PRDMS 有 $PRDMS_DIRTY 项未提交改动，**不会**进入本包（git archive 只取 HEAD）"

# ── 2. reqmesh 上游源码（取工作树，含本地补丁）───────────────────────────────
log "[2/4] 导出 reqmesh 上游源码"
[ -d "$ROOT/reqmesh/.git" ] || die "$ROOT/reqmesh 不是 git 仓库，无法确认来源"
REQMESH_HEAD="$( cd "$ROOT/reqmesh" && git rev-parse --short HEAD )"
REQMESH_DIRTY="$( cd "$ROOT/reqmesh" && git status --porcelain | wc -l | tr -d ' ' )"
[ "$REQMESH_DIRTY" != "0" ] && warn "reqmesh 有 $REQMESH_DIRTY 项未提交改动，将作为「本地补丁」进入本包（这是预期：本地 3 个补丁从未提交）"

mkdir -p "$STAGE/PRDMS/reqmesh"
( cd "$ROOT/reqmesh" && git ls-files -z | tar -c --null -T - ) \
  | tar -x -C "$STAGE/PRDMS/reqmesh" || die "reqmesh 导出失败"

# ── 3. 清单 ─────────────────────────────────────────────────────────────────
log "[3/4] 生成 MANIFEST.txt"
{
  echo "PRDMS 源码包"
  echo "============="
  echo "生成时间      : $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "生成主机      : $(uname -s)/$(uname -m)"
  echo
  echo "[PRDMS]"
  echo "  commit      : $PRDMS_HEAD"
  echo "  未提交改动  : $PRDMS_DIRTY 项（未包含在本包中）"
  echo
  echo "[reqmesh 上游]（私有仓库，无法从公网克隆，故随包分发）"
  echo "  commit      : $REQMESH_HEAD"
  echo "  版本       : $(cat "$ROOT/reqmesh/VERSION" 2>/dev/null || echo '?')"
  echo "  本地补丁    : $REQMESH_DIRTY 项"
  echo "  许可证      : GPL-3.0（见 reqmesh/LICENSE）"
  echo
  echo "[本地补丁清单]"
  ( cd "$ROOT/reqmesh" && git status --porcelain | sed 's/^/  /' )
  echo
  echo "[本包不含]"
  echo "  .venv / node_modules / dist  —— 架构绑定，目标机自建"
  echo "  data/ / .rt-secret / .rt-admin-pw / .env / deployment.local  —— 数据与凭据"
  echo
  echo "[目标机使用]"
  echo "  tar xzf <本包> && cd PRDMS && ./scripts/bootstrap-host.sh"
} > "$STAGE/PRDMS/MANIFEST.txt"

# ── 4. 打包 ─────────────────────────────────────────────────────────────────
OUT="$OUT_DIR/prdms-src-$STAMP.tar.gz"
log "[4/4] 打包 → $OUT"
( cd "$STAGE" && tar -czf "$OUT" PRDMS ) || die "打包失败"

SIZE="$(ls -l "$OUT" | awk '{printf "%.1f MB", $5/1048576}')"
if command -v shasum >/dev/null 2>&1; then
  SHA="$(shasum -a 256 "$OUT" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  SHA="$(sha256sum "$OUT" | awk '{print $1}')"
else
  SHA="(无 sha256 工具)"
fi

echo
echo "完成：$OUT  ($SIZE)"
echo "sha256 = $SHA"
echo
echo "把这个文件和它的 sha256 一起交给目标机；目标机按 docs/deployment-host.md §0 操作。"
