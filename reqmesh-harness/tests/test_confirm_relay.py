"""#41 审批门交互时序：denied → 确认中继（--yes 无头自动 / TTY 逐条 y-N）→ WhitelistStore.append →
agent 重试 → approved；审计双行（denied + approved，P2 字段零改动）；MUTATE 缺 project 不确认；
tool-loop 全链（FakeProvider + respx）审计两行断言（spec 验收 9 / 离线任务用例①）。"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest
import respx
from httpx import Response

from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ProviderError
from reqmesh_harness.guardrails.audit import AuditLog
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.runtime.confirm import (
    ConfirmationRelay,
    ConfirmedToolExecutor,
    PendingApproval,
)
from reqmesh_harness.runtime.fake import (
    EndStep,
    FakeProvider,
    QuestionStep,
    TextStep,
    ToolStep,
)
from reqmesh_harness.runtime.loop import RunDriver, ToolExecutor
from reqmesh_harness.runtime.provider import ProjectContext, Question
from reqmesh_harness.tools import build_registry
from tests.test_report_tool import (
    SIX_SOURCES,
    _fixture,
)  # noqa: F401 -- 六源路径/夹具复用

CTX = ProjectContext(
    project_id="cessna-172",
    base_url="http://reqmesh.test",
    created_at="2026-01-01T00:00:00Z",
)


def _settings(tmp_path) -> Settings:
    return Settings(
        base_url="http://reqmesh.test",
        username="dev",
        password="dev-pass",
        approvals_file=tmp_path / "approvals.toml",
        audit_file=tmp_path / "audit.jsonl",
        session_file=tmp_path / "session.json",
    )


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[str] = []

    def on_text(self, text: str) -> None:
        self.events.append("text:" + text)

    def on_tool_call(self, name: str, args: dict) -> None:
        self.events.append("tool_call:" + name)

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.events.append("tool_result:" + name + ":" + ("ok" if ok else "denied"))

    def on_question(self, q) -> None:
        self.events.append("question")

    def on_turn_end(self, reason: str) -> None:
        self.events.append("turn_end:" + reason)


# ------------------------------------------------------------------ 中继单元
class TestRelay:
    def test_auto_yes_appends_entry_and_answers_approval(self, tmp_path) -> None:
        relay = ConfirmationRelay(_settings(tmp_path), auto_yes=True)
        relay.on_denied(
            "review_item",
            {"project_id": "cessna-172", "req_id": "AFRM0000"},
            "ApprovalDeniedError: 拒绝",
        )
        entries = WhitelistStore(tmp_path / "approvals.toml").load()
        assert WhitelistEntry(tool="review_item", project="cessna-172") in entries
        text = relay.answer(Question(id="q1", question="批准？"))
        assert "已批准，请重试" in text
        assert relay.pending is None

    def test_tty_confirm_approves_with_spec_prompt(self, tmp_path, capsys) -> None:
        prompts: list[str] = []

        def reader(prompt: str) -> str:
            prompts.append(prompt)
            return "y"

        relay = ConfirmationRelay(_settings(tmp_path), confirm_reader=reader)
        relay.on_denied(
            "review_item", {"project_id": "cessna-172"}, "ApprovalDeniedError: 拒绝"
        )
        text = relay.answer(Question(id="q1", question="批准？"))
        assert "已批准，请重试" in text
        # spec ④ TTY 提示格式（内容为契约）
        assert prompts and "审批确认：tool=review_item" in prompts[0]
        assert "project=cessna-172" in prompts[0] and "level=DRAFT" in prompts[0]
        assert "dry_run=False" in prompts[0]
        assert "批准将写入白名单条目并重试 [y/N]" in prompts[0]
        assert (
            WhitelistEntry(tool="review_item", project="cessna-172")
            in WhitelistStore(tmp_path / "approvals.toml").load()
        )

    def test_tty_reject_no_entry(self, tmp_path) -> None:
        relay = ConfirmationRelay(
            _settings(tmp_path), confirm_reader=lambda prompt: "N"
        )
        relay.on_denied(
            "review_item", {"project_id": "cessna-172"}, "ApprovalDeniedError: 拒绝"
        )
        text = relay.answer(Question(id="q1", question="批准？"))
        assert "用户拒绝" in text
        assert WhitelistStore(tmp_path / "approvals.toml").load() == []

    def test_draft_without_project_wildcard_entry(self, tmp_path) -> None:
        relay = ConfirmationRelay(_settings(tmp_path), auto_yes=True)
        relay.on_denied("review_item", {"req_id": "AFRM0000"}, "ApprovalDeniedError")
        entries = WhitelistStore(tmp_path / "approvals.toml").load()
        assert WhitelistEntry(tool="review_item", project=None) in entries  # DRAFT 通配

    def test_mutate_without_project_cannot_confirm(self, tmp_path) -> None:
        warnings: list[str] = []
        relay = ConfirmationRelay(
            _settings(tmp_path),
            auto_yes=True,
            warning=lambda text: warnings.append(text),
        )
        relay.on_denied(
            "update_requirement", {"req_id": "AFRM0000"}, "ApprovalDeniedError"
        )
        text = relay.answer(Question(id="q1", question="批准？"))
        assert "用户拒绝" in text or "无法" in text
        assert warnings and "具体 project" in warnings[0]
        assert WhitelistStore(tmp_path / "approvals.toml").load() == []

    def test_generic_question_without_pending_tty(self, tmp_path) -> None:
        answers: list[str] = []

        def reader(prompt: str) -> str:
            answers.append(prompt)
            return "继续吧"

        relay = ConfirmationRelay(_settings(tmp_path), confirm_reader=reader)
        text = relay.answer(Question(id="q9", question="是否继续执行？"))
        assert text == "继续吧"
        assert "是否继续执行？" in answers[0]

    def test_unknown_tool_level_cannot_confirm(self, tmp_path) -> None:
        warnings: list[str] = []
        relay = ConfirmationRelay(
            _settings(tmp_path),
            auto_yes=True,
            warning=lambda text: warnings.append(text),
        )
        relay.on_denied("flying_saucers", {}, "ApprovalDeniedError")
        assert relay.pending is None
        assert warnings


# ------------------------------------------------------------------ confirmed executor + e2e


def test_tool_loop_tty_confirmation_triggered_at_denial(reqmesh_env) -> None:
    """②测试子代理反馈：OpenAI/tool-loop 路线 TTY 通道的触发点 = denial 即确认（无 question 帧也可用）。

    executor 挂点：ConfirmNow 在 denied 时立即呈现审批确认；错误文本原样回灌（模型自行重试，
    重试命中白名单）。之后的问题帧走通用回答（pending 已清）。
    """
    settings = Settings()
    calls: list[str] = []

    def reader(prompt: str) -> str:
        calls.append(prompt)
        return "y" if len(calls) == 1 else "没啥问题"

    relay = ConfirmationRelay(settings, confirm_reader=reader)
    confirmed = ConfirmedToolExecutor(
        ToolExecutor(registry=build_registry(), settings=settings), relay
    )
    with respx.mock(base_url="http://reqmesh.test"):
        result = confirmed(
            "review_item", {"project_id": "cessna-172", "req_id": "ACFT0000"}, CTX
        )
    # ① denial 即触发审批确认（TTY）→ 白名单已有条目
    assert result.ok is False  # 错误文本回灌（模型再决定重试）
    assert (
        calls
        and "审批确认：tool=review_item" in calls[0]
        and "project=cessna-172" in calls[0]
    )
    assert (
        WhitelistEntry(tool="review_item", project="cessna-172")
        in WhitelistStore(settings.resolved_approvals_file()).load()
    )
    # ② pending 已清：后续（脚本/模型的）问题走通用回答
    assert relay.pending is None
    assert relay.answer(Question(id="q7", question="继续吗？")) == "没啥问题"


def _mock_six(router) -> None:
    for path, fixture in SIX_SOURCES.items():
        router.get(path).mock(return_value=Response(200, json=_fixture(fixture)))


def _mock_review_targets(router) -> None:
    # 真实写路径只发 POST（checks 仅 dry_run 触发）；denied 路径零请求
    router.post("/api/projects/cessna-172/requirements/ACFT0000/review").mock(
        return_value=Response(200, json=_fixture("requirement_get.json"))
    )


@pytest.mark.asyncio
async def test_e2e_gap_report_then_approval_denied_retry(reqmesh_env) -> None:
    """离线任务用例①：get_traceability_gap_report → review_item denied → 确认通道 → 重试 approved。
    断言：工具调用序列、审计两行、流式顺序、白名单条目、RunResult。
    注：write_request 经 get_runtime().settings（环境变量）读审批/审计文件——middleware 依赖 env，
    故 Settings() 与 relay 必须以相同 env 解析（与 reqmesh_env 同源）。"""
    settings = Settings()
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        _mock_review_targets(router)
        relay = ConfirmationRelay(settings, auto_yes=True)
        registry = build_registry()
        driver = RunDriver(registry=registry, settings=settings)
        inner = ToolExecutor(registry=registry, settings=settings)
        confirmed = ConfirmedToolExecutor(inner, relay)
        driver.executor_factory = lambda: confirmed

        provider = FakeProvider(
            [
                TextStep("检查缺口报告。"),
                ToolStep("get_traceability_gap_report", {"project_id": "cessna-172"}),
                TextStep("发现缺口，提交评审。"),
                ToolStep(
                    "review_item",
                    {
                        "project_id": "cessna-172",
                        "req_id": "ACFT0000",
                        "comment": "补充来源与验证方法",
                    },
                    expect_ok=False,
                ),
                QuestionStep(
                    question=Question(id="q-1", question="是否批准 review_item？")
                ),
                ToolStep(
                    "review_item",
                    {
                        "project_id": "cessna-172",
                        "req_id": "ACFT0000",
                        "comment": "补充来源与验证方法",
                    },
                    expect_ok=True,
                ),
                EndStep("completed", "评审建议已提交。"),
            ]
        )
        request = driver.assemble(
            "读缺口报告并写评审建议", project_context=CTX, history=[]
        )
        sink = RecordingSink()
        result = await driver.drive(provider, request, sink, cancel=threading.Event())

    assert result.status == "completed"
    assert (
        result.tool_calls == 3
    )  # 缺口报告 1 + review_item 2（denied + approved 重试）
    assert result.questions == 1
    # ① 工具调用序列（含一次性 denied 重试）
    assert [e for e in sink.events if e.startswith("tool_call:")] == [
        "tool_call:get_traceability_gap_report",
        "tool_call:review_item",
        "tool_call:review_item",
    ]
    # ② 流式顺序：text → tool_call → tool_result → … → question → … → 重试 call → … → turn_end
    q_index = sink.events.index("question")
    call_indexes = [
        i for i, e in enumerate(sink.events) if e == "tool_call:review_item"
    ]
    assert sink.events.index("tool_result:review_item:denied") < q_index
    assert call_indexes[0] < q_index < call_indexes[1]  # 重试在问题之后
    assert sink.events[-1] == "turn_end:completed"
    # ③ 审计恰 2 行（denied + approved；P2 version=1 字段）
    audit = AuditLog(settings.resolved_audit_file()).read_all()
    assert [a["decision"] for a in audit] == ["denied", "approved"]
    assert all(a["tool"] == "review_item" and a["level"] == "DRAFT" for a in audit)
    assert audit[0]["deny_reason"] and audit[0]["approved_by"] is None
    assert audit[1]["approved_by"] and "review_item" in audit[1]["approved_by"]
    assert all(a["version"] == 1 for a in audit)
    # ④ 白名单条目（唯一裁决源）
    assert (
        WhitelistEntry(tool="review_item", project="cessna-172")
        in WhitelistStore(settings.resolved_approvals_file()).load()
    )


@pytest.mark.asyncio
async def test_e2e_readonly_task_zero_audit_lines(reqmesh_env) -> None:
    """离线任务用例②：READ-only 任务（get_coverage → 完成）断言零审计行（P2：READ 不记审计）。"""
    settings = Settings()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172/coverage").mock(
            return_value=Response(200, json=_fixture("coverage.json"))
        )
        relay = ConfirmationRelay(settings, auto_yes=True)
        registry = build_registry()
        driver = RunDriver(registry=registry, settings=settings)
        inner = ToolExecutor(registry=registry, settings=settings)
        driver.executor_factory = lambda: ConfirmedToolExecutor(inner, relay)
        provider = FakeProvider(
            [
                ToolStep("get_coverage", {"project_id": "cessna-172"}, expect_ok=True),
                EndStep("completed", "覆盖率 81%。"),
            ]
        )
        request = driver.assemble("查覆盖率", project_context=CTX, history=[])
        result = await driver.drive(
            provider, request, RecordingSink(), cancel=threading.Event()
        )
    assert result.status == "completed"
    assert result.tool_calls == 1
    assert AuditLog(settings.resolved_audit_file()).read_all() == []
    assert WhitelistStore(settings.resolved_approvals_file()).load() == []


@pytest.mark.asyncio
async def test_e2e_user_rejects_single_denied_line(reqmesh_env) -> None:
    """用户拒绝路径：只记 denied 一行；白名单无变化；总结继续（spec ④/验收 9）。"""
    settings = Settings()
    with respx.mock(base_url="http://reqmesh.test") as router:
        _mock_six(router)
        relay = ConfirmationRelay(settings, confirm_reader=lambda prompt: "N")
        registry = build_registry()
        driver = RunDriver(registry=registry, settings=settings)
        inner = ToolExecutor(registry=registry, settings=settings)
        driver.executor_factory = lambda: ConfirmedToolExecutor(inner, relay)
        provider = FakeProvider(
            [
                ToolStep("get_traceability_gap_report", {"project_id": "cessna-172"}),
                ToolStep(
                    "review_item",
                    {
                        "project_id": "cessna-172",
                        "req_id": "ACFT0000",
                        "comment": "评审",
                    },
                    expect_ok=False,
                ),
                QuestionStep(question=Question(id="q-1", question="批准？")),
                EndStep("completed", "用户拒绝，评审未提交。"),
            ]
        )
        request = driver.assemble(
            "读缺口报告并写评审建议", project_context=CTX, history=[]
        )
        result = await driver.drive(
            provider, request, RecordingSink(), cancel=threading.Event()
        )
    assert result.status == "completed"
    audit = AuditLog(settings.resolved_audit_file()).read_all()
    assert [a["decision"] for a in audit] == ["denied"]
    assert WhitelistStore(settings.resolved_approvals_file()).load() == []
