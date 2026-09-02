"""#26 EARS 模板与 NL 解析：五句式句子形式 + 要点形式 + 混用冲突 + InputParseError 各形态。

全部离线（纯函数，无网络）。金样例文本 G1–G5 来自 spec ⑥（字符级断言）。
"""

from __future__ import annotations

import pytest

from reqmesh_harness.ears import AUTO, derive_name, parse_nl, parse_sentence, render
from reqmesh_harness.errors import InputParseError

# spec ⑥ 金样例表（断言输出逐字符一致）
GOLDEN = [
    (
        "The aircraft shall achieve a range of at least 1185 km at maximum cruise power.",
        "ubiquitous",
        "The aircraft shall achieve a range of at least 1185 km at maximum cruise power.",
    ),
    (
        "When the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning.",
        "event",
        "WHEN the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning.",
    ),
    (
        "While in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level.",
        "state",
        "WHILE in the take-off climb, the aircraft shall maintain a climb rate of at least 2.5 m/s at sea level.",
    ),
    (
        "Where the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m.",
        "optional",
        "WHERE the autopilot is engaged, the aircraft shall hold the selected altitude within 15 m.",
    ),
    (
        "If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s.",
        "unwanted",
        "IF the cabin door is unlatched, THEN the aircraft shall display a door warning within 1 s.",
    ),
]


@pytest.mark.parametrize("src,template,sentence", GOLDEN, ids=lambda v: v[1] if isinstance(v, tuple) else "x")
def test_golden_sentence_render(src, template, sentence) -> None:
    """五句式：标记自动检测（auto）→ EARS 输出与金样例表逐字符一致。"""
    parsed = parse_nl(src)
    assert parsed.template == template
    assert parsed.sentence == sentence


def test_golden_slots() -> None:
    """槽位抽取（system 无冠词；condition/response 按句式）。"""
    g3 = parse_nl(GOLDEN[2][0])
    assert g3.system == "aircraft"
    assert g3.condition == "in the take-off climb"
    assert g3.response == "maintain a climb rate of at least 2.5 m/s at sea level"
    g5 = parse_nl(GOLDEN[4][0])
    assert g5.condition == "the cabin door is unlatched"
    assert g5.system == "aircraft"


def test_explicit_template_override_consistent() -> None:
    """显式 template 与输入标记一致时正常解析（确定性调用）。"""
    parsed = parse_nl(GOLDEN[1][0], template="event")
    assert parsed.template == "event"
    assert parsed.sentence == GOLDEN[1][2]


def test_explicit_template_mismatch_sentence_rejected() -> None:
    """显式 template 与句子标记不一致 → InputParseError（不静默改句式）。"""
    with pytest.raises(InputParseError):
        parse_nl(GOLDEN[4][0], template="event")
    with pytest.raises(InputParseError):
        parse_nl(GOLDEN[1][0], template="unwanted")


def test_explicit_template_requires_condition() -> None:
    """显式非通义句式但缺 condition（标记残缺）→ InputParseError。"""
    with pytest.raises(InputParseError):
        parse_nl("The aircraft shall display a warning.", template="event")


def test_system_parameter_fallback() -> None:
    """句子未检出系统主体（无 the）→ 回落参数 system/默认 the system。"""
    parsed = parse_nl("When the engine fails, the aircraft shall warn the pilot.")
    assert parsed.system == "aircraft"
    parsed = parse_nl("If the gear is up, shall warn the pilot.", system="aircraft")
    assert parsed.system == "aircraft"
    assert parsed.condition == "the gear is up"


# ------------------------------------------------------------------ 要点形式
def test_bullet_marker_keys_cover_five_templates() -> None:
    # marker key（含同义 key）→ 句式
    markers = {
        "when": ("event", "the speed exceeds 302 km/h"),
        "trigger": ("event", "the speed exceeds 302 km/h"),
        "if": ("unwanted", "the door is open"),
        "condition": ("unwanted", "the door is open"),
        "while": ("state", "the aircraft is on the ground"),
        "state": ("state", "the aircraft is on the ground"),
        "where": ("optional", "the autopilot is engaged"),
        "feature": ("optional", "the autopilot is engaged"),
    }
    for key, (tpl, cond) in markers.items():
        parsed = parse_nl(f"{key}: {cond}\nresponse: display the warning")
        assert parsed.template == tpl
        assert parsed.condition == cond
        assert parsed.sentence.startswith(
            {"event": "WHEN", "unwanted": "IF", "state": "WHILE", "optional": "WHERE"}[tpl]
        )


def test_bullet_default_ubiquitous_needs_response() -> None:
    parsed = parse_nl("system: aircraft\nresponse: achieve a range of 1185 km")
    assert parsed.template == "ubiquitous"
    assert parsed.sentence == "The aircraft shall achieve a range of 1185 km."


def test_bullet_response_required() -> None:
    with pytest.raises(InputParseError):
        parse_nl("system: aircraft")


def test_bullet_article_normalized() -> None:
    parsed = parse_nl("system: the aircraft\nresponse: hold the selected altitude")
    assert parsed.sentence == "The aircraft shall hold the selected altitude."
    assert parsed.system == "aircraft"


def test_bullet_common_overrides_extracted() -> None:
    """要点行内覆盖（name/type/priority/parent/subject/id）进入 slots 供字段映射。"""
    parsed = parse_nl(
        "if: the cabin door is unlatched\n"
        "response: display a door warning within 1 s\n"
        "name: Door warning\n"
        "type: safety\n"
        "priority: high\n"
        "parent: ACFT0000\n"
        "subject: cabin door\n"
        "id: SMOKE-P3-001\n"
    )
    assert parsed.slots["name"] == "Door warning"
    assert parsed.slots["type"] == "safety"
    assert parsed.slots["priority"] == "high"
    assert parsed.slots["parent"] == "ACFT0000"
    assert parsed.slots["subject"] == "cabin door"
    assert parsed.slots["id"] == "SMOKE-P3-001"


def test_multiple_marker_keys_conflict() -> None:
    with pytest.raises(InputParseError):
        parse_nl("when: X\nif: Y\nresponse: do Z")


def test_bullet_template_param_mismatch() -> None:
    with pytest.raises(InputParseError):
        parse_nl("if: X\nresponse: do Z", template="event")


# ------------------------------------------------------------------ 混用（并集与冲突）
def test_mixed_union_same_values_ok() -> None:
    parsed = parse_nl(
        "The aircraft shall hold the selected altitude.\nsystem: aircraft\nname: Hold altitude"
    )
    assert parsed.sentence == "The aircraft shall hold the selected altitude."
    assert parsed.system == "aircraft"
    assert parsed.slots["name"] == "Hold altitude"


def test_mixed_conflict_rejected() -> None:
    """同一槽位句子/要点取值不同 → InputParseError（冲突）。"""
    with pytest.raises(InputParseError):
        parse_nl("The aircraft shall hold the selected altitude.\nsystem: autopilot")
    with pytest.raises(InputParseError):
        parse_nl("The aircraft shall hold the selected altitude.\nresponse: do something else")


def test_mixed_sentence_bullet_marker_conflict() -> None:
    with pytest.raises(InputParseError):
        parse_nl("When the speed exceeds 302 km/h, the aircraft shall display the warning.\nif: the door is open\nresponse: warn")


# ------------------------------------------------------------------ InputParseError 形态
def test_chinese_input_rejected() -> None:
    with pytest.raises(InputParseError) as exc:
        parse_nl("飞机应在 2 秒内显示舱门告警")
    assert "ASCII" in str(exc.value) or "英文" in str(exc.value)


def test_no_shall_rejected() -> None:
    with pytest.raises(InputParseError) as exc:
        parse_nl("The aircraft displays a warning.")
    assert "shall" in str(exc.value)


def test_empty_response_rejected() -> None:
    with pytest.raises(InputParseError):
        parse_nl("The aircraft shall.")


def test_unknown_bullet_key_rejected() -> None:
    with pytest.raises(InputParseError) as exc:
        parse_nl("speed: 300\nresponse: warn")
    assert "key" in str(exc.value)


def test_empty_bullet_value_rejected() -> None:
    with pytest.raises(InputParseError) as exc:
        parse_nl("response:")
    assert "空" in str(exc.value)


def test_duplicate_bullet_key_rejected() -> None:
    with pytest.raises(InputParseError):
        parse_nl("response: a\nresponse: b")


def test_too_long_rejected() -> None:
    with pytest.raises(InputParseError) as exc:
        parse_nl("The aircraft shall " + "x " * 2100)
    assert "2000" in str(exc.value)


def test_empty_nl_rejected() -> None:
    with pytest.raises(InputParseError):
        parse_nl("   ")
    with pytest.raises(InputParseError):
        parse_nl("")


def test_system_param_language_and_length_boundary() -> None:
    """system 是 EARS 槽位：非 ASCII / 超长 → InputParseError（spec ② 语言边界）。"""
    with pytest.raises(InputParseError):
        parse_nl("If the gear is up, shall warn the pilot.", system="飞机")
    with pytest.raises(InputParseError):
        parse_nl("If the gear is up, shall warn the pilot.", system="x" * 201)


def test_double_shall_rejected() -> None:
    """response 内第二个 shall → InputParseError（单条约一个义务动词，请拆分）。"""
    with pytest.raises(InputParseError):
        parse_nl("When X shall warn shall alert.")


def test_double_then_normalized() -> None:
    """unwanted 连续 then 吞掉（确定性归一）。"""
    parsed = parse_nl("If X, then then the aircraft shall warn within 1 s.")
    assert parsed.sentence == "IF X, THEN the aircraft shall warn within 1 s."


def test_must_obligation_accepted_and_normalized() -> None:
    """义务位情态（must/will/should/may）被接受——渲染归一为 shall（EARS 规范化）。"""
    parsed = parse_nl("The aircraft must warn within 1 s.")
    assert parsed.sentence == "The aircraft shall warn within 1 s."
    parsed = parse_nl("The aircraft should warn within 1 s.")
    assert parsed.sentence == "The aircraft shall warn within 1 s."
    parsed = parse_nl("When the engine fails, the aircraft will warn within 1 s.")
    assert parsed.template == "event"
    assert parsed.sentence == "WHEN the engine fails, the aircraft shall warn within 1 s."


# ------------------------------------------------------------------ 派生与渲染
def test_derive_name_rules() -> None:
    assert derive_name("display the overspeed warning") == "Display the overspeed warning"
    assert derive_name("A powered system") == "A powered system"  # 首字母已大写
    assert derive_name("") == ""
    long_resp = "a" * 100
    assert len(derive_name(long_resp)) == 80


def test_render_adds_period_and_capitalizes_marker() -> None:
    assert render("event", system="the aircraft", condition="x", response="y") == "WHEN x, the aircraft shall y."
    assert render("unwanted", system="aircraft", condition="c", response="r") == "IF c, THEN the aircraft shall r."
    assert render("ubiquitous", system=" aircraft ", response="do") == "The aircraft shall do."
