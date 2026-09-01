"""`reqmesh-harness approvals` CLI：交互式维护白名单（与手改 TOML 同源同文件）。

- `list`：列出条目；
- `add <tool> [--project P] [--dry-run-only] [--yes]`：添加条目（TTY 下 y/N 确认；
  `--yes` 供脚本；MUTATE/ADMIN 必须给具体 project；READ 层工具不可入白名单）；
- `remove <tool> [--project P] [--yes]`：删除条目（`--project` 省略 = 删该工具全部条目）。

白名单文件（XDG config，0600）是唯一裁决源；本 CLI 与手改文件共用同一存储，
无双轨漂移。调用中途弹窗确认（MCP elicitation）属 P5 开放问题，本 CLI 不涉及。
"""

from __future__ import annotations

import sys
from typing import Sequence

from ..config import Settings
from ..errors import ApprovalConfigError
from ..tools import build_registry
from .whitelist import WhitelistEntry, WhitelistStore

LEVELS_NEEDING_PROJECT = ("MUTATE", "ADMIN")


def approvals_main(argv: Sequence[str]) -> int:
    settings = Settings()
    store = WhitelistStore(settings.resolved_approvals_file())
    args = list(argv)
    if not args:
        _usage(store)
        return 2
    sub = args[0]
    try:
        if sub == "list":
            return _list(store)
        if sub == "add":
            return _add(store, args[1:])
        if sub == "remove":
            return _remove(store, args[1:])
    except ApprovalConfigError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    _usage(store)
    return 2


def _usage(store: WhitelistStore) -> None:
    print(
        "用法: reqmesh-harness approvals <list|add|remove> ...\n"
        f"白名单文件: {store.path}\n"
        "  list                        列出条目\n"
        "  add <tool> [--project P] [--dry-run-only] [--yes]\n"
        "  remove <tool> [--project P] [--yes]\n"
        "DRAFT 条目 project 可省略（通配全部项目）；MUTATE/ADMIN 必须指定具体 project。"
    )


def _list(store: WhitelistStore) -> int:
    entries = store.load()
    if not entries:
        print(f"（空）{store.path}")
        return 0
    print(f"{store.path}")
    for i, entry in enumerate(entries, start=1):
        extra = f" （仅 dry_run）" if entry.dry_run_only else ""
        print(f"{i:>3}. {entry.tool}  project={entry.project or '<通配>'}{extra}")
    return 0


def _add(store: WhitelistStore, args: list[str]) -> int:
    parser = _add_parser()
    try:
        opts = parser.parse_args(args)
    except SystemExit:
        return 2
    tool = opts.tool
    if opts.project is not None and not opts.project:
        print("错误: --project 不能为空字符串", file=sys.stderr)
        return 2
    level = _tool_level(tool)
    if level is None:
        print(f"错误: 工具 {tool} 不在注册表（无此工具名）", file=sys.stderr)
        return 2
    if level == "READ":
        print(f"错误: {tool} 是 READ 层工具（只读），不需要也不允许白名单条目", file=sys.stderr)
        return 2
    if level in LEVELS_NEEDING_PROJECT and not opts.project:
        print(f"错误: {tool} 是 {level} 层工具，白名单条目必须指定具体 --project", file=sys.stderr)
        return 2
    entry = WhitelistEntry(tool=tool, project=opts.project, dry_run_only=bool(opts.dry_run_only))
    existing = store.load()
    if entry in existing:
        print(f"条目已存在（无变化）: {entry.label}")
        return 0
    if not _confirm("添加白名单条目", entry, yes=opts.yes):
        print("已取消")
        return 1
    store.append(entry)
    print(f"已添加: {entry.label} → {store.path}")
    return 0


def _remove(store: WhitelistStore, args: list[str]) -> int:
    parser = _remove_parser()
    try:
        opts = parser.parse_args(args)
    except SystemExit:
        return 2
    entries = store.load()
    matched = [e for e in entries if e.tool == opts.tool and (opts.project is None or e.project == opts.project)]
    if not matched:
        print(f"无匹配条目: tool={opts.tool} project={opts.project or '<全部>'}", file=sys.stderr)
        return 1
    if not _confirm("删除白名单条目", matched[0], yes=opts.yes, count=len(matched)):
        print("已取消")
        return 1
    removed = store.remove(opts.tool, opts.project)
    print(f"已删除 {removed} 条: tool={opts.tool} project={opts.project or '<全部>'}")
    return 0


def _confirm(action: str, entry: WhitelistEntry, *, yes: bool, count: int = 1) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print("非交互终端：请加 --yes 供脚本使用", file=sys.stderr)
        return False
    label = entry.label + (f"（共 {count} 条）" if count > 1 else "")
    answer = input(f"{action}: {label}? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _tool_level(tool: str) -> str | None:
    for spec in build_registry().all():
        if spec.name == tool:
            return spec.level
    return None


def _add_parser():
    import argparse

    parser = argparse.ArgumentParser(prog="reqmesh-harness approvals add", add_help=True)
    parser.add_argument("tool", help="工具名（注册表）")
    parser.add_argument("--project", default=None, help="具体项目 id（MUTATE/ADMIN 必填；省略 = DRAFT 通配）")
    parser.add_argument("--dry-run-only", action="store_true", help="只放行 dry_run 调用（灰度上线用）")
    parser.add_argument("--yes", action="store_true", help="跳过确认（供脚本）")
    return parser


def _remove_parser():
    import argparse

    parser = argparse.ArgumentParser(prog="reqmesh-harness approvals remove", add_help=True)
    parser.add_argument("tool", help="工具名（注册表）")
    parser.add_argument("--project", default=None, help="具体项目 id；省略 = 删除该工具全部条目")
    parser.add_argument("--yes", action="store_true", help="跳过确认（供脚本）")
    return parser
