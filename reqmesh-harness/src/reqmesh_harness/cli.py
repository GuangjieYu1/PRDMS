"""reqmesh-harness CLI 入口（console script 与 `python -m` 均可用）。

- `reqmesh-harness approvals <list|add|remove> ...`——审批白名单维护（P2）；
- 其余参数透传 MCP server 主程序（`--transport stdio|http`，P1 行为不变）：
  `reqmesh-harness --transport http` 等价于 `python -m reqmesh_harness.server --transport http`。
"""

from __future__ import annotations

import sys
from typing import Sequence

from .guardrails.approvals_cli import approvals_main


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "approvals":
        return approvals_main(args[1:])
    from .server import main as server_main

    return server_main(args)


if __name__ == "__main__":
    sys.exit(main())
