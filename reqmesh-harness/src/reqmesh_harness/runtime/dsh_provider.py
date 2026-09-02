"""DSH provider 适配器（委托式，spec ②/开放问题②）：loopback RPC + WS events.mux。

- 信封契约（事实 1–3）：`POST /api/<method>` client-request/server-response；
  `session.create({cwd})` → sessionId；`session.prompt({sessionId, mode:"queue", content:[…]})`
  → accepted；业务错误也是 HTTP 200 + ok:false；`POST /api/respond` client-response；
- 事件流（事实 4）：本机宿主 `events.mux` 为 **WebSocket-only**（GET 实测 426——
  与 design D10 的 SSE 表述不符，按 spec 事实 4 走 WS）；帧 = server-request 信封 +
  MuxFrame payload（10 种判别）；SessionEvent 严格信封 + 宽 data；
- 完成判定（事实 5/验收 5）：`turn/end` + `session.list` running=false 两条件齐备；
- 空闲超时 `REQMESH_DSH_IDLE_TIMEOUT`（自最后一帧起计）；`cancel` 事件 → session.cancel；
- 问题帧（question/requested）：经注入的 answerer（run 层确认中继）应答；
  DSH 原生 approval/requested **不代答**（警告并继续——MCP 工具不触发它，触发即违规）。
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..config import Settings, get_settings
from ..errors import ProviderError
from .loop import compose_prompt, is_denied_error
from .provider import AgentRequest, Question, QuestionOption, RunResult, StreamSink

# MuxFrame 判别 10 种（dsh-host-apiproxy events.schema.js muxFrameSchema）
MUX_FRAME_TYPES = frozenset(
    {
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
)

# rpcError code → ProviderError.kind（spec 事实 6 映射表；未知码默认 unavailable）
_RPC_KIND: dict[str, str] = {
    "session-not-found": "unavailable",
    "model-unavailable": "unavailable",
    "agent-busy": "busy",
    "steer-unavailable": "busy",
    "session-conflict": "busy",
    "queue-item-not-found": "busy",
    "internal": "unavailable",
    "bad-request": "protocol",
    "invalid-time-zone": "protocol",
}


def ws_url(base_url: str) -> str:
    """DSH base URL → events.mux WebSocket URL（http→ws/https→wss）。"""
    parts = urlsplit(base_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, "/api/events.mux", "", ""))


@dataclass(frozen=True)
class ParsedFrame:
    rpc_id: str
    kind: str
    session_id: str | None
    payload: dict


def parse_frame(text: str) -> ParsedFrame:
    """WS 帧解析：server-request 信封 + MuxFrame 判别（10 种；未知帧 type 即协议错误）。"""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProviderError("protocol", f"DSH WS 帧不是 JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("type") != "server-request":
        raise ProviderError("protocol", "DSH WS 帧信封不符合 server-request")
    payload = data.get("payload")
    if not isinstance(payload, dict) or not isinstance(payload.get("type"), str):
        raise ProviderError("protocol", "DSH WS 帧缺 payload.type（MuxFrame 判别）")
    kind = payload["type"]
    if kind not in MUX_FRAME_TYPES:
        raise ProviderError("protocol", f"未知 MuxFrame 类型: {kind!r}")
    session_id = payload.get("sessionId")
    if session_id is not None and not isinstance(session_id, str):
        raise ProviderError("protocol", "MuxFrame sessionId 非法")
    return ParsedFrame(
        rpc_id=str(data.get("rpcId") or ""),
        kind=kind,
        session_id=session_id,
        payload=payload,
    )


@dataclass(frozen=True)
class ChunkDelta:
    kind: Literal["text-delta", "reasoning-delta", "tool-call-delta"]
    text: str = ""
    arguments_delta: str = ""
    index: int = 0
    call_id: str = ""
    name: str | None = None


def iter_chunk_deltas(event: dict) -> list[ChunkDelta]:
    """把事件展开为 delta 序列：live `assistant/chunk`（text/reasoning/tool-call-delta）
    或存储打包行 `text-chunks`/`reasoning-chunks`/`tool-call-chunks`（事实 4：须按行展开）。
    打包行形状非法 → ProviderError(protocol)（fail-loud，绝不静默丢整段）。"""
    typ = event.get("type")
    if typ == "assistant/chunk":
        data = event.get("data") or {}
        chunk = data.get("chunk") or {}
        ctype = chunk.get("type")
        if ctype == "text-delta":
            return [ChunkDelta("text-delta", text=str(chunk.get("text", "")))]
        if ctype == "reasoning-delta":
            return [ChunkDelta("reasoning-delta", text=str(chunk.get("text", "")))]
        if ctype == "tool-call-delta":
            return [
                ChunkDelta(
                    "tool-call-delta",
                    arguments_delta=str(chunk.get("argumentsDelta", "")),
                    index=int(chunk.get("index", 0)),
                    call_id=str(chunk.get("id", "")),
                    name=(
                        chunk.get("name")
                        if isinstance(chunk.get("name"), str)
                        else None
                    ),
                )
            ]
        return []  # block-start/end、usage、finish 等：无文本增量
    if typ in ("text-chunks", "reasoning-chunks"):
        data = event.get("data") or {}
        texts = data.get("texts")
        dt = data.get("dt")
        if (
            not isinstance(texts, list)
            or not all(isinstance(t, str) for t in texts)
            or not isinstance(dt, list)
            or len(dt) != len(texts) - 1
        ):
            raise ProviderError(
                "protocol", f"chunk 打包行形状非法: {typ}（texts/dt 不匹配）"
            )
        kind = "text-delta" if typ == "text-chunks" else "reasoning-delta"
        return [ChunkDelta(kind, text=t) for t in texts]
    if typ == "tool-call-chunks":
        data = event.get("data") or {}
        args = data.get("args")
        dt = data.get("dt")
        if (
            not isinstance(args, list)
            or not all(isinstance(a, str) for a in args)
            or not isinstance(dt, list)
            or len(dt) != len(args) - 1
        ):
            raise ProviderError(
                "protocol", "tool-call-chunks 打包行形状非法（args/dt 不匹配）"
            )
        name = data.get("name") if isinstance(data.get("name"), str) else None
        return [
            ChunkDelta(
                "tool-call-delta",
                arguments_delta=a,
                index=int(data.get("index", 0)),
                call_id=str(data.get("id", "")),
                name=name,
            )
            for a in args
        ]
    return []


def tool_result_of(event: dict) -> tuple[bool, str]:
    """tool/result 事件 → (isError, 文本)；文本为 tool-result block 的 text 块拼接。"""
    data = event.get("data") or {}
    message = data.get("message") or {}
    content = message.get("content") if isinstance(message, dict) else None
    block = (
        content[0]
        if isinstance(content, list) and content and isinstance(content[0], dict)
        else {}
    )
    is_error = bool(block.get("isError")) or bool(data.get("error"))
    text = ""
    for part in block.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "text":
            text += str(part.get("text", ""))
    return is_error, text


def _status_for(turn_end_kind: str) -> str:
    if turn_end_kind == "completed":
        return "completed"
    if turn_end_kind == "aborted":
        return "cancelled"
    return "failed"


def _questions_of(payload: dict) -> list[Question]:
    raw = payload.get("questions")
    if not isinstance(raw, list):
        raise ProviderError("protocol", "question/requested 帧缺 questions 列表")
    out: list[Question] = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("question"), str)
        ):
            raise ProviderError("protocol", "question/requested 帧条目形状非法")
        options = tuple(
            QuestionOption(label=str(opt["label"]), description=opt.get("description"))
            for opt in (item.get("options") or [])
            if isinstance(opt, dict) and isinstance(opt.get("label"), str)
        )
        out.append(
            Question(
                id=item["id"],
                question=item["question"],
                header=(
                    item.get("header") if isinstance(item.get("header"), str) else None
                ),
                detail=(
                    item.get("detail") if isinstance(item.get("detail"), str) else None
                ),
                options=options,
                multi_select=bool(item.get("multiSelect")),
            )
        )
    return out


def _rpc_provider_error(error: dict) -> ProviderError:
    code = str(error.get("code") or "internal")
    message = str(error.get("message") or "未提供详情")
    kind = _RPC_KIND.get(code, "unavailable")
    return ProviderError(kind, f"DSH RPC 错误（{code}）：{message}", code=code)


class DshRpcClient:
    """loopback RPC 客户端（无凭据；承载层 404/415/400 与业务错误区分，业务错误归一）。"""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def call(self, method: str, payload: dict | None = None) -> Any:
        rpc_id = f"reqmesh-harness-{secrets.token_hex(4)}"
        body = {
            "type": "client-request",
            "rpcId": rpc_id,
            "method": method,
            "payload": payload or {},
        }
        try:
            response = self._client.post(f"/api/{method}", json=body)
        except httpx.TransportError as exc:
            raise ProviderError("unavailable", f"DSH 宿主不可达: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                "protocol",
                f"DSH RPC 响应非 JSON（HTTP {response.status_code}，载体层错误）",
            ) from exc
        if not isinstance(data, dict) or data.get("type") != "server-response":
            raise ProviderError("protocol", "DSH RPC 响应信封不符合 server-response")
        if data.get("rpcId") != rpc_id:
            raise ProviderError("protocol", "DSH RPC rpcId 与请求不匹配")
        result = data.get("result")
        if not isinstance(result, dict):
            raise ProviderError("protocol", "DSH RPC 响应缺 result")
        if result.get("ok") is True:
            return result.get("value")
        error = result.get("error")
        if not isinstance(error, dict):
            raise ProviderError("protocol", "DSH RPC ok=false 但缺 error 对象")
        raise _rpc_provider_error(error)

    def respond(self, rpc_id: str, value: dict) -> None:
        """client-response 应答；宿主拒绝（accepted=false）→ ProviderError(protocol)。"""
        body = {
            "type": "client-response",
            "rpcId": rpc_id,
            "result": {"ok": True, "value": value},
        }
        try:
            response = self._client.post("/api/respond", json=body)
        except httpx.TransportError as exc:
            raise ProviderError("unavailable", f"DSH 宿主不可达: {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("protocol", "respond 响应非 JSON") from exc
        if not isinstance(data, dict) or data.get("accepted") is not True:
            reason = data.get("reason") if isinstance(data, dict) else None
            raise ProviderError(
                "protocol", f"问题应答未被 DSH 宿主接受（{reason or 'accepted=false'}）"
            )


class MuxHandler:
    """会话内事件处理：文本流（reasoning 折叠，--show-reasoning 展开）、工具事件配对
    （callId→name/args）、审批拒绝通知、turn/end 记录。question/approval 帧由 provider 层处理。"""

    def __init__(
        self,
        session_id: str,
        sink: StreamSink,
        *,
        show_reasoning: bool = False,
        on_denied: Callable[[str, dict, str], None] | None = None,
    ) -> None:
        self._session_id = session_id
        self._sink = sink
        self._show_reasoning = show_reasoning
        self._on_denied = on_denied
        self._calls: dict[str, tuple[str, dict]] = {}
        self._texts: list[str] = []
        self.turn_end_kind: str | None = None
        self.turn_end_reason: str = ""
        self.tool_calls = 0
        self.questions = 0

    @property
    def visible_text(self) -> str:
        return "".join(self._texts)

    def feed(self, frame: ParsedFrame) -> bool:
        """处理一帧；返回本次是否出现 turn/end（一次性）。"""
        if frame.session_id != self._session_id:
            return False
        if frame.kind != "session/event":
            return False
        event = frame.payload.get("event") or {}
        typ = event.get("type")
        if typ in (
            "assistant/chunk",
            "text-chunks",
            "reasoning-chunks",
            "tool-call-chunks",
        ):
            for delta in iter_chunk_deltas(event):
                if delta.kind == "text-delta":
                    self._texts.append(delta.text)
                    self._sink.on_text(delta.text)
                elif delta.kind == "reasoning-delta" and self._show_reasoning:
                    self._sink.on_text(delta.text)
            return False
        if typ == "tool/call":
            data = event.get("data") or {}
            call_id = str(data.get("callId") or "")
            name = str(data.get("name") or "")
            raw_args = data.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else {}
            except ValueError:
                args = {}
            args = args if isinstance(args, dict) else {}
            self._calls[call_id] = (name, args)
            self._sink.on_tool_call(name, args)
            self.tool_calls += 1
            return False
        if typ == "tool/result":
            data = event.get("data") or {}
            message = data.get("message") or {}
            block = (
                (message.get("content") or [{}])[0] if isinstance(message, dict) else {}
            )
            call_id = str(
                (block.get("toolCallId") if isinstance(block, dict) else None)
                or (
                    (message.get("source") or {}).get("tool", {}).get("callId")
                    if isinstance(message, dict)
                    else None
                )
                or ""
            )
            is_error, text = tool_result_of(event)
            name, args = self._calls.get(call_id, (call_id, {}))
            self._sink.on_tool_result(name, not is_error, text or "（空结果）")
            if is_error and is_denied_error(text) and self._on_denied is not None:
                self._on_denied(name, args, text)
            return False
        if typ == "turn/end":
            data = event.get("data") or {}
            reason = data.get("reason")
            kind = reason.get("kind") if isinstance(reason, dict) else None
            if self.turn_end_kind is None:
                self.turn_end_kind = str(kind or "unknown")
                self.turn_end_reason = self.turn_end_kind
                self._sink.on_turn_end(self.turn_end_reason)
                return True
            return False
        return False


def _default_answerer(q: Question) -> str:
    return "用户拒绝了该操作，请放弃并继续。"  # 无中继注入时的安全默认（拒绝语义）


class DshProvider:
    """DSH 委托式 provider：session.create → prompt → WS 帧循环 → 完成判定（事实 1–5）。"""

    name = "dsh"
    execution: Literal["delegated"] = "delegated"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: DshRpcClient | None = None,
        ws_factory: Callable[[str], Any] | None = None,
        question_answerer: Callable[[Question], str] | None = None,
        on_session: Callable[[str], None] | None = None,
        on_denied: Callable[[str, dict, str], None] | None = None,
        warning: Callable[[str], None] | None = None,
        show_reasoning: bool | None = None,
        poll_interval: float = 0.3,
        dsh_session_id: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._rpc = client or DshRpcClient(self.settings.dsh_url)
        self._ws_factory = ws_factory or _default_ws_factory
        self._answerer = question_answerer or _default_answerer
        self._on_session = on_session
        self._on_denied = on_denied
        self._warning = warning or (lambda text: None)
        self._show_reasoning = (
            show_reasoning
            if show_reasoning is not None
            else self.settings.show_reasoning
        )
        self._poll_interval = poll_interval
        self._resume_session_id = dsh_session_id
        self._last_session_id: str | None = None

    def steer(self, text: str) -> None:
        """TTY /steer：向运行中的 DSH session 注入指导（session.prompt mode=steer，spec ④）。"""
        if not self._last_session_id:
            raise ProviderError("busy", "无可 steer 的 DSH session（run 尚未创建会话）")
        self._rpc.call(
            "session.prompt",
            {
                "sessionId": self._last_session_id,
                "mode": "steer",
                "content": [{"type": "text", "text": text}],
            },
        )

    def cancel_remote(self) -> None:
        """Ctrl-C 兜底：主线程异常路径下通知宿主取消（尽力而为；运行内 cancel 由事件循环处理）。"""
        if self._last_session_id:
            try:
                self._rpc.call("session.cancel", {"sessionId": self._last_session_id})
            except ProviderError:
                pass

    async def run_agentic(
        self, request: AgentRequest, sink: StreamSink, *, cancel: threading.Event
    ) -> RunResult:
        try:
            return await self._run(request, sink, cancel)
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"DSH 宿主不可达: {exc}") from exc

    # ------------------------------------------------------------------ 内部
    async def _run(
        self, request: AgentRequest, sink: StreamSink, cancel: threading.Event
    ) -> RunResult:
        if cancel.is_set():
            return RunResult("cancelled", "", 0, 0, None)
        if self._resume_session_id is not None:
            session_id = (
                self._resume_session_id
            )  # resume 分支①：沿用存活 DSH 会话（原生历史）
        else:
            created = self._rpc.call(
                "session.create", {"cwd": self.settings.dsh_cwd or os.getcwd()}
            )
            if not isinstance(created, dict) or not isinstance(
                created.get("sessionId"), str
            ):
                raise ProviderError(
                    "protocol", "session.create 响应缺 sessionId", code="bad-request"
                )
            session_id = created["sessionId"]
        self._last_session_id = session_id
        if self._on_session is not None:
            self._on_session(session_id)

        handler = MuxHandler(
            session_id,
            sink,
            show_reasoning=self._show_reasoning,
            on_denied=self._on_denied,
        )
        if cancel.is_set():
            return self._cancel(session_id, handler)

        accepted = self._rpc.call(
            "session.prompt",
            {
                "sessionId": session_id,
                "mode": "queue",
                "content": [{"type": "text", "text": compose_prompt(request)}],
            },
        )
        if not isinstance(accepted, dict) or accepted.get("accepted") is not True:
            raise ProviderError(
                "protocol", "session.prompt 未被宿主接受", code="bad-request"
            )

        turn_ended = False
        try:
            async with self._ws_factory(ws_url(self.settings.dsh_url)) as conn:
                iterator = conn.__aiter__()
                while True:
                    if cancel.is_set():
                        return self._cancel(session_id, handler)
                    try:
                        raw = await asyncio.wait_for(
                            anext(iterator), timeout=self.settings.dsh_idle_timeout
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        raise ProviderError(
                            "timeout",
                            f"DSH 事件流空闲超时（{self.settings.dsh_idle_timeout:.0f}s 无帧）",
                            code="idle-timeout",
                        ) from None
                    frame = parse_frame(raw)
                    if frame.session_id is not None and frame.session_id != session_id:
                        continue
                    if frame.kind == "stream/error":
                        error = frame.payload.get("error")
                        if not isinstance(error, dict):
                            error = {}
                        raise _rpc_provider_error(error)
                    if frame.kind == "session/event":
                        if handler.feed(frame):
                            turn_ended = True
                    elif frame.kind == "question/requested":
                        answers = []
                        for question in _questions_of(frame.payload):
                            sink.on_question(question)
                            answers.append(
                                {
                                    "id": question.id,
                                    "selected": [],
                                    "custom": self._answerer(question),
                                }
                            )
                        if answers:
                            self._rpc.respond(
                                frame.rpc_id,
                                {
                                    "sessionId": session_id,
                                    "answer": {"answers": answers},
                                },
                            )
                        handler.questions += len(answers)
                    elif frame.kind == "approval/requested":
                        self._warning(
                            "警告：DSH 会话触发了原生审批请求"
                            f"（tool={frame.payload.get('toolName')}）；harness 不代答——"
                            "任务指令只允许 mcp__reqmesh__* 工具，出现该帧说明 agent 违规。"
                        )
                    # 其余帧类型（subscribed/queue/jobs/projection/resolved）：忽略
                    if turn_ended:
                        break
        except ProviderError:
            raise
        except (
            Exception
        ) as exc:  # WS 层断流（websockets ConnectionClosed / OSError 族）
            if not turn_ended and handler.turn_end_kind is None:
                raise ProviderError("unavailable", f"DSH WS 连接断开: {exc}") from exc

        if handler.turn_end_kind is None:
            # 流结束但无 turn/end：turn/end 是完成判定的必要条件（事实 5）
            raise ProviderError(
                "timeout", "事件流结束但未收到 turn/end", code="stream-end"
            )
        idle = await self._await_idle(session_id, handler, cancel)
        if idle == "cancelled":
            return RunResult(
                "cancelled",
                handler.visible_text,
                handler.tool_calls,
                handler.questions,
                None,
            )
        return RunResult(
            _status_for(handler.turn_end_kind),
            handler.visible_text,
            handler.tool_calls,
            handler.questions,
            None,
        )

    def _cancel(self, session_id: str, handler: MuxHandler) -> RunResult:
        self._rpc.call("session.cancel", {"sessionId": session_id})
        return RunResult(
            "cancelled",
            handler.visible_text,
            handler.tool_calls,
            handler.questions,
            None,
        )

    async def _await_idle(
        self, session_id: str, handler: MuxHandler, cancel: threading.Event
    ) -> str:
        """完成判定第二步：轮询 session.list 直至 running=false；返回 "idle"|"cancelled"。"""
        deadline = time.monotonic() + max(self.settings.dsh_idle_timeout, 1.0)
        while True:
            if cancel.is_set():
                self._rpc.call("session.cancel", {"sessionId": session_id})
                return "cancelled"
            value = self._rpc.call("session.list", {})
            running = _running_of(value, session_id)
            if running is False:
                return "idle"
            if time.monotonic() > deadline:
                raise ProviderError(
                    "timeout",
                    f"turn/end 后 {self.settings.dsh_idle_timeout:.0f}s 内宿主未转为空闲",
                    code="idle-timeout",
                )
            await asyncio.sleep(self._poll_interval)


def _running_of(value: Any, session_id: str) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ProviderError("protocol", "session.list 响应形状非法（缺 items）")
    for item in value["items"]:
        if isinstance(item, dict) and item.get("sessionId") == session_id:
            return bool(item.get("running", False))
    raise ProviderError(
        "unavailable",
        f"DSH session 不存在于宿主: {session_id}",
        code="session-not-found",
    )


def _default_ws_factory(url: str):
    import websockets

    return websockets.connect(url)


__all__ = [
    "ChunkDelta",
    "DshProvider",
    "DshRpcClient",
    "MUX_FRAME_TYPES",
    "MuxHandler",
    "ParsedFrame",
    "iter_chunk_deltas",
    "parse_frame",
    "tool_result_of",
    "ws_url",
    "_status_for",
]
