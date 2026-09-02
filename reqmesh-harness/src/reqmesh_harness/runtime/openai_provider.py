"""OpenAI 兼容 provider（自驱 tool-loop，spec ②/开放问题②；#42）。

- tools：`export_openai_functions(registry)`（ADR-0001 预留消费面；40 工具 1:1）；
- 请求：system=任务指令（与 DSH 路线的指令同文不同位——DSH 无 system 通道，指令放
  首条 user content 开头，spec ②）+ history + user=任务；stream=True（SSE）；
- 流式解析：`choices[0].delta.content` 逐块 + `delta.tool_calls` 按 index 累积
  （arguments 分片拼接）；`data: [DONE]` 结束；任何一行非法 → ProviderError(protocol)；
- 工具执行：harness 自驱 executor 注入（RunDriver 对 tool-loop provider 统一注入），
  结果以 `role:tool` 消息回灌下一请求；防御轮数 `max_rounds`（超出 → ProviderError(protocol)）；
- 错误归一：无 key → ProviderError(unavailable)（发出请求前即报）；HTTP/连接错误同归
  unavailable；取消：模型调用间检查 cancel → RunResult(cancelled)。
"""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx

from ..config import Settings, get_settings
from ..errors import ProviderError
from ..tools import build_registry
from ..tools.export import export_openai_functions
from ..tools.registry import ToolRegistry
from .loop import build_task_instruction
from .provider import AgentRequest, RunResult, StreamSink, ToolCallRequest, ToolResult

_DONE = "[DONE]"


class OpenAIProvider:
    name = "openai"
    execution = "tool-loop"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        registry: ToolRegistry | None = None,
        executor=None,
        client: httpx.Client | None = None,
        api_key: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._registry = registry or build_registry()
        self.executor = executor
        self._key = (
            api_key
            if api_key is not None
            else self.settings.openai_api_key.get_secret_value()
        )
        self._client = client or httpx.Client(
            base_url=self.settings.openai_base_url.rstrip("/"), timeout=120.0
        )

    async def run_agentic(
        self, request: AgentRequest, sink: StreamSink, *, cancel: threading.Event
    ) -> RunResult:
        if not self._key:
            raise ProviderError(
                "unavailable",
                "未配置 REQMESH_OPENAI_API_KEY（自驱 provider 需要 key；DSH 路线零凭据）",
            )
        if self.executor is None:
            raise ProviderError(
                "protocol", "OpenAIProvider 未注入 executor（自驱执行契约缺失）"
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_task_instruction(request)},
            *list(request.history),
            {"role": "user", "content": request.task},
        ]
        tools = export_openai_functions(self._registry)
        text_parts: list[str] = []
        tool_calls_total = 0
        rounds = 0
        try:
            while True:
                if cancel.is_set():
                    return RunResult(
                        "cancelled", "".join(text_parts), tool_calls_total, 0, None
                    )
                if rounds >= request.max_rounds:
                    raise ProviderError(
                        "protocol",
                        f"自驱执行超过防御轮数上限（max_rounds={request.max_rounds}）——任务中止",
                    )
                rounds += 1
                text_chunks, tool_calls, raw_calls = self._stream_once(
                    messages, tools, sink, cancel
                )
                text_parts.extend(text_chunks)
                if not tool_calls:
                    sink.on_turn_end("completed")
                    return RunResult(
                        "completed", "".join(text_parts), tool_calls_total, 0, None
                    )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "".join(text_chunks) or None,
                        "tool_calls": [
                            {
                                "id": call_id,
                                "type": "function",
                                "function": {"name": name, "arguments": args_json},
                            }
                            for call_id, name, args_json in raw_calls
                        ],
                    }
                )
                for call_id, name, _ in raw_calls:
                    call = next(c for c in tool_calls if c.name == name)
                    result: ToolResult = self.executor(
                        call.name, dict(call.arguments), request.project_context
                    )
                    sink.on_tool_call(call.name, dict(call.arguments))
                    sink.on_tool_result(call.name, result.ok, result.text)
                    tool_calls_total += 1
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": result.text,
                        }
                    )
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            raise ProviderError("unavailable", f"OpenAI 兼容端点不可达: {exc}") from exc

    # ------------------------------------------------------------------ 内部
    def _stream_once(
        self,
        messages: list[dict],
        tools: list[dict],
        sink: StreamSink,
        cancel: threading.Event,
    ) -> tuple[list[str], list[ToolCallRequest], list[tuple[str, str, str]]]:
        """一次模型调用（SSE 流；同步执行，由 run_agentic 驱动的 async 上下文调用）。

        返回 (文本块, 解析后的工具调用, 原始 (id, name, arguments JSON 字符串) 列表)。
        """
        body = {
            "model": self.settings.openai_model,
            "messages": messages,
            "tools": tools,
            "stream": True,
        }
        with self._client.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code != 200:
                response.read()
                raise ProviderError(
                    "unavailable",
                    f"OpenAI 兼容端点错误（HTTP {response.status_code}）：{_detail_of(response)}",
                )
            text_chunks: list[str] = []
            calls: dict[int, dict[str, str]] = {}
            for line in response.iter_lines():
                if cancel.is_set():
                    raise ProviderError(
                        "timeout", "流式等待被取消", code="client-cancelled"
                    )
                if not line or not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload:
                    continue
                if payload == _DONE:
                    break
                try:
                    data = json.loads(payload)
                except ValueError as exc:
                    raise ProviderError(
                        "protocol", f"OpenAI SSE 行非法 JSON: {line[:120]}"
                    ) from exc
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    sink.on_text(content)
                    text_chunks.append(content)
                for tc in delta.get("tool_calls") or []:
                    index = int(tc.get("index", 0))
                    slot = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.get("id"):
                        slot["id"] = str(tc["id"])
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = str(fn["name"])
                    if fn.get("arguments"):
                        slot["arguments"] += str(fn["arguments"])
            ordered = [calls[index] for index in sorted(calls)]
            for slot in ordered:
                if not slot["id"] or not slot["name"]:
                    raise ProviderError(
                        "protocol", "tool_calls delta 缺 id/name（SSE 形状非法）"
                    )
            raw_calls = [(s["id"], s["name"], s["arguments"]) for s in ordered]
            tool_calls: list[ToolCallRequest] = []
            for call_id, name, args_json in raw_calls:
                try:
                    arguments = json.loads(args_json) if args_json.strip() else {}
                except ValueError as exc:
                    raise ProviderError(
                        "protocol", f"工具 {name} 的参数 JSON 非法: {args_json[:100]}"
                    ) from exc
                if not isinstance(arguments, dict):
                    raise ProviderError("protocol", f"工具 {name} 的参数应为对象")
                tool_calls.append(ToolCallRequest(name=name, arguments=arguments))
            return text_chunks, tool_calls, raw_calls


def _detail_of(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return (response.text or "")[:200]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        if isinstance(err, str):
            return err
        if isinstance(data.get("message"), str):
            return data["message"]
    return (response.text or "")[:200]


__all__ = ["OpenAIProvider"]
