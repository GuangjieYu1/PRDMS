"""本地 quality lint 引擎（P3 #25）：规则镜像打分 + 修正表 + 收敛检测 + 残余白名单。

- 打分：score = 100 - min(penalty, max_penalty)/max_penalty * 100（整数 round）；
  penalty 按命中次数累计（word_count 超长半罚）；max_penalty = 全部权重之和
  （与上游 /quality 的 max_penalty=sum(weights) 一致）；
- lint 文本 = name + 换行 + description（与上游 combined 一致；EARS 结构检查是
  二进制 gate，不进打分——见 spec ③）；
- config 装载：项目 config（GET /quality 响应 config 字段）→ 复数键映射 → 失败
  回落默认 config 并标注 config_source="default"（工具层负责采集/标注）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .rules import (
    MEASURABLE_RE,
    PATTERN_RULES,
    RULE_BY_ID,
    apply_fix_classes,
)

DEFAULT_MIN_WORDS = 5
DEFAULT_MAX_WORDS = 200


def default_rules() -> dict[str, bool]:
    return {r.id: True for r in PATTERN_RULES}


def default_weights() -> dict[str, int]:
    return {r.id: r.weight for r in PATTERN_RULES}


@dataclass(frozen=True)
class LintConfig:
    """本地 lint 配置（镜像 /quality 的 config 字段；id 键为公开契约）。

    rules 键 = rule id（vague_quantifier/placeholder——项目 config 的复数键在
    config_from_project 内映射为单数）；weights 同。
    """

    min_words: int = DEFAULT_MIN_WORDS
    max_words: int = DEFAULT_MAX_WORDS
    rules: dict[str, bool] = None  # type: ignore[assignment]
    weights: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if not self.rules:
            object.__setattr__(self, "rules", default_rules())
        if not self.weights:
            object.__setattr__(self, "weights", default_weights())


DEFAULT_CONFIG = LintConfig()

# 项目 config 复数键 → rule id（spec 事实 3；读取 _meta.yaml 时映射）
_CONFIG_KEY_TO_RULE = {
    "vague_quantifiers": "vague_quantifier",
    "placeholders": "placeholder",
}


def config_from_project(raw: dict | None) -> LintConfig:
    """项目 config（/quality 响应 config 字段）→ LintConfig（缺失/异常回落默认）。"""
    raw = raw or {}
    rules = default_rules()
    weights = default_weights()
    for key, value in (raw.get("rules") or {}).items():
        rule_id = _CONFIG_KEY_TO_RULE.get(key, key)
        if rule_id in rules:
            rules[rule_id] = bool(value)
    for key, value in (raw.get("weights") or {}).items():
        rule_id = _CONFIG_KEY_TO_RULE.get(key, key)
        if rule_id in weights:
            try:
                weights[rule_id] = int(value)
            except (TypeError, ValueError):
                continue
    min_words = DEFAULT_MIN_WORDS
    max_words = DEFAULT_MAX_WORDS
    try:
        min_words = int(raw.get("min_words", DEFAULT_MIN_WORDS))
    except (TypeError, ValueError):
        pass  # 单字段畸形仅丢弃该字段，不连带另一合法字段（回退默认，可重复）
    try:
        max_words = int(raw.get("max_words", DEFAULT_MAX_WORDS))
    except (TypeError, ValueError):
        pass
    min_words = max(1, min(min_words, max_words))
    max_words = max(max_words, min_words)
    return LintConfig(min_words=min_words, max_words=max_words, rules=rules, weights=weights)


@dataclass(frozen=True)
class Finding:
    """单条 finding（字段形状对齐上游 /quality：rule/severity/message/start/end）。"""

    rule: str
    severity: str
    message: str
    start: int
    end: int


@dataclass(frozen=True)
class LintReport:
    """一次 lint 的完整结果（含打分与 config 快照）。"""

    score: int
    findings: tuple[Finding, ...]
    penalty: int
    max_penalty: int
    config: dict


def lint_text(text: str, config: LintConfig = DEFAULT_CONFIG) -> LintReport:
    """对 lint 文本（name + "\\n" + description）打分并返回 findings（本地镜像规则集）。"""
    plain = (text or "").strip()
    findings: list[Finding] = []
    penalty = 0
    rules = config.rules
    weights = config.weights
    max_penalty = sum(weights.values())

    def add(rule_id: str, match: str, start: int, end: int) -> None:
        nonlocal penalty
        rule = RULE_BY_ID[rule_id]
        findings.append(Finding(rule_id, rule.severity, rule.message(match), start, end))
        penalty += weights.get(rule_id, rule.weight)

    # 1) pattern 规则（逐条命中/不命中；每次命中一次罚分）
    for rule in PATTERN_RULES:
        if rule.kind != "pattern":
            continue
        if not rules.get(rule.id, True):
            continue
        for m in re.finditer(rule.pattern, plain, re.IGNORECASE):
            add(rule.id, m.group(0), m.start(), m.end())

    # 2) no_obligation：倒置检查（语句无义务动词才命中）
    if rules.get("no_obligation", True):
        rule = RULE_BY_ID["no_obligation"]
        if not re.search(rule.pattern or "", plain, re.IGNORECASE):
            add("no_obligation", "", 0, len(plain))

    # 3) untestable：verification_method=test 回落语义（新需求无验证用例即 test）
    if rules.get("untestable", True):
        if not MEASURABLE_RE.search(plain):
            add("untestable", "", 0, len(plain))

    # 4) word_count：少于 min_words → warning 全额；多于 max_words → info 半罚
    if rules.get("word_count", True):
        n = len(plain.split())
        if n < config.min_words:
            add("word_count", "", 0, len(plain))
        elif n > config.max_words:
            findings.append(
                Finding(
                    "word_count", "info",
                    RULE_BY_ID["word_count"].message(f"{n} 词（上限 {config.max_words}）"),
                    0, len(plain),
                )
            )
            penalty += weights.get("word_count", 10) // 2

    if max_penalty <= 0:
        score = 100
    else:
        # 与上游 /quality 逐字节一致的整数公式（floor；上游 int(clamped*100 // max_penalty)）：
        # clamped = max(0, max_penalty - min(penalty, max_penalty))
        clamped = max(0, max_penalty - min(penalty, max_penalty))
        score = int(clamped * 100 // max_penalty)

    return LintReport(
        score=score,
        findings=tuple(findings),
        penalty=penalty,
        max_penalty=max_penalty,
        config={
            "min_words": config.min_words,
            "max_words": config.max_words,
            "rules": config.rules,
            "weights": config.weights,
        },
    )


# ── 残余 finding 白名单（句式固有，允许过线时携带；spec ④） ──
RESIDUAL_WHITELIST: dict[str, frozenset[str]] = {
    "unwanted": frozenset({"negation"}),  # EARS 与 INCOSE R16 固有张力，不允许反转语义
}


def check_passed(
    report: LintReport,
    *,
    template: str,
    require_measurable: bool,
    min_score: int,
) -> tuple[bool, list[str]]:
    """过线标准（两层，spec ③④）：零 error + score ≥ min_score + 白名单外 findng 检查。

    返回 (passed, 未过线原因列表)——reason 供 hint 构造。
    """
    reasons: list[str] = []
    errors = [f for f in report.findings if f.severity == "error"]
    if errors:
        reasons.append(f"{len(errors)} 个 error 级 finding（{sorted({f.rule for f in errors})}）")
    if report.score < min_score:
        reasons.append(f"score={report.score} < min_score={min_score}")
    allowed = set(RESIDUAL_WHITELIST.get(template, frozenset()))
    if not require_measurable:
        allowed.add("untestable")
    unexpected = [
        f for f in report.findings
        if f.severity in ("warning", "info") and f.rule not in allowed
    ]
    if unexpected:
        reasons.append(f"{len(unexpected)} 个白名单外 warning/info finding（{sorted({f.rule for f in unexpected})}）")
    return (not reasons), reasons


def apply_fixes(text: str) -> str:
    """6 类确定性修正（对传入文本）；未命中时返回原串（收敛检测依据）。"""
    return apply_fix_classes(text)


__all__ = [
    "DEFAULT_CONFIG",
    "Finding",
    "LintConfig",
    "LintReport",
    "RESIDUAL_WHITELIST",
    "check_passed",
    "config_from_project",
    "default_rules",
    "default_weights",
    "lint_text",
    "apply_fixes",
]
