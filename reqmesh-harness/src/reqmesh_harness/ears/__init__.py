"""EARS 句式：五句式解析与渲染（P3 复合技能，纯确定性，无 LLM）。

- 完整支持 Mavin et al. 2009 的 EARS 五句式（ubiquitous/event/unwanted/state/optional）；
- 输入为受控自然语言：标记句（When/If/While/Where + then + shall）或要点行（key: value）；
- 仅接受英文槽位（ASCII 可见字符）：中文等输入 → InputParseError（P5 agent loop 承担翻译）；
- 工具只做槽位抽取与模板渲染，不翻译、不编造内容；
- 渲染统一：句首标记（WHEN/IF/WHILE/WHERE/The）大写 + 句号结尾。

槽位语义（确定性规则）：

- system 槽位一律不带冠词（"aircraft"），渲染时按模板补 "the/The"——句子形式抽取到
  "the aircraft" 时自动归一化；要点形式直接写裸名词。
- 标记句解析：按首个 "shall" 切分 body/response；body 尾部取最后一个
  "the <名词短语>" 作为 system，其余为 condition（删标记/then/尾部逗号）。
- 无标记 body = 整个系统短语（ubiquitous："The <system> shall <response>."）。
- 句子与要点混用取并集，同一槽位值不同 → InputParseError（冲突）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..errors import InputParseError

TEMPLATES = ("ubiquitous", "event", "unwanted", "state", "optional")
AUTO = "auto"

_MARKER_TO_TEMPLATE = {
    "when": "event",
    "if": "unwanted",
    "while": "state",
    "where": "optional",
}
_TEMPLATE_MARKER = {t: m for m, t in _MARKER_TO_TEMPLATE.items()}
_MARKER_RE = re.compile(r"^(when|if|while|where)\b", re.IGNORECASE)

# 要点 key（marker key → 句式；common key → 槽位）
_BULLET_MARKER_KEYS = {
    "when": "event",
    "trigger": "event",
    "if": "unwanted",
    "condition": "unwanted",
    "while": "state",
    "state": "state",
    "where": "optional",
    "feature": "optional",
}
_BULLET_COMMON_KEYS = (
    "system", "response", "name", "type", "priority", "parent", "subject", "id",
)
_BULLET_KEYS = set(_BULLET_MARKER_KEYS) | set(_BULLET_COMMON_KEYS)
_BULLET_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*:\s*(.*)$")

# body 尾部的 "the <名词短语>（≤4 个词）"——系统槽位（取最后一个）
_SYSTEM_RE = re.compile(r"\bthe\s+[a-z][a-z0-9-]*(?:\s+[a-z][a-z0-9-]*){0,3}$", re.IGNORECASE)
_ARTICLE_RE = re.compile(r"^the\s+", re.IGNORECASE)

_RENDER = {
    "ubiquitous": "The {system} shall {response}.",
    "event": "WHEN {condition}, the {system} shall {response}.",
    "unwanted": "IF {condition}, THEN the {system} shall {response}.",
    "state": "WHILE {condition}, the {system} shall {response}.",
    "optional": "WHERE {condition}, the {system} shall {response}.",
}

_EARS_SAMPLE = (
    "单句: The aircraft shall achieve a range of at least 1185 km at maximum cruise power. | "
    "When the indicated airspeed exceeds 302 km/h, the aircraft shall display the overspeed warning. | "
    "If the cabin door is unlatched, then the aircraft shall display a door warning within 1 s. | "
    "要点: response: hold the selected altitude\nwhile: the autopilot is engaged"
)


@dataclass(frozen=True)
class EarsResult:
    """一次解析的产出：渲染句 + 槽位 + 附加字段（要点形式行内覆盖）。"""

    template: str
    sentence: str
    system: str
    condition: str
    response: str
    slots: dict


def _norm_system(value: str) -> str:
    """系统槽位归一化：去定冠词、去首尾空白（渲染时按模板补回冠词）。"""
    text = (value or "").strip()
    m = _ARTICLE_RE.match(text)
    if m:
        text = text[len(m.group(0)):].strip()
    return text


def derive_name(response: str) -> str:
    """name 派生（spec ②）：response 子句首字母大写、截断 80 字符。"""
    text = (response or "").strip()
    if not text:
        return ""
    if text[0].isalpha():
        text = text[0].upper() + text[1:]
    return text[:80]


def render(template: str, *, system: str, condition: str = "", response: str) -> str:
    """按模板渲染 EARS 句子（句首标记大写；句号结尾；槽位已归一化）。"""
    sys_slot = _norm_system(system) or "system"
    cond = (condition or "").strip()
    resp = (response or "").strip()
    if not resp:
        raise InputParseError("response 槽位为空 —— 无法渲染 EARS 句子")
    sentence = _RENDER[template].format(system=sys_slot, condition=cond, response=resp)
    sentence = re.sub(r"\s+", " ", sentence).strip()
    if not sentence.endswith("."):
        sentence += "."
    elif sentence.endswith(".."):
        sentence = sentence[:-1]
    return sentence


def _validate_ascii(text: str) -> None:
    if re.search(r"[^\x20-\x7E\n\t\r]", text):
        raise InputParseError(
            "仅接受英文槽位（ASCII 可见字符）：检测到非 ASCII 字符。中文自然语言的翻译是 "
            "P5 agent loop 的职责（中文会因英文 lint 规则匹配不到而假性满分，违背 quality 闭环目的）。"
            "请改用英文描述，或按要点形式以英文填写槽位。" + _EARS_SAMPLE
        )


def _validate_length(text: str) -> None:
    if len(text) > 2000:
        raise InputParseError(f"nl_text 超长（{len(text)} > 2000 字符）——请拆分或缩短输入。")


def parse_sentence(
    sentence: str, *, template: str = AUTO, system: str | None = None
) -> EarsResult:
    """解析单句（EARS 句子形式）：槽位抽取（确定性，无 LLM）。

    解析失败（无 shall / 标记残缺 / 结构不符）→ InputParseError（含受支持形态示例）。
    """
    if not sentence or not sentence.strip():
        raise InputParseError("nl_text 为空。受支持形态: " + _EARS_SAMPLE)
    _validate_length(sentence)
    _validate_ascii(sentence)
    text = re.sub(r"\s+", " ", sentence).strip()

    m = re.search(r"\bshall\b", text)
    if m is None:
        raise InputParseError(
            "句子缺少义务动词 shall（EARS 句式必须是 '... shall ...'）。受支持形态: " + _EARS_SAMPLE
        )
    body = text[: m.start()].strip()
    response = text[m.end():].strip().rstrip(".")
    if not response:
        raise InputParseError("shall 后缺 response 子句 —— EARS 句式要求 '... shall <response>'。")

    marker_m = _MARKER_RE.match(body)
    detected = _MARKER_TO_TEMPLATE.get(marker_m.group(1).lower()) if marker_m else None
    if template != AUTO:
        if detected is not None and detected != template:
            raise InputParseError(
                f"template={template} 与句子标记 {marker_m.group(1).lower()!r} 不一致 —— 请修正 template 参数或输入"
            )
        t = template
    else:
        t = detected or "ubiquitous"

    if t == "ubiquitous":
        system_slot = _norm_system(body)
        if not system_slot:
            raise InputParseError("ubiquitous 句式缺系统主体 —— 请用 'The <system> shall <response>.' 形式。")
        condition = ""
    else:
        rest = body[marker_m.end():].strip() if marker_m else body
        # unwanted 句型 "..., then the <system> shall ..."：删除 then（系统前）
        rest = re.sub(r"\bthen\s+the\b", "the", rest, flags=re.IGNORECASE)
        sys_m = _SYSTEM_RE.search(rest)
        if sys_m:
            system_slot = _norm_system(sys_m.group(0))
            condition = rest[: sys_m.start()].rstrip(" ,.\t")
        else:
            system_slot = _norm_system(system) if system else "system"
            condition = rest.rstrip(" ,.\t")
        if not condition:
            raise InputParseError(
                f"{t} 句式缺 condition 槽位（{_TEMPLATE_MARKER[t]} 标记后的条件/状态/特性）。受支持形态: " + _EARS_SAMPLE
            )

    return EarsResult(
        template=t,
        sentence=render(t, system=system_slot, condition=condition, response=response),
        system=system_slot,
        condition=condition,
        response=response,
        slots={"template": t, "condition": condition, "system": system_slot, "response": response},
    )


def parse_nl(nl_text: str, *, template: str = AUTO, system: str | None = None) -> EarsResult:
    """自然语言入口：句子形式 / 要点形式 / 混用（并集，同槽位冲突报错）。

    - 要点行：key: value（marker key 决定句式并携带 condition；common key 填槽位）；
    - 混用冲突：同一槽位在两处取值不同 → InputParseError。
    """
    if not isinstance(nl_text, str) or not nl_text.strip():
        raise InputParseError("nl_text 为空。受支持形态: " + _EARS_SAMPLE)
    _validate_length(nl_text)
    _validate_ascii(nl_text)

    bullets: dict[str, str] = {}
    sentence_lines: list[str] = []
    for line in nl_text.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            key = m.group(1).lower()
            if key not in _BULLET_KEYS:
                raise InputParseError(
                    f"要点 key 未知: {key!r} —— 支持 {sorted(_BULLET_KEYS)}。"
                )
            value = m.group(2).strip()
            if not value:
                raise InputParseError(f"要点 {key!r} 的值为空 —— 请提供内容。")
            if key in bullets:
                raise InputParseError(f"要点 key 重复: {key!r} —— 请合并为一行。")
            bullets[key] = value
        elif line.strip():
            sentence_lines.append(line.strip())

    parsed = None
    if sentence_lines:
        parsed = parse_sentence(" ".join(sentence_lines), template=template, system=system)

    # marker key → 句式（多点冲突报错）
    marker_t: str | None = None
    for key in bullets:
        if key in _BULLET_MARKER_KEYS:
            if marker_t is None:
                marker_t = _BULLET_MARKER_KEYS[key]
            elif marker_t != _BULLET_MARKER_KEYS[key]:
                raise InputParseError(f"要点含多个句式标记（{key!r} 与既有 {marker_t}）—— 一次一个句式。")

    if template != AUTO and marker_t is not None and marker_t != template:
        raise InputParseError(f"template={template} 与要点标记（{marker_t}）不一致 —— 请修正。")
    if parsed is not None and marker_t is not None and parsed.template != marker_t:
        raise InputParseError(f"句子标记（{parsed.template}）与要点标记（{marker_t}）冲突 —— 请统一。")

    t = template if template != AUTO else (parsed.template if parsed else None)
    if t is None:
        t = marker_t or "ubiquitous"

    # 槽位合并（混用并集；同值合并、异值冲突）
    def _merge(slot: str, sources: tuple[tuple[str, str], ...]) -> str:
        """从 (来源名, 值) 序列合并单槽位；冲突（不同值）报错。"""
        got: tuple[str, str] | None = None
        for label, value in sources:
            if value is None or value == "":
                continue
            if got is None:
                got = (label, value)
            elif got[1] != value:
                raise InputParseError(
                    f"槽位 {slot!r} 冲突: {got[0]}={got[1]!r} vs {label}={value!r} —— 请统一。"
                )
        return got[1] if got else ""

    sent_condition = parsed.condition if parsed else ""
    marker_values = [v for k, v in bullets.items() if k in _BULLET_MARKER_KEYS]
    condition = _merge("condition", (("句子", sent_condition), ("要点", marker_values[0] if marker_values else "")))
    system = _merge(
        "system",
        (("句子", parsed.system if parsed else ""), ("要点", bullets.get("system", "")), ("参数", system or "")),
    )
    response = _merge(
        "response",
        (("句子", parsed.response if parsed else ""), ("要点", bullets.get("response", ""))),
    )

    if not response:
        raise InputParseError("response 槽位缺失 —— 句子形式需含 shall，要点形式需 response: 行。")
    if not system:
        system = "system"
    else:
        system = _norm_system(system)
    if t != "ubiquitous" and not condition:
        raise InputParseError(
            f"{t} 句式缺 condition 槽位（{_TEMPLATE_MARKER[t]} 后的条件/状态/特性）。"
        )

    sentence = render(t, system=system, condition=condition, response=response)
    slots: dict = {
        "template": t,
        "condition": condition,
        "system": system,
        "response": response,
        "name": bullets.get("name"),
        "type": bullets.get("type"),
        "priority": bullets.get("priority"),
        "parent": bullets.get("parent"),
        "subject": bullets.get("subject"),
        "id": bullets.get("id"),
    }
    return EarsResult(
        template=t, sentence=sentence, system=system,
        condition=condition, response=response, slots=slots,
    )


__all__ = [
    "AUTO", "TEMPLATES", "EarsResult", "derive_name", "parse_nl", "parse_sentence", "render",
]
