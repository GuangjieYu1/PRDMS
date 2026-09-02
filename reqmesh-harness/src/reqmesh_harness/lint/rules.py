"""本地 quality lint 规则表（P3，独立重写）。

许可证边界（spec 事实 3）：reqmesh 为 GPL，本模块不复制上游 regex/权重/message
源码；以下 rule id、severity、weight、INCOSE 引用是「公开契约」（以 spec 表为准，
与上游 _meta.yaml quality 配置键逐项对账），检查模式按 README 行为描述独立实现。
行为等价性由冒烟「本地分 == 服务端分」对账断言保障（G1/G2/G5，无 finding 情形）。

extra 说明（本模块事实，已与 spec 对齐）：

- rule id 是公开契约；config 键存在复数差异：vague_quantifier → vague_quantifiers、
  placeholder → placeholders（spec 事实 3，读取 _meta.yaml quality 时映射）；
- no_obligation 为「倒置检查」实现（无义务动词才命中；config 默认开启）；
- untestable 按 verification_method=test 的回落语义执行（新需求无验证用例时上游
  即按 test 打分——spec 事实 2）；
- 打分公式与上游一致：score = 100 - min(penalty, max_penalty)/max_penalty * 100
  （每次命中按权重累计；word_count 超长按半罚；round 保留整数分——spec 金样例
  G4 默认 config == 98 的判据）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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


# ── 20 条规则（spec 表为契约：id/severity/weight/INCOSE 逐项对齐） ──
PATTERN_RULES: tuple[Rule, ...] = (
    Rule("weak_words", "弱词/模糊措辞", "warning", 5, "R07 Avoid Vague Terms",
         "义务表述用 shall，或直接陈述可度量的属性", pattern=r"\b(?:should|may|might|could|would|appropriate|adequate|sufficient|user-friendly|user friendly|fast|robust|flexible|scalable|easy|simple|simply|easily|normally|typically|generally|usually|reasonable|reasonably)\b"),
    Rule("negation", "否定表述", "warning", 4, "R16 Avoid Not",
         "改述系统应做什么，而不是不做什么", pattern=r"\b(?:shall not|must not|will not|never|not)\b"),
    Rule("superfluous_infinitive", "冗余不定式", "warning", 4, "R11 Superfluous Infinitives",
         "直接陈述需求（shall + 动作）",
         pattern=r"\b(?:have the ability to|be capable of|be designed to|be able to|be used to)\b"),
    Rule("escape_clauses", "豁免从句", "warning", 6, "R08 No Escape Clauses",
         "把条件显式化或删除该从句（不容许供应商自行决定是否履约）",
         pattern=r"\b(?:as far as possible|as far as is possible|as little as possible|as much as possible|where possible|if possible|if necessary|if required|if needed|as needed|as appropriate|as required|if practicable|wherever practical)\b"),
    Rule("oblique", "斜杠歧义", "warning", 3, "R17 Oblique",
         "改用 and 或 or 二选一；斜杠两侧均为 3+ 字母时须拆分",
         pattern=r"\band/or\b|[A-Za-z]{3,}/[A-Za-z]{3,}"),
    Rule("purpose_clause", "目的从句", "info", 2, "R20 Avoid Purpose",
         "直接陈述应满足的行为（不要 so that/in order to）",
         pattern=r"\b(?:with the intent of|in order to|so as to|so that)\b"),
    Rule("passive_voice", "被动语态", "info", 2, "",
         "改用主动语态（the <system> shall ...）",
         pattern=r"\b(?:am|is|are|was|were|be|been|being)\s+(?:\w+(?:ed|en|t)|given|taken|made|set|built|known|shown|found|seen|done|sent|held|left)\b"),
    Rule("vague_quantifier", "模糊量词", "warning", 3, "",
         "用量化值替代模糊量词", config_key="vague_quantifiers",
         pattern=r"\b(?:some|several|many|few|minimal|maximal|enough|sufficient|a lot of|a number of|a few|a couple of)\b"),
    Rule("pronoun", "代词指代", "warning", 4, "R24 Avoid Pronouns",
         "用实体名替代代词（these/their/this/it 等）",
         pattern=r"\b(?:these|those|their|them|they|this|its|she|he|it)\b"),
    Rule("absolute", "绝对化措辞", "warning", 4, "R26 Avoid Absolutes",
         "绝对化用词（always/every/none/all 等）难以验证，改为量化标准",
         pattern=r"\b(?:completely|totally|always|every|never|none|any|all)\b|\b100%\b"),
    Rule("combinator", "组合词", "info", 3, "R19 Avoid Combinators",
         "拆分为独立需求（however/whether/but 等）",
         pattern=r"\b(?:in addition to|as well as|otherwise|meanwhile|however|whether|unless|but)\b"),
    Rule("temporal_indefinite", "时间含糊", "warning", 4, "R35 Temporal Indefinite",
         "给出明确期限或时点（删除 in a timely manner 等）",
         pattern=r"\b(?:in a timely manner|in due course|when convenient|as soon as|eventually|promptly|at last)\b"),
    Rule("open_ended", "开放式结尾", "warning", 6, "R10 Avoid Open-Ended Clauses",
         "关闭列举（avoid such as / and so on / among others）",
         pattern=r"\b(?:including but not limited to|such as|and so on|and so forth|among others)\b|\betc\.?"),
    Rule("placeholder", "占位符", "error", 10, "",
         "占位符不可自动修复（工具绝不编造内容）：请补充内容后重试",
         pattern=r"\b(?:TODO|FIXME|TBD|XXX|HACK)\b|\?\?\?|\?\?"),
    Rule("abbreviation", "缩写", "info", 2, "R38 Avoid Abbreviations",
         "展开为完整词汇（for example / that is / versus 等）",
         pattern=r"\b(?:e\.g\.|i\.e\.|vs\.|approx\.|misc\.|min\.|max\.)"),
    Rule("non_atomic", "非原子语句", "info", 5, "",
         "单句单个 and；多个 and 应拆分为独立需求",
         pattern=r"\band\b.*\band\b"),
    Rule("parentheses", "括号", "info", 2, "R21 Avoid Parentheses",
         "括号内容并入主句或独立成条（避免圆/方括号）",
         pattern=r"\([^()]*\)|\[[^\[\]]*\]"),
    # 倒置检查（无义务动词才命中）——config 默认开启
    Rule("no_obligation", "缺义务动词", "warning", 6, "R01 Structured Statements",
         "需求句须含义务动词（shall/must/will/is required to）", kind="inverted",
         pattern=r"\b(?:is required to|shall|must|will|should|may)\b"),
    # 可度量检查（verification_method=test 的回落语义）
    Rule("untestable", "不可测试", "warning", 5, "",
         "补充可度量数字+单位（如 1185 km、2.5 m/s、1 s）", kind="measurable"),
    # 词数检查
    Rule("word_count", "词数边界", "warning", 10, "",
         "过短则补充完整句子；过长则拆分或精简", kind="count"),
)

RULE_BY_ID: dict[str, Rule] = {r.id: r for r in PATTERN_RULES}

# 可度量数字+单位词表（独立性实现；边界："m/s" 命中、"miles" 不命中；
# 单位末用 (?![a-zA-Z]) 而非 \b——% 与串尾（"20%"）无词边界，但 "miles" 必须排除）
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
    r"\b(?:as far as possible|as far as is possible|as little as possible|as much as possible|"
    r"where possible|if possible|if necessary|if required|if needed|as needed|as appropriate|"
    r"as required|if practicable|wherever practical)\b",
    re.IGNORECASE,
)


def apply_fix_classes(s: str) -> str:
    """确定性修正表（spec ④）：weak_words 情态替换 / superfluous_infinitive /
    escape_clauses / oblique / abbreviation / parentheses。其余规则一律残余。

    返回修正后的文本；无命中时返回原串（调用方据此做收敛检测）。
    """
    # 1) 括号：去括号保留内容（先于 escape——括号内的豁免从句可能依赖此步骤）
    s = re.sub(r"\(([^()]*)\)", lambda m: m.group(1).strip(), s)
    s = re.sub(r"\[([^\[\]]*)\]", lambda m: m.group(1).strip(), s)
    # 2) 豁免从句：删除命中从句（含两侧逗号）；无逗号前缀时删除整段
    s = re.sub(r"\s*,\s*" + _ESCAPE_RE.pattern + r"\s*,", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*,\s*" + _ESCAPE_RE.pattern, "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+" + _ESCAPE_RE.pattern + r"\s*,?", " ", s, flags=re.IGNORECASE)
    # 3) 冗余不定式：have the ability to X → X（X 保留）
    s = re.sub(
        r"\s*(?:have the ability to|be capable of|be designed to|be able to|be used to)\s*",
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
