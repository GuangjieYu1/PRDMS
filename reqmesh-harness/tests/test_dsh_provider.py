"""#38 DSH provider 适配器：loopback RPC 信封与应答、WS events.mux 帧解析（10 种）、
chunk 打包行展开、错误码映射、完成判定（turn/end + running=false）、空闲超时与 cancel
（spec 验收 4/5；fixture：tests/fixtures/dsh/）。全离线（respx 打桩 + 脚本化 WS）。"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
import respx
from httpx import Request, Response

from reqmesh_harness.config import Settings
from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime.dsh_provider import (
    DshProvider,
    DshRpcClient,
    MuxHandler,
    ParsedFrame,
    iter_chunk_deltas,
    parse_frame,
    ws_url,
    _status_for,
)
from reqmesh_harness.runtime.provider import Question, RunResult

DSH = "http://dsh.local"
FIXTURES = Path(__file__).parent / "fixtures" / "dsh"
FRAMES = FIXTURES / "frames"


def _frame(name: str) -> dict:
    return json.loads((FRAMES / name).read_text(encoding="utf-8"))


def _echo_ok(value: dict | list) -> Response:
    """server-response 封装（rpcId 回显请求，接受 JSON 值）。"""

    def handler(request) -> Response:
        body = json.loads(request.content)
        return Response(
            200,
            json={
                "type": "server-response",
                "rpcId": body["rpcId"],
                "result": {"ok": True, "value": value},
            },
        )

    return handler


def _lines(path: Path) -> list[str]:
    return [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class ScriptedWs:
    """脚本化 WS：aenter 后按序 yield 帧（str 或 dict）；可挂起等待（空闲超时测试）。"""

    def __init__(self, frames: list, *, hang_after: int | None = None) -> None:
        self._frames = frames
        self._hang_after = hang_after

    async def __aenter__(self) -> "ScriptedWs":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for i, frame in enumerate(self._frames):
            yield (
                frame
                if isinstance(frame, str)
                else json.dumps(frame, ensure_ascii=False)
            )
            if self._hang_after is not None and i + 1 >= self._hang_after:
                await asyncio.sleep(3600)


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def on_text(self, text: str) -> None:
        self.events.append(("text", text))

    def on_tool_call(self, name: str, args: dict) -> None:
        self.events.append(("tool_call", (name, args)))

    def on_tool_result(self, name: str, ok: bool, summary: str) -> None:
        self.events.append(("tool_result", (name, ok, summary)))

    def on_question(self, q: Question) -> None:
        self.events.append(("question", q))

    def on_turn_end(self, reason: str) -> None:
        self.events.append(("turn_end", reason))


def _settings(**overrides) -> Settings:
    kw = dict(dsh_url=DSH, dsh_cwd="/tmp/proj", dsh_idle_timeout=2.0)
    kw.update(overrides)
    return Settings(**kw)


# ------------------------------------------------------------------ 帧解析
class TestParseFrame:
    def test_subscribed(self) -> None:
        frame = parse_frame(json.dumps(_frame("session_subscribed.json")))
        assert frame.kind == "session/subscribed"
        assert frame.session_id == "sess-1"
        assert frame.rpc_id == "host-1"

    def test_session_event(self) -> None:
        frame = parse_frame(json.dumps(_frame("session_event_text_delta.json")))
        assert frame.kind == "session/event"
        assert frame.payload["event"]["type"] == "assistant/chunk"

    def test_non_json_is_protocol(self) -> None:
        with pytest.raises(ProviderError) as exc:
            parse_frame("not-json")
        assert exc.value.kind == "protocol"

    def test_wrong_envelope_is_protocol(self) -> None:
        with pytest.raises(ProviderError):
            parse_frame(
                json.dumps(
                    {
                        "type": "client-request",
                        "rpcId": "x",
                        "method": "m",
                        "payload": {},
                    }
                )
            )

    def test_unknown_frame_type_is_protocol(self) -> None:
        with pytest.raises(ProviderError) as exc:
            parse_frame(
                json.dumps(
                    {
                        "type": "server-request",
                        "rpcId": "x",
                        "method": "future/thing",
                        "payload": {"type": "future/thing", "sessionId": "s1"},
                    }
                )
            )
        assert "未知 MuxFrame" in exc.value.message

    def test_missing_payload_type_is_protocol(self) -> None:
        with pytest.raises(ProviderError):
            parse_frame(
                json.dumps(
                    {
                        "type": "server-request",
                        "rpcId": "x",
                        "method": "m",
                        "payload": {},
                    }
                )
            )

    def test_all_ten_frame_types_parse(self) -> None:
        names = [
            "session_subscribed.json",
            "session_event_text_delta.json",
            "approval_requested.json",
            "approval_resolved.json",
            "question_requested.json",
            "question_resolved.json",
            "session_queue.json",
            "session_jobs.json",
            "session_projection.json",
            "stream_error_internal.json",
        ]
        for name in names:
            frame = parse_frame(json.dumps(_frame(name)))
            assert frame.kind in {
                "session/event",
                "session/subscribed",
                "approval/requested",
                "approval/resolved",
                "question/requested",
                "question/resolved",
                "session/queue",
                "session/jobs",
                "session/projection",
                "stream/error",
            }


# ------------------------------------------------------------------ chunk 展开
class TestChunkExpansion:
    def test_live_text_delta(self) -> None:
        deltas = iter_chunk_deltas(
            _frame("session_event_text_delta.json")["payload"]["event"]
        )
        assert [(d.kind, d.text) for d in deltas] == [("text-delta", "P5-")]

    def test_storage_row_expands_per_delta(self) -> None:
        deltas = iter_chunk_deltas(
            _frame("session_event_text_chunks_row.json")["payload"]["event"]
        )
        assert [(d.kind, d.text) for d in deltas] == [
            ("text-delta", "A"),
            ("text-delta", "冒"),
            ("text-delta", "烟"),
            ("text-delta", "B"),
        ]

    def test_reasoning_delta_kind(self) -> None:
        deltas = iter_chunk_deltas(
            _frame("session_event_reasoning_delta.json")["payload"]["event"]
        )
        assert deltas[0].kind == "reasoning-delta"

    def test_malformed_row_is_protocol(self) -> None:
        bad = {
            "type": "text-chunks",
            "seq0": 1,
            "time0": 1,
            "data": {
                "turn": 0,
                "step": 0,
                "index": 0,
                "dt": [1],
                "texts": ["a", "b", "c"],
            },
        }
        with pytest.raises(ProviderError):
            iter_chunk_deltas(bad)


# ------------------------------------------------------------------ RPC
class TestRpcClient:
    def test_prompt_payload_shape_matches_fact_3(self) -> None:
        """session.prompt 请求体逐字段（mode=queue、content text 结构）——spec 验收 4 契约。"""
        captured = {}

        def handler(request) -> Response:
            captured["body"] = json.loads(request.content)
            return Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": captured["body"]["rpcId"],
                    "result": {"ok": True, "value": {"accepted": True}},
                },
            )

        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.prompt").mock(side_effect=handler)
            DshRpcClient(DSH).call(
                "session.prompt",
                {
                    "sessionId": "sess-1",
                    "mode": "queue",
                    "content": [{"type": "text", "text": "任务指令"}],
                },
            )
        payload = captured["body"]["payload"]
        assert payload == {
            "sessionId": "sess-1",
            "mode": "queue",
            "content": [{"type": "text", "text": "任务指令"}],
        }
        assert "clientTimeZone" not in payload  # 可选字段未提供时不发送

    def test_call_envelope_and_value_parse(self) -> None:
        captured = {}

        def handler(request) -> Response:
            captured["body"] = json.loads(request.content)
            return Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": captured["body"]["rpcId"],
                    "result": {"ok": True, "value": {"sessionId": "sess-1"}},
                },
            )

        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.create").mock(side_effect=handler)
            value = DshRpcClient(DSH).call("session.create", {"cwd": "/tmp/proj"})
        assert value == {"sessionId": "sess-1"}
        body = captured["body"]
        assert body["type"] == "client-request"
        assert body["method"] == "session.create"
        assert body["payload"] == {"cwd": "/tmp/proj"}
        assert body["rpcId"]

    def test_business_error_is_http_200_with_ok_false(self) -> None:
        def handler(request: httpx.Request) -> Response:
            body = json.loads(request.content)
            return Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": body["rpcId"],
                    "result": {
                        "ok": False,
                        "error": {
                            "code": "agent-busy",
                            "message": "busy now",
                            "details": {},
                        },
                    },
                },
            )

        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.prompt").mock(side_effect=handler)
            with pytest.raises(ProviderError) as exc:
                DshRpcClient(DSH).call("session.prompt", {"sessionId": "s"})
        assert exc.value.kind == "busy"
        assert exc.value.code == "agent-busy"
        assert "busy now" in exc.value.message

    @pytest.mark.parametrize(
        "code,kind",
        [
            ("session-not-found", "unavailable"),
            ("model-unavailable", "unavailable"),
            ("agent-busy", "busy"),
            ("steer-unavailable", "busy"),
            ("session-conflict", "busy"),
            ("queue-item-not-found", "busy"),
            ("internal", "unavailable"),
            ("bad-request", "protocol"),
            ("invalid-time-zone", "protocol"),
            ("some-future-code", "unavailable"),  # 未知码 → unavailable（默认）
        ],
    )
    def test_error_code_mapping_table(self, code, kind) -> None:
        def handler(request) -> Response:
            body = json.loads(request.content)
            return Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": body["rpcId"],
                    "result": {
                        "ok": False,
                        "error": {"code": code, "message": "m", "details": {}},
                    },
                },
            )

        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.prompt").mock(side_effect=handler)
            with pytest.raises(ProviderError) as exc:
                DshRpcClient(DSH).call("session.prompt", {})
        assert exc.value.kind == kind
        assert exc.value.code == code
        assert "DSH RPC 错误" in exc.value.message

    def test_rpc_id_mismatch_is_protocol(self) -> None:
        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.create").mock(
                return_value=Response(
                    200,
                    json={
                        "type": "server-response",
                        "rpcId": "other",
                        "result": {"ok": True, "value": {}},
                    },
                )
            )
            with pytest.raises(ProviderError) as exc:
                DshRpcClient(DSH).call("session.create", {})
        assert exc.value.kind == "protocol"

    def test_non_json_response_is_protocol(self) -> None:
        with respx.mock(base_url=DSH) as router:
            router.post("/api/session.create").mock(
                return_value=Response(500, text="boom")
            )
            with pytest.raises(ProviderError) as exc:
                DshRpcClient(DSH).call("session.create", {})
        assert exc.value.kind == "protocol"

    def test_respond_question_answer_payload(self) -> None:
        captured = {}

        def handler(request) -> Response:
            captured["body"] = json.loads(request.content)
            return Response(200, json={"accepted": True})

        with respx.mock(base_url=DSH) as router:
            router.post("/api/respond").mock(side_effect=handler)
            DshRpcClient(DSH).respond(
                "q-rpc-1",
                {
                    "sessionId": "sess-1",
                    "answer": {
                        "answers": [
                            {"id": "q-1", "selected": [], "custom": "已批准，请重试"}
                        ]
                    },
                },
            )
        body = captured["body"]
        assert body["type"] == "client-response"
        assert body["rpcId"] == "q-rpc-1"
        assert body["result"]["ok"] is True
        assert (
            body["result"]["value"]["answer"]["answers"][0]["custom"]
            == "已批准，请重试"
        )

    def test_respond_rejected_receipt(self) -> None:
        with respx.mock(base_url=DSH) as router:
            router.post("/api/respond").mock(
                return_value=Response(
                    200, json={"accepted": False, "reason": "bad-response"}
                )
            )
            with pytest.raises(ProviderError) as exc:
                DshRpcClient(DSH).respond(
                    "q-rpc-1", {"sessionId": "s", "answer": {"answers": []}}
                )
        assert "问题应答" in exc.value.message or "应答" in exc.value.message


# ------------------------------------------------------------------ handler
class TestMuxHandler:
    def _handler(self, sync_events=True):
        sink = RecordingSink()
        denied = []
        handler = MuxHandler(
            "sess-1",
            sink,
            on_denied=lambda tool, args, text: denied.append((tool, args, text)),
        )
        return handler, sink, denied

    def test_tool_call_and_result_pairing(self) -> None:
        handler, sink, _ = self._handler()
        handler.feed(parse_frame(json.dumps(_frame("session_event_tool_call.json"))))
        ended = handler.feed(
            parse_frame(json.dumps(_frame("session_event_tool_result_ok.json")))
        )
        assert ended is False
        assert handler.tool_calls == 1
        events = sink.events
        assert events[0] == (
            "tool_call",
            ("get_requirement", {"project_id": "cessna-172", "id": "SMOKE-P5-001"}),
        )
        assert events[1][0] == "tool_result" and events[1][1][1] is True

    def test_denied_result_notifies_and_reports_failure(self) -> None:
        handler, sink, denied = self._handler()
        handler.feed(
            parse_frame(json.dumps(_frame("session_event_tool_call_draft.json")))
        )
        handler.feed(
            parse_frame(json.dumps(_frame("session_event_tool_result_denied.json")))
        )
        assert len(denied) == 1
        tool, args, text = denied[0]
        assert tool == "draft_requirement"
        assert args["project_id"] == "cessna-172"
        assert "ApprovalDeniedError" in text and "approvals add" in text
        result_event = [e for e in sink.events if e[0] == "tool_result"][0]
        assert result_event[1][1] is False

    def test_turn_end_recorded_once(self) -> None:
        handler, sink, _ = self._handler()
        frame = parse_frame(json.dumps(_frame("session_event_turn_end_completed.json")))
        assert handler.feed(frame) is True
        assert handler.feed(frame) is False
        assert handler.turn_end_kind == "completed"
        assert handler.turn_end_reason == "completed"
        assert sink.events[-1] == ("turn_end", "completed")

    def test_other_session_frames_ignored(self) -> None:
        handler, sink, _ = self._handler()
        frame = ParsedFrame(
            rpc_id="x",
            kind="session/event",
            session_id="other",
            payload={"type": "session/event", "sessionId": "other", "event": {}},
        )
        assert handler.feed(frame) is False
        assert handler.tool_calls == 0

    def test_reasoning_folded_by_default(self) -> None:
        handler, sink, _ = self._handler()
        handler.feed(
            parse_frame(json.dumps(_frame("session_event_reasoning_delta.json")))
        )
        assert not any(e[0] == "text" for e in sink.events)


# ------------------------------------------------------------------ status mapping
class TestStatus:
    def test_completed_aborted_else(self) -> None:
        assert _status_for("completed") == "completed"
        assert _status_for("aborted") == "cancelled"
        assert _status_for("error") == "failed"
        assert _status_for("max-tokens") == "failed"
        assert _status_for("blocked") == "failed"


# ------------------------------------------------------------------ run_agentic 集成（respx + 脚本化 WS）
def _rpc_stubs(router, prompt_texts: list[str] | None = None) -> None:
    """session.create / session.prompt 的基础桩（返回 sess-1 / accepted；可捕获 prompt 文本）。"""

    def create_handler(request) -> Response:
        body = json.loads(request.content)
        return Response(
            200,
            json={
                "type": "server-response",
                "rpcId": body["rpcId"],
                "result": {"ok": True, "value": {"sessionId": "sess-1"}},
            },
        )

    router.post("/api/session.create").mock(side_effect=create_handler)

    def prompt_handler(request) -> Response:
        body = json.loads(request.content)
        if prompt_texts is not None:
            prompt_texts.append(body["payload"]["content"][0]["text"])
        return Response(
            200,
            json={
                "type": "server-response",
                "rpcId": body["rpcId"],
                "result": {"ok": True, "value": {"accepted": True}},
            },
        )

    router.post("/api/session.prompt").mock(side_effect=prompt_handler)


class TestRunAgentic:
    def _provider(
        self, ws, *, question_answerer=None, on_denied=None, **settings_overrides
    ):
        on_session: list[str] = []
        denied: list[tuple] = []

        def factory(url):
            assert url == "ws://dsh.local/api/events.mux"
            return ws

        provider = DshProvider(
            _settings(**settings_overrides),
            ws_factory=factory,
            question_answerer=question_answerer,
            on_session=lambda sid: on_session.append(sid),
            on_denied=on_denied
            or (lambda tool, args, text: denied.append((tool, args, text))),
            warning=lambda text: None,
            poll_interval=0.01,
        )
        return provider, on_session, denied

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        prompt_texts: list[str] = []
        with respx.mock(base_url=DSH) as router:
            _rpc_stubs(router, prompt_texts)
            router.post("/api/session.list").mock(
                side_effect=[
                    _echo_ok(
                        json.loads(
                            (FIXTURES / "session_list_running.json").read_text("utf-8")
                        )
                    ),
                    _echo_ok(
                        json.loads(
                            (FIXTURES / "session_list_idle.json").read_text("utf-8")
                        )
                    ),
                ]
            )
            ws = ScriptedWs(_lines(FIXTURES / "ws_stream_happy.jsonl"))
            provider, on_session, denied = self._provider(ws)
            sink = RecordingSink()
            result = await provider.run_agentic(
                _request(), sink, cancel=threading.Event()
            )
        assert result.status == "completed"
        assert result.tool_calls == 1
        assert result.questions == 0
        assert result.final_text == "好的，开始处理。任务完成"
        assert on_session == ["sess-1"]
        assert denied == []
        prompt = prompt_texts[0]
        assert "你是 reqmesh-harness 的内置 agent" in prompt
        assert "任务：用自然语言建一条需求" in prompt

    @pytest.mark.asyncio
    async def test_denied_approved_flow_and_respond_shape(self) -> None:
        responds: list[dict] = []

        def respond_handler(request) -> Response:
            responds.append(json.loads(request.content))
            return Response(200, json={"accepted": True})

        with respx.mock(base_url=DSH) as router:
            _rpc_stubs(router)
            router.post("/api/session.list").mock(
                side_effect=_echo_ok(
                    json.loads((FIXTURES / "session_list_idle.json").read_text("utf-8"))
                )
            )
            router.post("/api/respond").mock(side_effect=respond_handler)
            ws = ScriptedWs(_lines(FIXTURES / "ws_stream_denied_approved.jsonl"))
            provider, _, denied = self._provider(
                ws, question_answerer=lambda q: "已批准，请重试"
            )
            sink = RecordingSink()
            result = await provider.run_agentic(
                _request(), sink, cancel=threading.Event()
            )
        # ① 拒绝通知（tool+args+错误文本）
        assert len(denied) == 1
        assert denied[0][0] == "draft_requirement"
        assert denied[0][1]["project_id"] == "cessna-172"
        assert "ApprovalDeniedError" in denied[0][2]
        # ② 问题应答（respond 客户端响应形状）
        assert len(responds) == 1
        body = responds[0]
        assert body["type"] == "client-response"
        assert body["rpcId"] == "q-rpc-1"
        answer = body["result"]["value"]
        assert answer["sessionId"] == "sess-1"
        assert answer["answer"]["answers"] == [
            {"id": "q-1", "selected": [], "custom": "已批准，请重试"}
        ]
        # ③ 重试后 approved：工具调用 2 次、问题 1 次、completed
        assert result.status == "completed"
        assert result.tool_calls == 2
        assert result.questions == 1
        calls = [e for e in sink.events if e[0] == "tool_call"]
        assert [c[1][0] for c in calls] == ["draft_requirement", "draft_requirement"]
        assert any(e[0] == "question" for e in sink.events)

    @pytest.mark.asyncio
    async def test_idle_timeout(self) -> None:
        with respx.mock(base_url=DSH) as router:
            _rpc_stubs(router)
            ws = ScriptedWs(
                [json.dumps(_frame("session_subscribed.json"))], hang_after=1
            )
            provider, *_ = self._provider(ws, dsh_idle_timeout=0.05)
            with pytest.raises(ProviderError) as exc:
                await provider.run_agentic(
                    _request(), RecordingSink(), cancel=threading.Event()
                )
        assert exc.value.kind == "timeout"
        assert "空闲超时" in exc.value.message

    @pytest.mark.asyncio
    async def test_stream_ends_without_turn_end_is_timeout(self) -> None:
        with respx.mock(base_url=DSH, assert_all_called=False) as router:
            _rpc_stubs(router)
            router.post("/api/session.list").mock(
                side_effect=_echo_ok(
                    json.loads((FIXTURES / "session_list_idle.json").read_text("utf-8"))
                )
            )
            ws = ScriptedWs([json.dumps(_frame("session_subscribed.json"))])
            provider, *_ = self._provider(ws)
            with pytest.raises(ProviderError) as exc:
                await provider.run_agentic(
                    _request(), RecordingSink(), cancel=threading.Event()
                )
        assert exc.value.kind == "timeout"
        assert "未收到 turn/end" in exc.value.message

    @pytest.mark.asyncio
    async def test_cancel_sends_session_cancel(self) -> None:
        cancel_bodies: list[dict] = []

        def cancel_handler(request) -> Response:
            body = json.loads(request.content)
            cancel_bodies.append(body)
            return Response(
                200,
                json={
                    "type": "server-response",
                    "rpcId": body["rpcId"],
                    "result": {"ok": True, "value": {"accepted": True}},
                },
            )

        with respx.mock(base_url=DSH, assert_all_called=False) as router:
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
            router.post("/api/session.cancel").mock(side_effect=cancel_handler)
            ws = ScriptedWs(
                [json.dumps(_frame("session_subscribed.json"))], hang_after=1
            )
            event = threading.Event()

            def cancel_when_session_registered(session_id: str) -> None:
                event.set()

            provider = DshProvider(
                _settings(),
                ws_factory=lambda url: ws,
                on_session=cancel_when_session_registered,  # session 注册即置位 cancel（模拟 Ctrl-C）
                on_denied=lambda *a: None,
                poll_interval=0.01,
            )
            result = await provider.run_agentic(
                _request(), RecordingSink(), cancel=event
            )
        assert result.status == "cancelled"
        assert len(cancel_bodies) == 1
        assert cancel_bodies[0]["method"] == "session.cancel"
        assert cancel_bodies[0]["payload"] == {"sessionId": "sess-1"}

    @pytest.mark.asyncio
    async def test_stream_error_maps_to_provider_error(self) -> None:
        with respx.mock(base_url=DSH) as router:
            _rpc_stubs(router)
            ws = ScriptedWs([json.dumps(_frame("stream_error_internal.json"))])
            provider, *_ = self._provider(ws)
            with pytest.raises(ProviderError) as exc:
                await provider.run_agentic(
                    _request(), RecordingSink(), cancel=threading.Event()
                )
        assert exc.value.kind == "unavailable"
        assert exc.value.code == "internal"


def _request():
    from reqmesh_harness.runtime.provider import AgentRequest

    return AgentRequest(
        task="用自然语言建一条需求", project_context=None, history=[], tools=[]
    )


def test_ws_url_scheme_rewrite() -> None:
    assert ws_url("http://127.0.0.1:8080") == "ws://127.0.0.1:8080/api/events.mux"
    assert ws_url("https://host.example") == "wss://host.example/api/events.mux"
