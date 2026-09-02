"""#40 `reqmesh-harness run` CLI：参数契约、流式渲染（capsys）、project context 解析（fail-fast）、
resume 两分支、--yes 中继接线、TTY /steer、退出码、审计摘要（spec 验收 8/10）。"""

from __future__ import annotations

import asyncio
import io
import json
import threading
from pathlib import Path

import pytest
import respx
from httpx import Response

from reqmesh_harness.config import Settings
from reqmesh_harness.runtime import AgentRequest, ProjectContext, RunResult
from reqmesh_harness.runtime.dsh_provider import DshProvider
from reqmesh_harness.runtime.memory import RunRecorder
from reqmesh_harness.runtime.run_cli import run_main, _exit_code
from tests.conftest import HTTP_FIXTURES

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


class StubProvider:
    """注入的 provider：记录请求/接线；steer 记录；cancel 记录。"""

    execution = "delegated"
    name = "stub"

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []
        self.sessions: list[str] = []
        self.denied: list[tuple] = []
        self.steers: list[str] = []
        self.cancel_remote_calls = 0
        self.question_answerer = None
        self._wiring: dict = {}

    def bind(self, wiring: dict) -> "StubProvider":
        self._wiring = wiring
        if wiring.get("question_answerer"):
            self.question_answerer = wiring["question_answerer"]
        if wiring.get("on_session"):
            wiring["on_session"](
                "stub-session-1"
            )  # 模拟 DSH session 注册（recorder 落盘）
        return self

    async def run_agentic(self, request, sink, *, cancel) -> RunResult:
        self.requests.append(request)
        if cancel.is_set():
            return RunResult("cancelled", "", 0, 0, None)
        sink.on_text("stub 输出")
        sink.on_turn_end("completed")
        return RunResult("completed", "stub 输出", 1, 0, None)

    def steer(self, text: str) -> None:
        self.steers.append(text)

    def cancel_remote(self) -> None:
        self.cancel_remote_calls += 1


def _cli_env(monkeypatch, tmp_path) -> dict:
    monkeypatch.setenv("REQMESH_BASE_URL", "http://reqmesh.test")
    monkeypatch.setenv("REQMESH_USERNAME", "dev")
    monkeypatch.setenv("REQMESH_PASSWORD", "dev-pass")
    monkeypatch.setenv("REQMESH_TOKEN", "")
    monkeypatch.setenv("REQMESH_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("REQMESH_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("REQMESH_APPROVALS_FILE", str(tmp_path / "approvals.toml"))
    session_file = tmp_path / "session.json"
    session_file.write_text((FIXTURES / "session.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(session_file))
    return {"tmp": tmp_path}


def _factory(stub: StubProvider):
    def factory(settings, *, registry=None, **wiring):
        return stub.bind(wiring)

    return factory


def test_exit_code_mapping() -> None:
    assert _exit_code("completed") == 0
    assert _exit_code("failed") == 1
    assert _exit_code("cancelled") == 130


def test_run_minimal_params_and_streaming_render(monkeypatch, tmp_path, capsys) -> None:
    """参数契约 + 流式渲染（text 逐块 stdout、工具行、结束行）+ 审计摘要 + run 目录落盘。"""
    _cli_env(monkeypatch, tmp_path)
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172").mock(
            return_value=Response(200, json=_fixture("project_detail.json"))
        )
        code = run_main(
            [
                "给 cessna-172 补一条需求",
                "--project",
                "cessna-172",
                "--yes",
                "--max-rounds",
                "5",
            ],
            provider_factory=_factory(stub),
            steer_input=io.StringIO(),
        )
    assert code == 0
    out = capsys.readouterr().out
    assert "stub 输出" in out
    assert "[结束]" in out
    assert "审计摘要" in out
    # run 目录 + context.json + run.jsonl（task/done 事件）+ dsn-session.txt
    runs = Path(Path(tmp_path) / "runs")
    entries = [p for p in runs.iterdir() if p.is_dir()]
    assert len(entries) == 1
    ctx = json.loads((entries[0] / "context.json").read_text(encoding="utf-8"))
    assert ctx["provider"] == "dsh"
    assert ctx["project_context"]["project_id"] == "cessna-172"
    events = [e["kind"] for e in RunRecorder(entries[0]).read_events()]
    assert "task" in events and "done" in events
    assert (entries[0] / "dsn-session.txt").read_text(
        encoding="utf-8"
    ) == "stub-session-1"
    # 请求装配：指令任务 + max_rounds
    request = stub.requests[0]
    assert request.max_rounds == 5
    assert request.project_context == ProjectContext(
        project_id="cessna-172",
        base_url="http://reqmesh.test",
        created_at=_fixture("project_detail.json").get("created_at", ""),
    )


def test_run_fail_fast_when_project_id_in_task_without_flag(
    monkeypatch, tmp_path, capsys
) -> None:
    """未给 --project 且任务文本唯一命中项目 id → fail-fast（不做启发式猜测）。"""
    _cli_env(monkeypatch, tmp_path)
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects").mock(
            return_value=Response(
                200, json=[{"id": "cessna-172", "name": "Cessna 172S Skyhawk SP"}]
            )
        )
        code = run_main(
            ["给 cessna-172 补一条需求"],
            provider_factory=_factory(stub),
            steer_input=io.StringIO(),
        )
    assert code == 2
    err = capsys.readouterr().err
    assert "--project" in err and "显式" in err
    assert stub.requests == []


def test_run_no_project_mention_readonly_task(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects").mock(
            return_value=Response(200, json=[{"id": "cessna-172", "name": "C"}])
        )
        code = run_main(
            ["列出全部项目"], provider_factory=_factory(stub), steer_input=io.StringIO()
        )
    assert code == 0
    assert stub.requests[0].project_context is None


def test_run_badge_resume_id(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    code = run_main(
        ["继续任务", "--resume", "run-10000101T000000-deadbeef"],
        provider_factory=_factory(StubProvider()),
        steer_input=io.StringIO(),
    )
    assert code == 2
    assert "不存在" in capsys.readouterr().err


def test_run_resume_branch1_live_dsh_session(monkeypatch, tmp_path, capsys) -> None:
    """分支①：DSH 会话存活 → session id 沿用 + history 为空（原生历史）。"""
    _cli_env(monkeypatch, tmp_path)
    root = Path(tmp_path) / "runs"
    old = RunRecorder.create(root)
    old.init_context(task="原任务", project_context=None, provider="dsh")
    old.save_dsh_session("dsn-old-1")
    stub = StubProvider()
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172").mock(
            return_value=Response(200, json=_fixture("project_detail.json"))
        )
        code = run_main(
            ["继续", "--resume", old.run_id, "--project", "cessna-172"],
            provider_factory=_factory(stub),
            session_live_check=lambda sid: sid == "dsn-old-1",
            steer_input=io.StringIO(),
        )

    assert code == 0
    request = stub.requests[0]
    assert request.history == []  # DSH 会话自带历史
    # 新目录 -resume + resumed_from
    resumed = [p for p in root.iterdir() if p.name.endswith("-resume")]
    assert len(resumed) == 1
    ctx = json.loads((resumed[0] / "context.json").read_text(encoding="utf-8"))
    assert ctx["resumed_from"] == old.run_id


def test_run_resume_branch2_dead_session_rebuilds_summary(
    monkeypatch, tmp_path, capsys
) -> None:
    """分支②：DSH 会话失活 → 历史摘要注入（history 字段承载 + 明示重建来源）。"""
    _cli_env(monkeypatch, tmp_path)
    root = Path(tmp_path) / "runs"
    old = RunRecorder.create(root)
    old.init_context(task="原任务：读缺口并评审", project_context=None, provider="dsh")
    old.save_dsh_session("dsn-old-gone")
    old.record_text("部分进展")
    old.record_tool_call("get_traceability_gap_report", {"project_id": "cessna-172"})
    old.record_done("completed", "最终文本", tool_calls=1, questions=0)
    stub = StubProvider()
    code = run_main(
        ["继续", "--resume", old.run_id],
        provider_factory=_factory(stub),
        session_live_check=lambda sid: False,
        steer_input=io.StringIO(),
    )
    assert code == 0
    request = stub.requests[0]
    assert request.history
    assert "历史由 harness 内存重建" in request.history[0]["content"]
    assert "最终文本" in request.history[0]["content"]


def test_run_tty_steer_wiring(monkeypatch, tmp_path, capsys) -> None:
    """TTY /steer：steer 输入流 → provider.steer（行首 /steer 前缀，其余忽略）。"""
    _cli_env(monkeypatch, tmp_path)
    stub = StubProvider()
    steer_input = io.StringIO("/steer 请检查一下\n普通行\n")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects").mock(return_value=Response(200, json=[]))
        code = run_main(
            ["纯只读任务"],
            provider_factory=_factory(stub),
            steer_input=steer_input,
        )
    assert code == 0
    assert stub.steers == ["请检查一下"]


def test_run_unknown_provider_value(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    code = run_main(
        ["任务", "--provider", "fancy", "--project", "cessna-172"],
        provider_factory=_factory(StubProvider()),
        steer_input=io.StringIO(),
    )
    assert code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_run_cli_fake_provider_requires_script(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    code = run_main(
        ["任务", "--provider", "fake"],
        provider_factory=_factory(StubProvider()),
        steer_input=io.StringIO(),
    )
    assert code == 2
    assert "fake" in capsys.readouterr().err


def test_run_keyboard_interrupt_returns_130(monkeypatch, tmp_path, capsys) -> None:
    _cli_env(monkeypatch, tmp_path)
    stub = StubProvider()

    class InterruptProvider(StubProvider):
        async def run_agentic(self, request, sink, *, cancel) -> RunResult:
            raise KeyboardInterrupt

    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172").mock(
            return_value=Response(200, json=_fixture("project_detail.json"))
        )
        code = run_main(
            ["任务", "--project", "cessna-172"],
            provider_factory=_factory(InterruptProvider()),
            steer_input=io.StringIO(),
        )
    assert code == 130


def test_run_runtime_error_returns_1_and_records_error(
    monkeypatch, tmp_path, capsys
) -> None:
    _cli_env(monkeypatch, tmp_path)
    from reqmesh_harness.errors import ProviderError

    class FailProvider(StubProvider):
        async def run_agentic(self, request, sink, *, cancel) -> RunResult:
            raise ProviderError("unavailable", "DSH 宿主不可达: boom")

    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172").mock(
            return_value=Response(200, json=_fixture("project_detail.json"))
        )
        code = run_main(
            ["任务", "--project", "cessna-172"],
            provider_factory=_factory(FailProvider()),
            steer_input=io.StringIO(),
        )
    assert code == 1
    assert "DSH 宿主不可达" in capsys.readouterr().err
    runs = [p for p in (Path(tmp_path) / "runs").iterdir() if p.is_dir()]
    events = RunRecorder(runs[0]).read_events()
    assert any(e["kind"] == "error" for e in events)


@pytest.mark.asyncio
async def test_dsh_provider_steer_prompt_mode_steer() -> None:
    """/steer → session.prompt(mode="steer")（spec ④：steer 是指导注入，不作审批裁决）。"""
    from tests.test_dsh_provider import (
        _rpc_stubs,
        ScriptedWs,
        _frame,
        RecordingSink,
        _settings,
    )

    bodies: list[dict] = []

    def prompt_handler(request) -> Response:
        body = json.loads(request.content)
        bodies.append(body)
        return Response(
            200,
            json={
                "type": "server-response",
                "rpcId": body["rpcId"],
                "result": {"ok": True, "value": {"accepted": True}},
            },
        )

    with respx.mock(base_url="http://dsh.local") as router:
        router.post("/api/session.create").mock(
            side_effect=lambda req: Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": json.loads(req.content)["rpcId"],
                    "result": {"ok": True, "value": {"sessionId": "sess-1"}},
                },
            )
        )
        router.post("/api/session.prompt").mock(side_effect=prompt_handler)
        router.post("/api/session.list").mock(
            side_effect=lambda req: Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": json.loads(req.content)["rpcId"],
                    "result": {
                        "ok": True,
                        "value": json.loads(
                            (
                                Path(__file__).parent
                                / "fixtures"
                                / "dsh"
                                / "session_list_idle.json"
                            ).read_text("utf-8")
                        ),
                    },
                },
            )
        )
        ws = ScriptedWs([json.dumps(_frame("session_event_turn_end_completed.json"))])
        provider = DshProvider(
            _settings(),
            ws_factory=lambda url: ws,
            on_denied=lambda *a: None,
            poll_interval=0.01,
        )
        from reqmesh_harness.runtime.provider import AgentRequest as AR

        req = AR(task="t", project_context=None, history=[], tools=[])
        result = await provider.run_agentic(
            req, RecordingSink(), cancel=threading.Event()
        )
        # 运行后 steer 调用（模拟 TTY）——仍在 respx 上下文内
        provider.steer("请重新检查")
    assert result.status == "completed"
    steers = [b for b in bodies if b["payload"]["mode"] == "steer"]
    assert len(steers) == 1
    assert steers[0]["payload"]["content"] == [{"type": "text", "text": "请重新检查"}]
    assert steers[0]["payload"]["sessionId"] == "sess-1"
