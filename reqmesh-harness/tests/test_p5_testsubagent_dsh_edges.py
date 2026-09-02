"""P5 测试子代理补充用例（DSH 适配器边缘）：spec 事实 1–4 / 验收 4/5 的未覆盖分支。

- session.prompt 载荷逐字段（mode=queue / content 结构 / clientTimeZone 缺省）；
- session.list 找不到会话（_running_of → ProviderError session-not-found）；
- question/requested 多问题帧逐 id 应答（一个 respond、逐 id custom）；
- approval/requested 帧不代答（warning 而非 respond；agent 违规用 bash 时）；
- --show-reasoning 展开 reasoning-delta（默认折叠已测）。

复用 tests/test_dsh_provider 的离线夹具/脚本化 WS；全离线（respx + 脚本 WS）。
"""

from __future__ import annotations

import json
import threading

import pytest
import respx
from httpx import Response

from reqmesh_harness.errors import ProviderError
from reqmesh_harness.runtime.dsh_provider import (
    DshProvider,
    MuxHandler,
    _running_of,
    parse_frame,
)

from tests.test_dsh_provider import (
    DSH,
    FIXTURES,
    ScriptedWs,
    RecordingSink,
    _echo_ok,
    _frame,
    _request,
    _rpc_stubs,
    _settings,
)


def _idle_list() -> dict:
    return json.loads((FIXTURES / "session_list_idle.json").read_text("utf-8"))


# ------------------------------------------------------------------ session.prompt 载荷逐字段
@pytest.mark.asyncio
async def test_session_prompt_payload_field_by_field() -> None:
    captured: dict = {}

    with respx.mock(base_url=DSH) as router:
        router.post("/api/session.create").mock(
            side_effect=lambda req: Response(200, json={
                "type": "server-response", "rpcId": json.loads(req.content)["rpcId"],
                "result": {"ok": True, "value": {"sessionId": "sess-1"}}}))

        def prompt_handler(request) -> Response:
            captured["body"] = json.loads(request.content)
            return Response(200, json={"type": "server-response",
                                       "rpcId": captured["body"]["rpcId"],
                                       "result": {"ok": True, "value": {"accepted": True}}})

        router.post("/api/session.prompt").mock(side_effect=prompt_handler)
        router.post("/api/session.list").mock(side_effect=_echo_ok(_idle_list()))
        ws = ScriptedWs([json.dumps(_frame("session_event_turn_end_completed.json"))])
        provider = DshProvider(_settings(), ws_factory=lambda url: ws, poll_interval=0.01)
        result = await provider.run_agentic(_request(), RecordingSink(), cancel=threading.Event())

    assert result.status == "completed"
    payload = captured["body"]["payload"]
    # 逐字段：session.prompt 载荷只含三键（sessionId/mode/content），clientTimeZone 缺省（spec 事实 3）
    assert set(payload.keys()) == {"sessionId", "mode", "content"}
    assert payload["sessionId"] == "sess-1"
    assert payload["mode"] == "queue"
    assert "clientTimeZone" not in payload
    assert len(payload["content"]) == 1
    assert payload["content"][0]["type"] == "text"
    assert isinstance(payload["content"][0]["text"], str)
    assert "任务：" in payload["content"][0]["text"]


# ------------------------------------------------------------------ session.list 找不到会话
def test_running_of_missing_session_raises_session_not_found() -> None:
    value = {"items": [{"sessionId": "other", "running": False}]}
    with pytest.raises(ProviderError) as exc:
        _running_of(value, "sess-1")
    assert exc.value.kind == "unavailable"
    assert exc.value.code == "session-not-found"


def test_running_of_running_true_and_false() -> None:
    assert _running_of({"items": [{"sessionId": "s", "running": True}]}, "s") is True
    assert _running_of({"items": [{"sessionId": "s", "running": False}]}, "s") is False


def test_running_of_non_list_items_is_protocol() -> None:
    with pytest.raises(ProviderError) as exc:
        _running_of({"items": "not-a-list"}, "s")
    assert exc.value.kind == "protocol"


# ------------------------------------------------------------------ 多问题帧逐 id 应答
@pytest.mark.asyncio
async def test_question_requested_multi_question_per_id_answer() -> None:
    responds: list[dict] = []

    def respond_handler(request) -> Response:
        responds.append(json.loads(request.content))
        return Response(200, json={"accepted": True})

    multi = {
        "type": "server-request", "rpcId": "q-rpc-multi", "method": "question/requested",
        "payload": {"type": "question/requested", "sessionId": "sess-1",
                    "questions": [
                        {"id": "q-1", "question": "问题一？"},
                        {"id": "q-2", "question": "问题二？", "header": "H",
                         "options": [{"label": "a"}]},
                    ]},
    }
    with respx.mock(base_url=DSH) as router:
        _rpc_stubs(router)
        router.post("/api/session.list").mock(side_effect=_echo_ok(_idle_list()))
        router.post("/api/respond").mock(side_effect=respond_handler)
        ws = ScriptedWs([
            json.dumps(_frame("session_subscribed.json")),
            json.dumps(multi),
            json.dumps(_frame("session_event_turn_end_completed.json")),
        ])
        provider = DshProvider(
            _settings(), ws_factory=lambda url: ws,
            question_answerer=lambda q: f"答复:{q.id}", poll_interval=0.01,
        )
        sink = RecordingSink()
        result = await provider.run_agentic(_request(), sink, cancel=threading.Event())

    assert result.status == "completed"
    assert result.questions == 2
    # 一个 respond 帧、逐 id custom 应答（spec 事实 7：question 应答按 id 校验）
    assert len(responds) == 1
    body = responds[0]
    assert body["rpcId"] == "q-rpc-multi"
    answers = body["result"]["value"]["answer"]["answers"]
    assert [a["id"] for a in answers] == ["q-1", "q-2"]
    assert [a["custom"] for a in answers] == ["答复:q-1", "答复:q-2"]
    assert all(a["selected"] == [] for a in answers)
    # sink.on_question 逐 id 通知
    qs = [e[1] for e in sink.events if e[0] == "question"]
    assert [q.id for q in qs] == ["q-1", "q-2"]


# ------------------------------------------------------------------ approval/requested 不代答
@pytest.mark.asyncio
async def test_approval_requested_warns_and_does_not_respond() -> None:
    warnings: list[str] = []
    respond_calls: list = []

    def respond_handler(request) -> Response:
        respond_calls.append(request)
        return Response(200, json={"accepted": True})

    with respx.mock(base_url=DSH, assert_all_called=False) as router:
        _rpc_stubs(router)
        router.post("/api/session.list").mock(side_effect=_echo_ok(_idle_list()))
        router.post("/api/respond").mock(side_effect=respond_handler)
        ws = ScriptedWs([
            json.dumps(_frame("session_subscribed.json")),
            json.dumps(_frame("approval_requested.json")),
            json.dumps(_frame("session_event_turn_end_completed.json")),
        ])
        provider = DshProvider(
            _settings(), ws_factory=lambda url: ws,
            warning=lambda text: warnings.append(text), poll_interval=0.01,
        )
        result = await provider.run_agentic(_request(), RecordingSink(), cancel=threading.Event())

    assert result.status == "completed"  # 帧被跳过、run 继续（不代答、不阻断）
    assert respond_calls == []  # 绝不代答 DSH 原生 approval
    assert warnings and any("原生审批" in w for w in warnings)


# ------------------------------------------------------------------ --show-reasoning 展开
def test_show_reasoning_expands_reasoning_delta() -> None:
    sink = RecordingSink()
    handler = MuxHandler("sess-1", sink, show_reasoning=True)
    frame = parse_frame(json.dumps(_frame("session_event_reasoning_delta.json")))
    handler.feed(frame)
    texts = [e[1] for e in sink.events if e[0] == "text"]
    assert texts == ["（思考）"]


def test_reasoning_still_folded_when_show_reasoning_false() -> None:
    sink = RecordingSink()
    handler = MuxHandler("sess-1", sink, show_reasoning=False)
    frame = parse_frame(json.dumps(_frame("session_event_reasoning_delta.json")))
    handler.feed(frame)
    assert not any(e[0] == "text" for e in sink.events)
