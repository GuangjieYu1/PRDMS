"""本地 quality lint 模块（P3）。

- rules：20 条规则表（公开契约：id/severity/weight/INCOSE 引用）+ 6 类确定性修正表；
- engine：打分（镜像上游 max_penalty=sum(weights)）、config 装载（复数键映射）、
  残余白名单（unwanted→negation）与过线判定；
- 许可证边界：独立重写，不复刻 reqmesh GPL 源码（行为等价性靠冒烟对账）。
"""

from .engine import (
    DEFAULT_CONFIG,
    Finding,
    LintConfig,
    LintReport,
    RESIDUAL_WHITELIST,
    apply_fixes,
    check_passed,
    config_from_project,
    lint_text,
)
from .rules import MEASURABLE_RE, PATTERN_RULES, RULE_BY_ID

__all__ = [
    "DEFAULT_CONFIG",
    "Finding",
    "LintConfig",
    "LintReport",
    "MEASURABLE_RE",
    "PATTERN_RULES",
    "RESIDUAL_WHITELIST",
    "RULE_BY_ID",
    "apply_fixes",
    "check_passed",
    "config_from_project",
    "lint_text",
]
