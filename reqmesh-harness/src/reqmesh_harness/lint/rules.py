r"""本地 quality lint 规则表（P3，独立重写——许可证边界）。

reqmesh 为 GPL（见 SPEC「许可证边界」），本模块**不复制**上游
backend/app/services/quality_rules.py 的正则/词表/权重/message 源码。各规则的
独立推导依据（两级公开契约）：

1. **spec 表（docs/specs/p3-nl-requirements.md 事实 3）**：rule id、severity、
   weight、INCOSE 引用、以及规则表逐条列示的**短语/词表**（如 negation 的
   "shall not/must not/will not/never/not"、abbreviation 的 7 个缩写等）——这些
   短语清单本身就是公开契约，逐项采用；
2. **README 行为描述（上游 README「Quality Linting」节）与 INCOSE 摘要表**：
   spec 表以「等」收尾的规则（weak_words/escape_clauses 等），词表在本模块内
   **自行选定**并注明；凡与上游词表不一致处，以行为等价（冒烟对账：本地分 ==
   服务端分，金样例 G1/G2/G5 无 finding 样本）+ 金样例命中/不命中为准。

结构差异声明（与上游可核对）：本模块对「be + 过去分词」用词长门槛（[a-z]{2,}ed
等）而非上游的 \w+(?:ed|en|t) 形式；weak_words 词表按 spec 列示 + 独立补充
（不含 simply/easily/normally/typically/generally/usually/reasonably——那些词的
列入不来自任何公开清单）；no_obligation 按 spec 表「无 shall/must/will/is
required to」实现（**不含** should/may——上游实现含之，本模块以 spec 表述为准，
draft_requirement 渲染句恒含 shall，实际不影响行为）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SEVERITIES = ("error", "warning", "info")


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: str
    weight: int
    incose: str
    hint: str
    kind: str = "pattern"           # pattern | inverted | measurable | count
    pattern: str = ""               # kind=pattern 的正则
    config_key: str = ""            # 与 id 不同时的 _meta.yaml 键（复数差异）

    @property
    def cfg(self) -> str:
        return self.config_key or self.id

    def message(self, match: str) -> str:
        cite = f"（INCOSE {self.incose}）" if self.incose else ""
        return f"{self.title}（rule={self.id}{cite}）: “{match}” —— {self.hint}"


# ── 20 条规则（spec 表为契约：id/severity/weight/INCOSE 逐项对齐；词表见上方说明） ──
PATTERN_RULES: tuple[Rule, ...] = (
    # 弱词：义务情态 + 模糊形容词（spec 列示 + 独立补充）
    Rule("weak_words", "弱词/模糊措辞", "warning", 5, "R07 Avoid Vague Terms",
         "义务表述用 shall，或直接陈述可度量的属性",
         pattern=r"\b(?:should|may|might|could|would|appropriate|adequate|"
                 r"user-friendly|user friendly|fast|robust|flexible|scalable|"
                 r"easy|simple|reasonable|sufficient|acceptable|convenient)\b"),
    # 否定：spec 表列示 5 个短语
    Rule("negation", "否定表述", "warning", 4, "R16 Avoid Not",
         "改述系统应做什么，而不是不做什么",
         pattern=r"\b(?:shall not|must not|will not|never|not)\b"),
    # 冗余不定式：spec 表列示 5 个短语
    Rule("superfluous_infinitive", "冗余不定式", "warning", 4, "R11 Superfluous Infinitives",
         "直接陈述需求（shall + 动作）",
         pattern=r"\b(?:have the ability to|be capable of|be designed to|be able to|be used to)\b"),
    # 豁免从句：spec 表列示 5 个 + 独立补充（常见 escape 短语；上游另含
    # to the extent…/if it should prove necessary 等——本表未纳入，行为等价
    # 边界以冒烟对账与金样例为准）
    Rule("escape_clauses", "豁免从句", "warning", 6, "R08 No Escape Clauses",
         "把条件显式化或删除该从句（不容许供应商自行决定是否履约）",
         pattern=r"\b(?:as far as possible|as little as possible|as much as possible|"
                 r"where possible|if possible|if necessary|if required|if needed|"
                 r"as needed|as appropriate|as required|if practicable|wherever practical)\b"),
    # 斜杠：spec 表「and/or；3+ 字母/3+ 字母」
    Rule("oblique", "斜杠歧义", "warning", 3, "R17 Oblique",
         "改用 and 或 or 二选一；斜杠两侧均为 3+ 字母时须拆分",
         pattern=r"\band/or\b|[A-Za-z]{3,}/[A-Za-z]{3,}"),
    # 目的从句：spec 表列示 4 个短语
    Rule("purpose_clause", "目的从句", "info", 2, "R20 Avoid Purpose",
         "直接陈述应满足的行为（不要 so that/in order to）",
         pattern=r"\b(?:with the intent of|in order to|so as to|so that)\b"),
    # 被动语态：be + 过去分词——spec 表列示过去分词词表 + "-ed 词尾"；
    # 本模块以「词长门槛 + 词表」形式实现（与上游 \w+(?:ed|en|t) 形式不同）
    Rule("passive_voice", "被动语态", "info", 2, "",
         "改用主动语态（the <system> shall ...）",
         pattern=r"\b(?:am|is|are|was|were|be|been|being)\s+"
                 r"(?:[a-z]{2,}ed|[a-z]{2,}en|[a-z]{2,}t|given|taken|made|set|built|"
                 r"known|shown|found|seen|done|sent|held|left)\b"),
    # 模糊量词：spec 表列示；config 键复数差异（vague_quantifiers）
    Rule("vague_quantifier", "模糊量词", "warning", 3, "",
         "用量化值替代模糊量词", config_key="vague_quantifiers",
         pattern=r"\b(?:some|several|many|few|minimal|maximal|enough|sufficient|"
                 r"a lot of|a number of|a few|a couple of)\b"),
    # 代词：spec 表列示
    Rule("pronoun", "代词指代", "warning", 4, "R24 Avoid Pronouns",
         "用实体名替代代词（these/their/this/it 等）",
         pattern=r"\b(?:these|those|their|them|they|this|its|she|he|it)\b"),
    # 绝对化：spec 表列示 + 100%
    Rule("absolute", "绝对化措辞", "warning", 4, "R26 Avoid Absolutes",
         "绝对化用词（always/every/none/all 等）难以验证，改为量化标准",
         pattern=r"\b(?:completely|totally|always|every|never|none|any|all)\b|\b100%\b"),
    # 组合词：spec 表列示
    Rule("combinator", "组合词", "info", 3, "R19 Avoid Combinators",
         "拆分为独立需求（however/whether/but 等）",
         pattern=r"\b(?:in addition to|as well as|otherwise|meanwhile|however|whether|unless|but)\b"),
    # 时间含糊：spec 表列示
    Rule("temporal_indefinite", "时间含糊", "warning", 4, "R35 Temporal Indefinite",
         "给出明确期限或时点（删除 in a timely manner 等）",
         pattern=r"\b(?:in a timely manner|in due course|when convenient|"
                 r"as soon as|eventually|promptly|at last)\b"),
    # 开放式结尾：spec 表列示（and so forth 为独立补充）
    Rule("open_ended", "开放式结尾", "warning", 6, "R10 Avoid Open-Ended Clauses",
         "关闭列举（avoid such as / and so on / among others）",
         pattern=r"\b(?:including but not limited to|such as|and so on|and so forth|"
                 r"among others)\b|\betc\.?"),
    # 占位符：spec 表列示；唯一 error 级（硬门槛，工具绝不自动修复）
    Rule("placeholder", "占位符", "error", 10, "",
         "占位符不可自动修复（工具绝不编造内容）：请补充内容后重试",
         pattern=r"\b(?:TODO|FIXME|TBD|XXX|HACK)\b|\?\?\?|\?\?"),
    # 缩写：spec 表列示 7 个
    Rule("abbreviation", "缩写", "info", 2, "R38 Avoid Abbreviations",
         "展开为完整词汇（for example / that is / versus 等）",
         pattern=r"\b(?:e\.g\.|i\.e\.|vs\.|approx\.|misc\.|min\.|max\.)"),
    # 非原子：spec 表「单句两个 and」
    Rule("non_atomic", "非原子语句", "info", 5, "",
         "单句单个 and；多个 and 应拆分为独立需求",
         pattern=r"\band\b.*\band\b"),
    # 括号：spec 表「圆/方括号内容」
    Rule("parentheses", "括号", "info", 2, "R21 Avoid Parentheses",
         "括号内容并入主句或独立成条（避免圆/方括号）",
         pattern=r"\([^()]*\)|\[[^\[\]]*\]"),
    # 倒置检查（无义务动词才命中）——spec 表：「无 shall/must/will/is required to」
    Rule("no_obligation", "缺义务动词", "warning", 6, "R01 Structured Statements",
         "需求句须含义务动词（shall/must/will/is required to）", kind="inverted",
         pattern=r"\b(?:is required to|shall|must|will)\b"),
    # 可度量检查（verification_method=test 的回落语义）——单位词表按 spec 类别
    # （百分比/时间/字节/频率/长度/质量/温度）自列
    Rule("untestable", "不可测试", "warning", 5, "",
         "补充可度量数字+单位（如 1185 km、2.5 m/s、1 s）", kind="measurable"),
    # 词数检查
    Rule("word_count", "词数边界", "warning", 10, "",
         "过短则补充完整句子；过长则拆分或精简", kind="count"),
)

RULE_BY_ID: dict[str, Rule] = {r.id: r for r in PATTERN_RULES}

# 可度量数字+单位词表（按 spec 类别自列：百分比/时间/字节/存储/频率/速率/像素/
# 长度/质量/温度；边界："m/s" 命中、"miles" 不命中——用 (?![a-zA-Z]) 而非 \b，
# 因 % 与串尾（"20%"）无词边界）
MEASURABLE_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|percent|ms|s|sec|seconds?|minutes?|hours?|"
    r"days?|weeks?|months?|years?|bytes?|KB|MB|GB|TB|Hz|kHz|MHz|GHz|bps|fps|px|"
    r"mm|cm|m|km|g|kg|lb|°C|°F)(?![a-zA-Z])",
    re.IGNORECASE,
)

# ── 确定性修正表（6 类；仅此 6 类，语义性修复是 P5 LLM 的事） ──
_ABBREVIATION_MAP = {
    "e.g.": "for example",
    "i.e.": "that is",
    "vs.": "versus",
    "approx.": "approximately",
    "misc.": "miscellaneous",
    "min.": "minimum",
    "max.": "maximum",
}
_ABBREVIATION_RE = re.compile(r"\b(e\.g\.|i\.e\.|vs\.|approx\.|misc\.|min\.|max\.)", re.IGNORECASE)
_ESCAPE_RE = re.compile(
    r"\b(?:as far as possible|as little as possible|as much as possible|"
    r"where possible|if possible|if necessary|if required|if needed|as needed|"
    r"as appropriate|as required|if practicable|wherever practical)\b",
    re.IGNORECASE,
)


def _ungerund(stem: str) -> str:
    """动名词→动词原形的最小确定性规则（仅用于 "be capable of X" 修正，X 为 gerund）。

    - "detecting" → "detect"（去 ing）；"running" → "run"（双写辅音塌缩）；
    - 形态学完整处理（ie→y 等）超出 P3 确定性范围——未覆盖形态以原文保留（残余）。
    """
    if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1].lower() not in "aeiou":
        return stem[:-1]  # 双写辅音塌缩（"running" → "run"）；长元音（"seeing"→"see"）不塌缩
    return stem


def apply_fix_classes(s: str) -> str:
    """确定性修正表（spec ④）：weak_words 情态替换 / superfluous_infinitive /
    escape_clauses / oblique / abbreviation / parentheses。其余规则一律残余。

    返回修正后的文本；无命中时返回原串（调用方据此做收敛检测）。
    """
    # 0) "be capable of <gerund>" 特殊形态：删除短语并把 gerund 归一为原形
    #    （"shall be capable of detecting X" → "shall detect X"；其余三短语 X 为原形直接删除）
    s = re.sub(
        r"\s*be capable of\s+(([a-z]+?)ing)\b",
        lambda m: " " + _ungerund(m.group(2)) + " ",
        s, flags=re.IGNORECASE,
    ).replace("  ", " ")
    # 1) 括号：去括号保留内容（先于 escape——括号内的豁免从句可能依赖此步骤）
    s = re.sub(r"\(([^()]*)\)", lambda m: m.group(1).strip(), s)
    s = re.sub(r"\[([^\[\]]*)\]", lambda m: m.group(1).strip(), s)
    # 2) 豁免从句：删除命中从句（含两侧逗号）；无逗号前缀时删除整段
    s = re.sub(r"\s*,\s*" + _ESCAPE_RE.pattern + r"\s*,", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*,\s*" + _ESCAPE_RE.pattern, "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+" + _ESCAPE_RE.pattern + r"\s*,?", " ", s, flags=re.IGNORECASE)
    # 3) 冗余不定式：have the ability to X → X（X 保留；be capable of 已在步骤 0 处理 gerund）
    s = re.sub(
        r"\s*(?:have the ability to|be designed to|be able to|be used to)\s*",
        " ", s, flags=re.IGNORECASE,
    )
    # 4) 弱词情态：should/might/could/would → shall（形容词类命中不修 → 残余）
    s = re.sub(
        r"\b(should|might|could|would)\b",
        lambda m: ("Shall" if m.group(1)[0].isupper() else "shall"),
        s, flags=re.IGNORECASE,
    )
    # 5) 斜杠：and/or → or（A/B 类 3+ 字母斜杠不拆 → 残余）
    s = re.sub(r"\band/or\b", "or", s, flags=re.IGNORECASE)
    # 6) 缩写：展开字典
    s = re.sub(
        _ABBREVIATION_RE.pattern,
        lambda m: _ABBREVIATION_MAP[m.group(1).lower()],
        s, flags=re.IGNORECASE,
    )
    # 归一化空格并去首尾；删除从句后修复标点前残留空格（"warn ." → "warn."）
    s = re.sub(r"\s+([.,;:?!])", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()
