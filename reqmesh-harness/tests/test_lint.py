"""#25 lint 模块：20 条规则逐条、金样例打分、修正表、收敛、残余白名单、measurable 边界。

全部离线（纯函数）。金样例文本与 spec ⑥ 表一致；打分目标：
G1–G5 == 100（cessna-172 config：passive_voice=false）；G4/G5 默认 config == 98
（passive_voice info 权重 2 —— G5 "is unlatched" 与 G4 "is engaged" 同为 be+过去分词，
spec 仅列举 G4，本测试按规则表语义覆盖两者并注明）。
"""

from __future__ import annotations

import pytest

from reqmesh_harness.ears import derive_name, parse_nl
from reqmesh_harness.lint import (
    DEFAULT_CONFIG,
    MEASURABLE_RE,
    RESIDUAL_WHITELIST,
    apply_fixes,
    check_passed,
    config_from_project,
    lint_text,
)

# 金样例（ubiquitous/event/state/optional/unwanted）
GOLDEN = [
    "The aircraft shall achieve a range of at least 1185 km at maximum cruise power.",
    "When the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning.",
    "While in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level.",
    "Where the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m.",
    "If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s.",
]


def _golden_text(i: int) -> str:
    parsed = parse_nl(GOLDEN[i])
    return f"{derive_name(parsed.response)}\n{parsed.sentence}"


# cessna-172 项目 config（P1 fixture 实测：passive_voice=false、max_words=300）
CESSNA_CONFIG = config_from_project(
    {
        "min_words": 5,
        "max_words": 300,
        "rules": {
            "weak_words": True, "negation": True, "superfluous_infinitive": True,
            "escape_clauses": True, "oblique": True, "purpose_clause": True,
            "passive_voice": False, "vague_quantifiers": True, "pronoun": True,
            "absolute": True, "combinator": True, "temporal_indefinite": True,
            "open_ended": True, "placeholders": True, "abbreviation": True,
            "non_atomic": True, "parentheses": True, "no_obligation": True,
            "untestable": True, "word_count": True,
        },
        "weights": {
            "weak_words": 5, "negation": 4, "superfluous_infinitive": 4,
            "escape_clauses": 6, "oblique": 3, "purpose_clause": 2,
            "passive_voice": 2, "vague_quantifiers": 3, "pronoun": 4,
            "absolute": 4, "combinator": 3, "temporal_indefinite": 4,
            "open_ended": 6, "placeholders": 10, "abbreviation": 2,
            "non_atomic": 5, "parentheses": 2, "no_obligation": 6,
            "untestable": 5, "word_count": 10,
        },
    }
)


# ------------------------------------------------------------------ 金样例打分
def test_golden_scores_100_cessna_config() -> None:
    """G1–G5 在 cessna-172 config 下全部 == 100（spec ⑥；passive_voice 关闭）。"""
    for i in range(5):
        report = lint_text(_golden_text(i), CESSNA_CONFIG)
        assert report.score == 100, (i, [f.rule for f in report.findings])
        assert report.findings == ()


def test_golden_default_config_g4_g5_passive_voice_97() -> None:
    """默认 config 下 G4/G5 触发 passive_voice（info 权重 2）→ 97（上游 floor 公式）。

    - spec ⑥ 仅列举 G4（"is engaged"）；G5 的 "is unlatched" 同为 be+过去分词，
      按规则表语义同样命中（需求会话可确认）；
    - **打分取整（实测偏差②，待需求会话确认）**：spec 判例「G4 默认 98」按 round；
      上游 /quality 用 int(clamped*100//max_penalty)（floor）→ 同为 97。
      本实现取**上游一致公式**（保「本地分 == 服务端分」对全部分数成立），
      断言 97 并把 spec 的 98 判例记入 smoke 记录偏差清单。
    """
    report = lint_text(_golden_text(3), DEFAULT_CONFIG)
    assert [f.rule for f in report.findings] == ["passive_voice"]
    assert report.score == 97
    report = lint_text(_golden_text(4), DEFAULT_CONFIG)
    assert [f.rule for f in report.findings] == ["passive_voice"]
    assert report.score == 97


def test_default_max_penalty_is_90() -> None:
    """默认权重合计 90（spec 事实 3：默认 max_penalty==90）。"""
    assert sum(DEFAULT_CONFIG.weights.values()) == 90
    report = lint_text(_golden_text(0), DEFAULT_CONFIG)
    assert report.max_penalty == 90


# ------------------------------------------------------------------ 规则逐条命中/不命中
@pytest.mark.parametrize(
    "rule,text",
    [
        ("weak_words", "The aircraft should detect a stall."),
        ("negation", "The aircraft shall not permit engine start."),
        ("superfluous_infinitive", "The aircraft shall have the ability to detect a stall."),
        ("escape_clauses", "The aircraft shall detect a stall if practicable."),
        ("oblique", "The aircraft shall use red/green lights."),
        ("oblique", "The aircraft shall use and/or the battery."),
        ("purpose_clause", "The aircraft shall warn so that the pilot is alerted."),
        ("passive_voice", "The alert is displayed by the aircraft."),
        ("vague_quantifier", "The aircraft shall provide several settings."),
        ("pronoun", "The aircraft shall report it."),
        ("absolute", "The aircraft shall always warn."),
        ("combinator", "The aircraft shall warn, however it shall not alert."),
        ("temporal_indefinite", "The aircraft shall respond as soon as possible."),
        ("open_ended", "The aircraft shall provide such as a manual."),
        ("placeholder", "The aircraft shall support TBD configuration."),
        ("abbreviation", "The aircraft shall use e.g. a generator."),
        ("non_atomic", "The aircraft shall warn and record and alert."),
        ("parentheses", "The aircraft shall warn (at the gate)."),
        ("no_obligation", "The aircraft detects a stall."),
        ("untestable", "The aircraft shall provide a manual."),
        ("word_count", "The aircraft shall warn."),
    ],
)
def test_rule_hits(rule: str, text: str) -> None:
    """逐条命中：编写可命中文本并断言规则 id 在 findings 中（负例=金样例零 finding）。"""
    report = lint_text(text, DEFAULT_CONFIG)
    assert rule in {f.rule for f in report.findings}, report.findings


@pytest.mark.parametrize("rule", ["weak_words", "negation", "superfluous_infinitive", "escape_clauses"])
def test_golden_negatives_no_hit(rule: str) -> None:
    """金样例逐一核对（spec ⑥）：G1/G2/G5 不命中这些规则（passive_voice 关闭 config）。"""
    for i in (0, 1, 4):
        report = lint_text(_golden_text(i), CESSNA_CONFIG)
        assert rule not in {f.rule for f in report.findings}


def test_rule_ids_match_public_contract() -> None:
    """20 条规则 id 与 spec 公开契约对齐（唯一性 + 顺序无关）。"""
    from reqmesh_harness.lint import PATTERN_RULES

    ids = [r.id for r in PATTERN_RULES]
    assert len(ids) == len(set(ids)) == 20
    assert set(ids) == {
        "weak_words", "negation", "superfluous_infinitive", "escape_clauses", "oblique",
        "purpose_clause", "passive_voice", "vague_quantifier", "pronoun", "absolute",
        "combinator", "temporal_indefinite", "open_ended", "placeholder", "abbreviation",
        "non_atomic", "parentheses", "no_obligation", "untestable", "word_count",
    }
    # 权重/severity 与 spec 表逐项对齐
    by_id = {r.id: r for r in PATTERN_RULES}
    assert by_id["placeholder"].severity == "error" and by_id["placeholder"].weight == 10
    assert by_id["no_obligation"].severity == "warning" and by_id["no_obligation"].weight == 6
    assert by_id["word_count"].severity == "warning" and by_id["word_count"].weight == 10


# ------------------------------------------------------------------ config 装载与复数键
def test_config_plural_key_mapping() -> None:
    """项目 config 复数键（vague_quantifiers/placeholders）→ 单数 rule id。"""
    cfg = config_from_project({"rules": {"vague_quantifiers": False, "placeholders": False}, "min_words": 5, "max_words": 200})
    assert cfg.rules["vague_quantifier"] is False
    assert cfg.rules["placeholder"] is False
    # 复合：禁用后不再命中
    report = lint_text("The aircraft shall use several settings and support TBD.", cfg)
    rules = {f.rule for f in report.findings}
    assert "vague_quantifier" not in rules
    assert "placeholder" not in rules


def test_config_from_project_fallback_on_garbage() -> None:
    """畸形 config 回落默认（min_words/max_words 钳制）。"""
    cfg = config_from_project({"min_words": "x", "max_words": -5})
    assert cfg.min_words >= 1 and cfg.max_words >= cfg.min_words
    cfg2 = config_from_project(None)
    assert cfg2.rules["weak_words"] is True


def test_word_count_short_warning_and_long_half_penalty() -> None:
    short = lint_text("The aircraft shall warn.", DEFAULT_CONFIG)
    assert any(f.rule == "word_count" and f.severity == "warning" for f in short.findings)
    long = lint_text("The aircraft shall " + "word " * 300 + "within 5 m.", DEFAULT_CONFIG)
    longify = lint_text("The aircraft shall " + "word " * 300, DEFAULT_CONFIG)
    findings = [f for f in long.findings if f.rule == "word_count"]
    assert findings and findings[0].severity == "info"
    # 半罚：word_count（10）→ 5；另含 untestable 5 → 总罚 10 → score 88（floor 88.9）
    assert longify.penalty == 10
    assert longify.score == 88


# ------------------------------------------------------------------ 修正表（6 类）+ 收敛
@pytest.mark.parametrize(
    "source,expected",
    [
        ("The aircraft should detect a stall.", "The aircraft shall detect a stall."),
        ("The aircraft should warn and alert.", "The aircraft shall warn and alert."),  # 情态类修正
        ("The aircraft shall have the ability to detect a stall.", "The aircraft shall detect a stall."),
        ("The aircraft shall be able to detect a stall.", "The aircraft shall detect a stall."),
        ("The aircraft shall be capable of detecting a stall.", "The aircraft shall detect a stall."),
        ("The aircraft shall warn if necessary.", "The aircraft shall warn."),
        ("The aircraft shall warn, if necessary, within 1 s.", "The aircraft shall warn within 1 s."),
        ("The aircraft shall warn as appropriate.", "The aircraft shall warn."),
        ("The aircraft shall use and/or a battery.", "The aircraft shall use or a battery."),
        ("The aircraft shall use e.g. a generator.", "The aircraft shall use for example a generator."),
        ("The aircraft shall use i.e. a generator.", "The aircraft shall use that is a generator."),
        ("The aircraft shall use approx. 20 m.", "The aircraft shall use approximately 20 m."),
        ("The aircraft shall warn (at the gate).", "The aircraft shall warn at the gate."),
        ("The aircraft shall warn [at the gate].", "The aircraft shall warn at the gate."),
    ],
)
def test_fix_table(source: str, expected: str) -> None:
    assert apply_fixes(source) == expected


def test_fix_table_residual_cases_unchanged() -> None:
    """白名单外不可确定修复：形容词类弱词与 3+ 字母斜杠不修（残余）。"""
    assert apply_fixes("The aircraft shall be fast.") == "The aircraft shall be fast."
    assert apply_fixes("The aircraft shall use red/green lights.") == "The aircraft shall use red/green lights."


def test_fix_convergence() -> None:
    """修正幂等：第二次修正文本不再变化（收敛检测依据）。"""
    text = "The aircraft should have the ability to warn (if necessary)."
    once = apply_fixes(text)
    twice = apply_fixes(once)
    assert once == twice
    assert once == "The aircraft shall warn."


def test_fix_loop_integration() -> None:
    """工具内循环等价：初始文本两轮修正后过线（确定性修正语义）。"""
    text = "The aircraft should have the ability to warn (at the gate) if necessary."
    current = text
    for _ in range(3):
        report = lint_text("The aircraft\n" + current, CESSNA_CONFIG)
        if check_passed(report, template="ubiquitous", require_measurable=False, min_score=90)[0]:
            break
        fixed = apply_fixes(current)
        if fixed == current:
            break
        current = fixed
    assert current == "The aircraft shall warn at the gate."
    report = lint_text("The aircraft\n" + current, CESSNA_CONFIG)
    assert check_passed(report, template="ubiquitous", require_measurable=False, min_score=90)[0]


# ------------------------------------------------------------------ 残余白名单与过线
def test_residual_whitelist_unwanted_negation() -> None:
    """unwanted 句式允许携带 negation（EARS 与 R16 固有张力，不反转语义）。"""
    parsed = parse_nl("If the engine fails, then the aircraft shall not start after 2 s.")
    text = f"{derive_name(parsed.response)}\n{parsed.sentence}"
    report = lint_text(text, CESSNA_CONFIG)
    rules = {f.rule for f in report.findings}
    assert "negation" in rules
    # 文本含 "2 s" → 已可度量（无 untestable）；unwanted 残余白名单放行 negation
    assert "untestable" not in rules, rules
    passed, reasons = check_passed(report, template="unwanted", require_measurable=True, min_score=90)
    assert passed, reasons


def test_residual_whitelist_other_templates_reject_negation() -> None:
    """其他句式不允许残余 negation（白名单外 → 未过线）。"""
    parsed = parse_nl("The aircraft shall not start after 2 s.")
    text = f"{derive_name(parsed.response)}\n{parsed.sentence}"
    report = lint_text(text, CESSNA_CONFIG)
    passed, reasons = check_passed(report, template="ubiquitous", require_measurable=True, min_score=90)
    assert passed is False
    assert any("白名单外" in r for r in reasons)


def test_require_measurable_exemption() -> None:
    """require_measurable=false 显式豁免：untestable 降为残余（照常过线）。"""
    parsed = parse_nl("The aircraft shall provide a user manual for the operator.")
    text = f"{derive_name(parsed.response)}\n{parsed.sentence}"
    report = lint_text(text, CESSNA_CONFIG)
    assert "untestable" in {f.rule for f in report.findings}
    assert check_passed(report, template="ubiquitous", require_measurable=True, min_score=90)[0] is False
    assert check_passed(report, template="ubiquitous", require_measurable=False, min_score=90)[0] is True


def test_error_level_blocks_always() -> None:
    """error 级 finding（placeholder）= 硬门槛：过线标准恒不满足。"""
    report = lint_text("The aircraft shall support TBD configuration.", DEFAULT_CONFIG)
    assert any(f.severity == "error" for f in report.findings)
    assert check_passed(report, template="ubiquitous", require_measurable=False, min_score=90)[0] is False


def test_score_threshold_boundary() -> None:
    """分数门槛：90 分界（一个 weak_words→87；两个→82；floor 公式）。

    should 按 spec 表述非义务动词 → 同时触发 weak_words 与 no_obligation
    （-5/-6 与 -10/-6；EARS 渲染句恒含 shall，故不影响 draft_requirement 输出）。
    """
    text_one = "The aircraft should warn within 1 s."
    assert lint_text(text_one, CESSNA_CONFIG).score == 87
    text_two = "The aircraft should warn should alert within 1 s."
    assert lint_text(text_two, CESSNA_CONFIG).score == 82


# ------------------------------------------------------------------ measurable 正则边界
def test_measurable_regex_boundaries() -> None:
    assert MEASURABLE_RE.search("2.5 m/s")
    assert MEASURABLE_RE.search("within 1 s")
    assert MEASURABLE_RE.search("302 km/h")
    assert MEASURABLE_RE.search("1185 km")
    assert MEASURABLE_RE.search("20% of the fleet")
    assert not MEASURABLE_RE.search("10 miles")  # \bm\b 必须排除 miles
    assert not MEASURABLE_RE.search("the aircraft shall reach 20")  # 裸数字无单位
    assert not MEASURABLE_RE.search("a large amount")


def test_no_hit_when_rule_disabled_in_config() -> None:
    cfg = config_from_project({"rules": {"negation": False}})
    report = lint_text("The aircraft shall not start after 2 s.", cfg)
    assert "negation" not in {f.rule for f in report.findings}
