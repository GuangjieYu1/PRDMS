"""候选检查内核（纯函数，零网络）。

当前只有结构检查（``structural``）。场景求值属另一条路径——它需要求值器且
必须带取值，与本包的"不看取值"定位不同，故不混在一起。

设计约束（与 ``report/`` 一致）：纯函数、无网络、无文件、不接触写路径，
便于单测与离线复算。
"""

from .structural import (
    ALLOWED_FUNCS,
    ALLOWED_NODE_TYPES,
    CHECKED_AGAINST,
    SOURCE_OF_TRUTH,
    check_expression,
    check_project,
)

__all__ = [
    "ALLOWED_FUNCS",
    "ALLOWED_NODE_TYPES",
    "CHECKED_AGAINST",
    "SOURCE_OF_TRUTH",
    "check_expression",
    "check_project",
]
