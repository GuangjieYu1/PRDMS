"""P6 evals 黄金任务集：任务定义 = 数据（期望工具序列 + 参数匹配器 + 最终状态断言 + 审计期望）。

spec p6-delivery.md 决策①/验收 1–3（入口 docs/handoffs/p6-delivery.md）：

- 5 个黄金任务 G1–G5（≥1 每旗舰能力 + 审批拒绝路径 + P5 run 任务）；
- 断言只测外部行为：executor 实际执行的调用 == 期望序列、写负载形状、审计行、读回响应
  （P1–P5 同款口径）；不测内部实现；
- 零复制裁决逻辑：全部经 registry.call / run_task（审批门/审计/白名单唯一事实源），
  evals/ 不进 pytest 集合（离线基线 533 计数不变，spec 验收 12）；
- 离线（run_offline.py，respx + FakeProvider，零网络）与 live（run_live.py，DSH 委托路线，
  network-tagged）共享同一任务定义；G5 仅离线（P5 live 已由 smoke_p5 B 段覆盖）。

术语（CONTEXT.md）：harness 侧运行时会话称 run；下文「run 日志」即 run.jsonl（P5 ⑤）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from reqmesh_harness.runtime.fake import EndStep, FakeStep, QuestionStep, TextStep, ToolStep
from reqmesh_harness.runtime.provider import Question

PROJECT_ID = "cessna-172"

# 残渣 id（live 约定，spec 验收 3）：G1 = 落库需求 id；G3 = 追踪链接 target 前缀
SMOKE_ID_G1 = "SMOKE-EVAL-P6-G1"
SMOKE_ID_G4 = "SMOKE-EVAL-P6-G4"
SMOKE_LINK_G3 = "SMOKE-EVAL-P6-G3"

# G1/G5 金样例 EARS 句（P5 B 段同款，本地 lint 过线确定）
EARS_SENTENCE = (
    "When the landing gear is down and locked, the aircraft shall display "
    "a gear-down indication within 1 s."
)
# EARS 渲染归一：时间状语关键字按句式大写（P3 契约；落库 description = 渲染句）
EARS_NORMALIZED = EARS_SENTENCE.replace("When", "WHEN", 1)

HTTP_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "http"


def fixture(name: str) -> Any:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 参数匹配器（数据化定义）
class Wildcard:
    """任意值匹配（匹配器语义：除字面量精确相等外的全部放行）；实例 = ANY。"""

    def __repr__(self) -> str:
        return "<any>"


ANY = Wildcard()


@dataclass(frozen=True)
class Matcher:
    """谓词匹配器（描述 + 判定函数；任务定义数据化的部分：值域 = 字面量 | ANY | Matcher）。"""

    describe: str
    fn: Callable[[Any], bool]

    def __call__(self, value: Any) -> bool:
        return self.fn(value)

    def __repr__(self) -> str:
        return f"<matches {self.describe}>"


def matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, Wildcard):
        return True
    if isinstance(expected, Matcher):
        return expected.fn(actual)
    return expected == actual


@dataclass(frozen=True)
class ExpectedCall:
    """期望工具调用：name 精确 + args 子集匹配（仅检查列出的键；值域见模块文档）。"""

    name: str
    args: dict[str, Any] | None = None


@dataclass(frozen=True)
class AuditRow:
    """审计期望（字段按 P2 version=1；decision/tool 必查，level/result 可选）。"""

    decision: str
    tool: str
    level: str | None = None
    result: str | None = None


# ------------------------------------------------------------------ Eval 上下文（离线/live）
@dataclass
class EvalEnv:
    """一次 eval 的环境（离线：respx 路由范围仍打开时可断言 router.calls）。"""

    router: Any = None
    settings: Any = None
    registry: Any = None
    recorder: Any = None
    sink: Any = None  # RecordingSink：event 列表（tool_call/tool_result/question/…）
    db: dict[str, Any] = field(default_factory=dict)
    run: Any = None
    # live 专用
    dsh_url: str = ""
    dsh_session_ids: list[str] = field(default_factory=list)
    dsh_counts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GoldenTask:
    """黄金任务：数据 + 断言钩子（setup/final_state 属断言代码，不含裁决逻辑）。"""

    id: str
    capability: str
    steps: list[FakeStep]
    expected_calls: list[ExpectedCall]
    audit: list[AuditRow]
    # 离线钩子
    setup: Callable[[EvalEnv], None]
    final_state: Callable[[EvalEnv], None]
    run_confirmation: bool = False  # True = ConfirmedToolExecutor + ConfirmationRelay（auto_yes）
    # live 钩子（G5 仅离线）
    live: bool = False
    live_task: str = ""
    live_expected_names: list[str] = field(default_factory=list)
    live_audit: list[AuditRow] = field(default_factory=list)
    live_final_state: Callable[[EvalEnv], None] | None = None
    live_residue: list[str] = field(default_factory=list)


# ================================================================== G1 NL 建需求（P3 旗舰①）
def _setup_g1(env: EvalEnv) -> None:
    from httpx import Response

    from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore

    # DRAFT 白名单：project 可省略（= 通配全部项目，P2 规则）
    WhitelistStore(env.settings.resolved_approvals_file()).append(
        WhitelistEntry(tool="draft_requirement")
    )

    quality = fixture("report_quality.json")
    # /quality 双职：① lint config（项目 config_source）② get_requirement_quality 回读
    # 目标需求 score=95（≥ REQMESH_LINT_MIN_SCORE=90 过线语义，spec 验收 2 点检）
    quality = {
        **quality,
        "per_requirement": [
            {"id": SMOKE_ID_G1, "name": "Gear-down indication", "score": 95, "findings": []}
        ],
    }
    env.db["quality"] = quality
    env.db["created"] = None

    def capture(request) -> Response:
        body = json.loads(request.content)
        env.db["created"] = dict(body)
        return Response(201, json=dict(body))

    env.router.get("/api/projects/cessna-172/quality").mock(return_value=Response(200, json=quality))
    env.router.post("/api/projects/cessna-172/requirements").mock(side_effect=capture)
    env.router.get("/api/projects/cessna-172/requirements/{}".format(SMOKE_ID_G1)).mock(
        side_effect=lambda request: Response(200, json=env.db["created"])
    )


def _final_g1(env: EvalEnv) -> None:
    def call_text(seq: int) -> dict:
        rec = env.sink.tool_records[seq]
        assert rec is not None, f"G1 缺少第 {seq} 次工具结果"
        return json.loads(rec["text"])

    # ① 落库实体：description 与 EARS 句相等、status=proposed、id 为残渣约定
    created = env.db["created"]
    assert created is not None, "G1 写路径未发出 POST（落库失败）"
    assert created["description"] == EARS_NORMALIZED, created["description"]
    assert created["status"] == "proposed", created["status"]
    assert created["id"] == SMOKE_ID_G1, created["id"]
    # ② get_requirement 回读 == 落库实体（stub 回声，写负载形状断言）
    readback = call_text(2)
    assert readback["description"] == EARS_NORMALIZED and readback["status"] == "proposed"
    # ③ get_requirement_quality：score ≥ lint 线（settings.lint_min_score=90）
    quality = call_text(1)
    assert quality["id"] == SMOKE_ID_G1, quality
    assert quality["score"] == 95 and quality["score"] >= env.settings.lint_min_score, quality
    # ④ 只读回读零写：唯一非 GET 请求 = 落库 POST（之外无隐藏写路径）
    non_get = [c for c in env.router.calls if c.request.method != "GET"]
    assert len(non_get) == 1 and non_get[0].request.method == "POST", [
        c.request.method for c in env.router.calls
    ]


G1 = GoldenTask(
    id="G1",
    capability="P3 旗舰① 自然语言建需求（EARS + lint 闭环 + 落库）",
    steps=[
        ToolStep(
            "draft_requirement",
            {
                "project_id": PROJECT_ID,
                "nl_text": EARS_SENTENCE,
                "id": SMOKE_ID_G1,
                "template": "auto",
            },
        ),
        ToolStep("get_requirement_quality", {"project_id": PROJECT_ID, "req_id": SMOKE_ID_G1}),
        ToolStep("get_requirement", {"project_id": PROJECT_ID, "req_id": SMOKE_ID_G1}),
        EndStep("completed", "G1 需求已建库并回读。"),
    ],
    expected_calls=[
        ExpectedCall("draft_requirement", {"project_id": PROJECT_ID, "id": SMOKE_ID_G1}),
        ExpectedCall("get_requirement_quality", {"project_id": PROJECT_ID, "req_id": SMOKE_ID_G1}),
        ExpectedCall("get_requirement", {"project_id": PROJECT_ID, "req_id": SMOKE_ID_G1}),
    ],
    audit=[AuditRow("approved", "draft_requirement", "DRAFT", "ok")],
    setup=_setup_g1,
    final_state=_final_g1,
    live=True,
    live_task=(
        f"用自然语言给 {PROJECT_ID} 建一条需求：{EARS_SENTENCE}"
        f"（id 用 {SMOKE_ID_G1}，project {PROJECT_ID}）"
    ),
    live_expected_names=["draft_requirement", "get_requirement"],
    live_audit=[AuditRow("denied", "draft_requirement"), AuditRow("approved", "draft_requirement")],
    live_final_state=lambda env: _live_g1(env),
    live_residue=[SMOKE_ID_G1],
)


def _live_g1(env: EvalEnv) -> None:
    req = env.registry.call("get_requirement", project_id=PROJECT_ID, req_id=SMOKE_ID_G1)
    description = (req.get("description") or "")
    # EARS 渲染归一（WHEN 关键字大写）：主断言 = casefold 归一后逐字相等（覆盖关键字大小写归一）；
    # 兜底 = 精确子串——live 回读的 description 可能被上游包一层 HTML 包装（P1 fixture 形态），
    # 子串命中即语义满足（离线侧已有逐字精确断言，见 _final_g1）。
    assert (
        description.casefold() == EARS_NORMALIZED.casefold()
        or EARS_SENTENCE in description
    ), req
    assert req.get("status") == "proposed", req
    calls = [e["name"] for e in env.sink.events if e["kind"] == "tool_call"]
    drafts = [n for n in calls if n == "draft_requirement"]
    assert len(drafts) == 2, calls  # denied → 确认 → approved 重试（B 段同款序列）
    results = [e for e in env.sink.events if e["kind"] == "tool_result"]
    denied = [e for e in results if e["name"] == "draft_requirement" and e["ok"] is False]
    assert len(denied) == 1 and "ApprovalDeniedError" in denied[0]["text"], denied


# ================================================================== G2 追踪/覆盖缺口报告（P4 旗舰②）
_SIX_SOURCES = {
    "/api/projects/cessna-172/coverage": "coverage.json",
    "/api/projects/cessna-172/gap-analysis": "gap_analysis.json",
    "/api/projects/cessna-172/traces": "traces.json",
    "/api/projects/cessna-172/suspect-links": "suspect_links.json",
    "/api/projects/cessna-172/unreviewed": "unreviewed.json",
    "/api/projects/cessna-172/allocation-matrix": "allocation_matrix.json",
}


def _mock_six(env: EvalEnv) -> None:
    from httpx import Response

    for path, name in _SIX_SOURCES.items():
        env.router.get(path).mock(return_value=Response(200, json=fixture(name)))


def _setup_g2(env: EvalEnv) -> None:
    _mock_six(env)
    env.db["golden"] = fixture("report_golden.json")


def _final_g2(env: EvalEnv) -> None:
    # 报告结构：summary/gaps 非空 + P4 golden 基线点检（确定性 re-run，同 stubs 必同形）
    golden = env.db["golden"]
    report = env.registry.call("get_traceability_gap_report", project_id=PROJECT_ID)
    assert report["project_id"] == PROJECT_ID
    assert report["generated_at"]
    assert report["summary"] == golden["summary"], "summary 与 P4 golden 漂移"
    assert report["meta"] == golden["meta"], "meta 与 P4 golden 漂移"
    assert report["chapters"] == golden["chapters"], "chapters 与 P4 golden 漂移"
    assert [g["id"] for g in report["gaps"]] == [g["id"] for g in golden["gaps"]]
    assert report["summary"]["requirements_total"] > 0 and report["gaps"], "summary/gaps 非空"
    gap_ids = {g["id"] for g in report["gaps"]}
    assert "AFRM0000" in gap_ids, "P4 golden 基线点检：AFRM0000 缺口缺失（live 另点检 SMOKE-P2-001）"
    # 零副作用：全程 GET（登录不在本 eval——会话文件预置）
    assert {c.request.method for c in env.router.calls} <= {"GET"}, [
        (c.request.method, c.request.url.path) for c in env.router.calls
    ]


G2 = GoldenTask(
    id="G2",
    capability="P4 旗舰② 追踪/覆盖缺口报告（六源聚合 + golden 基线点检）",
    steps=[
        ToolStep("get_traceability_gap_report", {"project_id": PROJECT_ID}),
        EndStep("completed", "G2 报告已生成。"),
    ],
    expected_calls=[ExpectedCall("get_traceability_gap_report", {"project_id": PROJECT_ID})],
    audit=[],
    setup=_setup_g2,
    final_state=_final_g2,
    live=True,
    live_task=f"读取 {PROJECT_ID} 的追踪/覆盖缺口报告（get_traceability_gap_report）。",
    live_expected_names=["get_traceability_gap_report"],
    live_audit=[],
    live_final_state=lambda env: _live_g2(env),
    live_residue=[],
)


def _live_g2(env: EvalEnv) -> None:
    report = env.registry.call("get_traceability_gap_report", project_id=PROJECT_ID)
    assert report["summary"]["requirements_total"] > 0 and report["gaps"], "summary/gaps 非空"
    gap_ids = {g["id"] for g in report["gaps"]}
    # P4 golden 口径点检（live 六源基线；离线侧仅 AFRM0000 — 见 _final_g2）
    assert "SMOKE-P2-001" in gap_ids or "AFRM0000" in gap_ids, gap_ids
    # 全 READ：零审计新增（live_audit == [] 由 runner 断言，此处只断自身形状）
    assert report["chapters"] and report["summary"]["coverage"]["total"] > 0, report["summary"]


# ================================================================== G3 追踪维护（P2 追踪域）
_TRACES = None  # lazy（fixture 读取一次）


def _traces_old() -> list[dict[str, str]]:
    global _TRACES
    if _TRACES is None:
        _TRACES = list(fixture("traces.json")["links"])
    return _TRACES


NEW_LINK_G3 = {"source": "ACFT0000", "target": SMOKE_LINK_G3, "type": "refines"}


def _setup_g3(env: EvalEnv) -> None:
    from httpx import Response

    from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore

    old = _traces_old()
    env.db["matrix"] = list(old)
    env.db["put_body"] = None

    def put(request) -> Response:
        body = json.loads(request.content)
        env.db["put_body"] = body["links"]
        env.db["matrix"] = list(body["links"])
        return Response(200, json={"links": env.db["matrix"]})

    env.router.get("/api/projects/cessna-172/traces").mock(
        side_effect=lambda request: Response(200, json={"links": env.db["matrix"]})
    )
    env.router.put("/api/projects/cessna-172/traces").mock(side_effect=put)
    # MUTATE 白名单：tool + 具体 project（P2 不允许通配条目）
    WhitelistStore(env.settings.resolved_approvals_file()).append(
        WhitelistEntry(tool="set_relations", project=PROJECT_ID)
    )


def _link_keys(links: list[Any]) -> list[tuple[str, str, str]]:
    return [(l["source"], l["target"], l["type"]) for l in links]


def _final_g3(env: EvalEnv) -> None:
    old = _traces_old()
    put_body = env.db["put_body"]
    assert put_body is not None, "set_relations 未发出 PUT（读-改-写回放缺失）"
    # ① 写负载形状：旧链接全部保留 + 新链接追加（读-改-写回放）
    assert _link_keys(put_body) == _link_keys(old) + [
        (NEW_LINK_G3["source"], NEW_LINK_G3["target"], NEW_LINK_G3["type"])
    ], f"put_body 与期望矩阵不一致: {_link_keys(put_body)}"
    # ② 新链接回读可见（执行器文本 = GET 响应形状）
    readback = json.loads(env.sink.tool_records[2]["text"])
    keys = _link_keys(readback["links"])
    assert keys == _link_keys(old) + [
        (NEW_LINK_G3["source"], NEW_LINK_G3["target"], NEW_LINK_G3["type"])
    ], keys
    # ③ 写路径外形：恰 1 个 PUT（追踪矩阵），其余 GET
    writes = [c for c in env.router.calls if c.request.method != "GET"]
    assert len(writes) == 1 and writes[0].request.method == "PUT", [
        (c.request.method, c.request.url.path) for c in env.router.calls
    ]


G3 = GoldenTask(
    id="G3",
    capability="P2 追踪域 MUTATE（get_traces → set_relations 读-改-写回放）",
    steps=[
        ToolStep("get_traces", {"project_id": PROJECT_ID}),
        ToolStep(
            "set_relations",
            {
                "project_id": PROJECT_ID,
                "links": _traces_old() + [NEW_LINK_G3],
                "reason": "P6 eval G3",
            },
        ),
        ToolStep("get_traces", {"project_id": PROJECT_ID}),
        EndStep("completed", "G3 追踪矩阵已更新并回读。"),
    ],
    expected_calls=[
        ExpectedCall("get_traces", {"project_id": PROJECT_ID}),
        ExpectedCall("set_relations", {"project_id": PROJECT_ID, "reason": "P6 eval G3"}),
        ExpectedCall("get_traces", {"project_id": PROJECT_ID}),
    ],
    audit=[AuditRow("approved", "set_relations", "MUTATE", "ok")],
    setup=_setup_g3,
    final_state=_final_g3,
    live=True,
    live_task=(
        f"先读取 {PROJECT_ID} 的追踪矩阵（get_traces），然后为需求 ACFT0000 追加一条指向 "
        f"{SMOKE_LINK_G3} 的 refines 链接：用 set_relations 读-改-写回放（保留全部既有链接，"
        "不要丢弃旧链接）。"
    ),
    live_expected_names=["get_traces", "set_relations", "get_traces"],
    live_audit=[AuditRow("denied", "set_relations"), AuditRow("approved", "set_relations")],
    live_final_state=lambda env: _live_g3(env),
    live_residue=[SMOKE_LINK_G3],
)


def _live_g3(env: EvalEnv) -> None:
    matrix = env.registry.call("get_traces", project_id=PROJECT_ID)
    keys = _link_keys(matrix["links"])
    # 新链接可见 + 既有旧链接（ACFT0000→AFRM0000 refines 等）保留
    assert any(k[2] == "refines" and k[1].startswith(SMOKE_LINK_G3) for k in keys), keys
    assert ("ACFT0000", "AFRM0000", "refines") in keys, keys
    calls = [e["name"] for e in env.sink.events if e["kind"] == "tool_call"]
    writes = [n for n in calls if n == "set_relations"]
    assert len(writes) == 2, calls  # denied → 确认 → approved 重试


# ================================================================== G4 审批拒绝路径（P2 审批门）
def _setup_g4(env: EvalEnv) -> None:
    # 空白名单（fail-closed 的 trivial 情形）：不写 approvals 文件
    env.db["approvals_before"] = (
        env.settings.resolved_approvals_file().read_bytes()
        if env.settings.resolved_approvals_file().exists()
        else None
    )


def _final_g4(env: EvalEnv) -> None:
    assert len(env.sink.tool_records) == 1, f"G4 工具结果记录数 != 1: {len(env.sink.tool_records)}"
    deny = env.sink.tool_records[0]
    # ① 拒绝错误文本：ApprovalDeniedError + fix_hint（approvals add 命令）
    assert deny["ok"] is False, deny
    assert "ApprovalDeniedError" in deny["text"], deny["text"]
    # DRAFT 层 fix_hint 形态（gate.py _deny：project 可省略=通配——G4 按 spec 验收 2 断言 approvals add 命令）
    assert "reqmesh-harness approvals add create_requirement" in deny["text"]
    assert "修复建议" in deny["text"], deny["text"]
    # ② 库状态零变化：零 HTTP（裁决在请求之前——审批门 fail-closed 的唯一裁决源语义）
    assert list(env.router.calls) == [], [
        (c.request.method, c.request.url.path) for c in env.router.calls
    ]
    # ③ 白名单文件未被修改
    path = env.settings.resolved_approvals_file()
    after = path.read_bytes() if path.exists() else None
    assert after == env.db["approvals_before"], "白名单文件被拒绝路径修改"


G4 = GoldenTask(
    id="G4",
    capability="P2 审批门拒绝路径（空白名单 fail-closed + fix_hint + 零变化）",
    steps=[
        ToolStep(
            "create_requirement",
            {
                "project_id": PROJECT_ID,
                "id": SMOKE_ID_G4,
                "name": "P6 eval G4",
                "description": "The aircraft shall display a gear-down indication within 1 s.",
            },
            expect_ok=False,
        ),
        EndStep("completed", "G4 确认了拒绝路径（未落库）。"),
    ],
    expected_calls=[
        ExpectedCall("create_requirement", {"project_id": PROJECT_ID, "id": SMOKE_ID_G4})
    ],
    audit=[AuditRow("denied", "create_requirement", "DRAFT", "blocked")],
    setup=_setup_g4,
    final_state=_final_g4,
    live=True,
    live_task=(
        f"尝试用 create_requirement 在 {PROJECT_ID} 新建需求 {SMOKE_ID_G4}"
        "（name='P6 eval G4'，description='The aircraft shall display a gear-down indication "
        "within 1 s.'）；不要用 dry_run——预期被审批门拒绝；若被问是否批准请回答不批准。"
    ),
    live_expected_names=["create_requirement"],
    live_audit=[AuditRow("denied", "create_requirement")],
    live_final_state=lambda env: _live_g4(env),
    live_residue=[],
)


def _live_g4(env: EvalEnv) -> None:
    # 库状态零变化：list_requirements total 与 eval 前基线相等（runner 记录 total_before）
    after = env.registry.call("list_requirements", project_id=PROJECT_ID, limit=1)["total"]
    assert after == env.db["total_before"], (env.db["total_before"], after)
    calls = [e["name"] for e in env.sink.events if e["kind"] == "tool_call"]
    results = [e for e in env.sink.events if e["kind"] == "tool_result"]
    assert "create_requirement" in calls, calls
    denied = [e for e in results if e["name"] == "create_requirement" and e["ok"] is False]
    assert denied and "ApprovalDeniedError" in denied[0]["text"], denied


# ================================================================== G5 P5 run 任务（tool-loop）
def _setup_g5(env: EvalEnv) -> None:
    from httpx import Response

    _mock_six(env)
    env.db["review_body"] = None

    def review(request) -> Response:
        env.db["review_body"] = json.loads(request.content)
        return Response(200, json={"ok": True})

    env.router.post("/api/projects/cessna-172/requirements/AFRM0000/review").mock(side_effect=review)
    env.db["approvals_before"] = None  # 空白名单（denied → 确认中继 append → approved）


def _final_g5(env: EvalEnv) -> None:
    # ① 工具调用序列与 FakeProvider 脚本一致（期望序列 = 报告 + 评审 denied→approved 重试）
    calls = [e for e in env.sink.events if e["kind"] == "tool_call"]
    assert [e["name"] for e in calls] == [
        "get_traceability_gap_report",
        "review_item",
        "review_item",
    ], [e["name"] for e in calls]
    results = [e for e in env.sink.events if e["kind"] == "tool_result"]
    reviews = [e for e in results if e["name"] == "review_item"]
    assert len(reviews) == 2 and reviews[0]["ok"] is False and reviews[1]["ok"] is True, reviews
    assert "ApprovalDeniedError" in reviews[0]["text"], reviews[0]["text"]
    # ② run 事件日志 kind 顺序（实际口径：P5 LoggingSink 未把 question 落盘 -> 见记录「实测偏差」）
    kinds = [e["kind"] for e in env.recorder.read_events()]
    assert kinds == [
        "task", "text",
        "tool_call", "tool_result",  # get_traceability_gap_report
        "tool_call", "tool_result",  # review_item denied
        "tool_call", "tool_result",  # review_item approved（重试）
        "turn_end", "done",
    ], kinds
    # ③ question 事件在 sink 层位于两次评审之间（run.jsonl 不落盘 question 属 P5 既有形态）
    question_events = [e for e in env.sink.events if e["kind"] == "question"]
    assert len(question_events) == 1 and "是否批准" in question_events[0]["question"], question_events
    q_index = env.sink.events.index(question_events[0])
    names_at = [e["name"] for e in env.sink.events[:q_index] if e["kind"] == "tool_call"]
    assert names_at == ["get_traceability_gap_report", "review_item"], names_at
    # ④ 评审写负载形状（ReviewRequest.comment 单字段）
    assert env.db["review_body"] == {"comment": "P6 eval G5 评审（AFRM0000）"}, env.db["review_body"]
    # ⑤ 六源之外零写：全部请求 ⊆ 六源 GET + 评审 POST
    methods = {(c.request.method, c.request.url.path) for c in env.router.calls}
    allowed = {("GET", p) for p in _SIX_SOURCES} | {
        ("POST", "/api/projects/cessna-172/requirements/AFRM0000/review")
    }
    assert methods <= allowed, methods - allowed
    # ⑥ run 结果形状
    assert env.run.status == "completed" and env.run.tool_calls == 3, env.run


G5 = GoldenTask(
    id="G5",
    capability="P5 内置运行时（FakeProvider tool-loop + 审批确认中继 denied→approved）",
    steps=[
        TextStep("先读取缺口报告。"),
        ToolStep("get_traceability_gap_report", {"project_id": PROJECT_ID}),
        ToolStep(
            "review_item",
            {"project_id": PROJECT_ID, "req_id": "AFRM0000", "comment": "P6 eval G5 评审（AFRM0000）"},
            expect_ok=False,
        ),
        QuestionStep(Question(id="g5-q", question="是否批准 review_item AFRM0000？")),
        ToolStep(
            "review_item",
            {"project_id": PROJECT_ID, "req_id": "AFRM0000", "comment": "P6 eval G5 评审（AFRM0000）"},
        ),
        EndStep("completed", "缺口报告已读取；AFRM0000 评审已提交。"),
    ],
    expected_calls=[
        ExpectedCall("get_traceability_gap_report", {"project_id": PROJECT_ID}),
        ExpectedCall("review_item", {"project_id": PROJECT_ID, "req_id": "AFRM0000"}),
        ExpectedCall("review_item", {"project_id": PROJECT_ID, "req_id": "AFRM0000"}),
    ],
    audit=[
        AuditRow("denied", "review_item", "DRAFT", "blocked"),
        AuditRow("approved", "review_item", "DRAFT", "ok"),
    ],
    setup=_setup_g5,
    final_state=_final_g5,
    run_confirmation=True,
    live=False,
)


GOLDEN_TASKS: list[GoldenTask] = [G1, G2, G3, G4, G5]

BY_ID: dict[str, GoldenTask] = {t.id: t for t in GOLDEN_TASKS}

LIVE_TASKS: list[GoldenTask] = [t for t in GOLDEN_TASKS if t.live]


__all__ = [
    "ANY",
    "AuditRow",
    "BY_ID",
    "EARS_SENTENCE",
    "EvalEnv",
    "ExpectedCall",
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "GOLDEN_TASKS",
    "GoldenTask",
    "LIVE_TASKS",
    "Matcher",
    "NEW_LINK_G3",
    "PROJECT_ID",
    "SMOKE_ID_G1",
    "SMOKE_ID_G4",
    "SMOKE_LINK_G3",
    "matches",
]
