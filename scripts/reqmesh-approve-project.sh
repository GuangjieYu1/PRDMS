#!/usr/bin/env bash
# 给 ReqMesh 项目开写权限（白名单 =「工具 × 项目」逐条授权）。
#
# 在**任意一台装了 aliyun CLI 并配置好 AccessKey 的电脑**上运行：脚本通过
# 云助手（Cloud Assistant）在服务器上改白名单，不需要 SSH、不需要开放端口。
#
# 用法
#   ./scripts/reqmesh-approve-project.sh IATA_TEST_002
#   ./scripts/reqmesh-approve-project.sh IATA_TEST_002 --status          # 只看，不改
#   ./scripts/reqmesh-approve-project.sh IATA_TEST_002 --tools create_requirement,update_requirement
#   ./scripts/reqmesh-approve-project.sh IATA_TEST_002 --dry-run-only    # 只放行 dry_run
#
# 行为
#   · 项目不存在         → 报错退出 2（不会凭空建白名单条目）
#   · 已全部开启         → 提示"已开启"，不动文件
#   · 部分开启           → 只补缺失的那几条
#   · 改完不用重启       → 审批门每次调用重读白名单
#
# 环境变量（都有默认值，切换实例时覆盖）
#   REQMESH_ECS_ID      默认 i-2ze2awf50fsyswsz3tfg
#   REQMESH_ECS_REGION  默认 cn-beijing
#   REQMESH_ECS_USER    云助手执行用户（默认 root）
#
# 依赖：aliyun CLI（已配置有效 AccessKey）、base64、grep、sed

set -euo pipefail

ECS_ID="${REQMESH_ECS_ID:-i-2ze2awf50fsyswsz3tfg}"
ECS_REGION="${REQMESH_ECS_REGION:-cn-beijing}"
APPROVALS="/srv/reqmesh/state/approvals.toml"
PROJECTS_DIR="/srv/reqmesh/data/projects"

# 13 个写工具（DRAFT 7 + MUTATE 6）
ALL_TOOLS="create_comment create_component create_requirement create_risk
create_verification_case draft_requirement review_item
run_verification set_allocation set_relations
update_component update_requirement update_verification_case"

PROJ=""
STATUS_ONLY=0
DRY_ONLY="false"
TOOLS="$ALL_TOOLS"

die() { printf '\033[1;31m[错误]\033[0m %s\n' "$*" >&2; exit 2; }
log() { printf '\033[1;36m[..]\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m[成功]\033[0m %s\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --status) STATUS_ONLY=1; shift ;;
    --dry-run-only) DRY_ONLY="true"; shift ;;
    --tools) TOOLS="$(printf '%s' "$2" | tr ',' ' ')"; shift 2 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    -*) die "未知参数：$1" ;;
    *) [ -z "$PROJ" ] && PROJ="$1" || die "多余参数：$1"; shift ;;
  esac
done

[ -n "$PROJ" ] || die "用法：$0 <项目id> [--status] [--tools a,b] [--dry-run-only]"

# 项目 id 会嵌进远端脚本，必须先断言字符集（防注入）
case "$PROJ" in
  *[!A-Za-z0-9_-]*) die "项目 id 只允许字母/数字/下划线/连字符：$PROJ" ;;
esac
[ ${#PROJ} -le 64 ] || die "项目 id 过长（>64）"

command -v aliyun >/dev/null 2>&1 || die "未安装 aliyun CLI。安装：https://help.aliyun.com/zh/cli/"
aliyun sts GetCallerIdentity >/dev/null 2>&1 || die "aliyun 凭据无效。先执行：aliyun configure"

# ── 远端脚本（项目 id 已断言为安全字符）─────────────────────────────────────────
# 注意：不能写成 REMOTE=$(cat <<EOF ... EOF)，bash 3.2 在命令替换里解析含 `case`/`;;`
# 的 heredoc 会报语法错误。改为先落临时文件。
TMPSCRIPT=$(mktemp)
trap 'rm -f "$TMPSCRIPT"' EXIT
cat > "$TMPSCRIPT" <<REMOTE_EOF
set -e
PROJ="$PROJ"
F="$APPROVALS"
DIR="$PROJECTS_DIR"
DRY_ONLY="$DRY_ONLY"
TOOLS="$TOOLS"
STATUS_ONLY=$STATUS_ONLY

# 1) 项目必须真实存在（目录即项目）
if [ ! -d "\$DIR/\$PROJ" ]; then
  echo "STATUS=NOT_FOUND"
  echo "AVAILABLE=\$(ls -1 "\$DIR" 2>/dev/null | tr '\n' ' ')"
  exit 0
fi

# 2) 取该项目已有的工具名
existing() {
  awk -v p="\$PROJ" '
    /^\[\[approvals\]\]/ {tool=""}
    /^tool = / {gsub(/^tool = |"/,"");tool=\$0}
    /^project = / {gsub(/^project = |"/,"");if (\$0==p && tool!="") print tool}
  ' "\$F" 2>/dev/null | sort -u
}
# existing() 输出是**换行**分隔；下面 case 用空格做边界匹配，必须先归一化。
# （踩过：没归一化时 13 个工具一个都匹配不上，每次运行都会重复追加一遍。）
EXISTING=\$(existing | tr '\n' ' ')

MISSING=""
ADDED=""
for t in \$TOOLS; do
  case " \$EXISTING " in
    *" \$t "*) ;;
    *) MISSING="\$MISSING \$t" ;;
  esac
done

echo "STATUS=OK"
echo "EXISTING_COUNT=\$(printf '%s' "\$EXISTING" | wc -w | tr -d ' ')"
if [ -z "\$MISSING" ]; then
  echo "RESULT=ALREADY_ENABLED"
  echo "TOOL_COUNT=\$(printf '%s' "\$TOOLS" | wc -w | tr -d ' ')"
  echo "TOTAL_ENTRIES=\$(grep -c '^\[\[approvals\]\]' "\$F" 2>/dev/null || echo 0)"
  exit 0
fi

if [ "\$STATUS_ONLY" = "1" ]; then
  echo "RESULT=PARTIAL_OR_NONE"
  echo "MISSING=\$(printf '%s' "\$MISSING" | sed 's/^ *//')"
  echo "TOTAL_ENTRIES=\$(grep -c '^\[\[approvals\]\]' "\$F" 2>/dev/null || echo 0)"
  exit 0
fi

# 3) 备份后追加
cp "\$F" "\$F.bak.\$(date +%s)" 2>/dev/null || true
for t in \$MISSING; do
  printf '\n[[approvals]]\ntool = "%s"\nproject = "%s"\ndry_run_only = %s\n' "\$t" "\$PROJ" "\$DRY_ONLY" >> "\$F"
  ADDED="\$ADDED \$t"
done
chmod 600 "\$F" 2>/dev/null || true

# 4) 回读确认（防半行写入）
FINAL=""
for t in \$ADDED; do
  if awk -v p="\$PROJ" -v want="\$t" '
      /^\[\[approvals\]\]/ {tool=""}
      /^tool = / {gsub(/^tool = |"/,"");tool=\$0}
      /^project = / {gsub(/^project = |"/,"");if (\$0==p && tool==want) found=1}
      END{exit !found}' "\$F"; then
    FINAL="\$FINAL \$t"
  fi
done

echo "RESULT=ADDED"
echo "ADDED=\$(printf '%s' "\$ADDED" | sed 's/^ *//')"
echo "VERIFIED=\$(printf '%s' "\$FINAL" | sed 's/^ *//')"
echo "TOTAL_ENTRIES=\$(grep -c '^\[\[approvals\]\]' "\$F" 2>/dev/null || echo 0)"
REMOTE_EOF

log "在 $ECS_ID 上检查项目 $PROJ …"

B64=$(base64 < "$TMPSCRIPT" | tr -d '\n')
INV=$(aliyun ecs RunCommand --RegionId "$ECS_REGION" --Type RunShellScript \
        --InstanceId.1 "$ECS_ID" --CommandContent "$B64" --ContentEncoding Base64 \
        --Timeout 120 --Name "reqmesh-approve-$PROJ" 2>&1 \
      | grep -o '"InvokeId"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
[ -n "$INV" ] || die "云助手调用失败（检查 AccessKey 与该实例权限）"

# 轮询结果
OUT=""
i=0
while [ $i -lt 30 ]; do
  sleep 3
  i=$((i+1))
  RAW=$(aliyun ecs DescribeInvocationResults --RegionId "$ECS_REGION" --InvokeId "$INV" 2>/dev/null || true)
  ST=$(printf '%s' "$RAW" | grep -o '"InvocationStatus"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
  case "$ST" in
    Success|Failed|Timeout)
      OUT=$(printf '%s' "$RAW" | grep -o '"Output"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
      break ;;
  esac
done
[ -n "$OUT" ] || die "等待云助手结果超时（InvokeId=$INV）"

# base64 解码（macOS 用 -D，Linux 用 -d）
DEC=$(printf '%s' "$OUT" | base64 -d 2>/dev/null || printf '%s' "$OUT" | base64 -D 2>/dev/null || true)
[ -n "$DEC" ] || die "结果解码失败"

get() { printf '%s\n' "$DEC" | sed -n "s/^$1=//p" | head -1; }

STATUS=$(get STATUS)
case "$STATUS" in
  NOT_FOUND)
    printf '\033[1;31m[错误]\033[0m 项目不存在：%s\n' "$PROJ" >&2
    printf '  现有项目：%s\n' "$(get AVAILABLE)" >&2
    printf '  请先在 ReqMesh 前端新建该项目，再回来开权限。\n' >&2
    exit 2 ;;
  OK) ;;
  *) die "远端返回异常状态：$STATUS（原始输出见下）\n$DEC" ;;
esac

RESULT=$(get RESULT)
case "$RESULT" in
  ALREADY_ENABLED)
    ok "项目 $PROJ 已开启写权限（$(get TOOL_COUNT) 个工具），无需改动。"
    printf '  白名单总条目：%s\n' "$(get TOTAL_ENTRIES)" ;;
  PARTIAL_OR_NONE)
    printf '\033[1;33m[现状]\033[0m 项目 %s 存在，但下列工具尚未开启：\n' "$PROJ"
    printf '  %s\n' "$(get MISSING)"
    printf '  去掉 --status 重跑即可开启。\n'
    printf '  白名单总条目：%s\n' "$(get TOTAL_ENTRIES)" ;;
  ADDED)
    ok "已为项目 $PROJ 开启写权限。"
    printf '  新增：%s\n' "$(get ADDED)"
    V=$(get VERIFIED)
    if [ -n "$V" ]; then
      printf '  回读确认：%s\n' "$V"
    else
      printf '\033[1;31m[警告]\033[0m 回读未确认到新增条目，请人工检查 %s\n' "$APPROVALS"
    fi
    printf '  白名单总条目：%s\n' "$(get TOTAL_ENTRIES)"
    printf '  \033[2m无需重启服务：审批门每次调用重读白名单。\033[0m\n' ;;
  *) die "未知结果：$RESULT\n$DEC" ;;
esac
