"""写视图：工具层写路径唯一能看到的客户端接口——结构上只有 post/put/patch/delete。

P1 只读护栏的对称实现（P2 spec）：`WriteClient` 构造函数要求审批门签发的
`GateToken`（不可自行伪造），未过门的调用方拿不到写视图——未批准即结构性无写路径。
会话层契约（CSRF/401 重登/错误归一化）在 `AuthSession` 实现，本类只做视图包装。
"""

from __future__ import annotations

from typing import Any

from ..guardrails.gate import GateToken


class WriteClient:
    """只暴露写方法、构造需 GateToken 的客户端视图（P2 写护栏）。

    `last_status` 记录最近一次写请求的上游状态码（供审计日志使用）。
    """

    __slots__ = ("_session", "_token", "last_status")

    def __init__(self, session: Any, token: GateToken) -> None:
        if not isinstance(token, GateToken):
            raise TypeError("WriteClient 需要审批门签发的 GateToken（未批准即无写路径）")
        self._session = session
        self._token = token
        self.last_status: int | None = None

    def post(self, path: str, json: dict | None = None) -> Any:
        status, data = self._session.post(path, json=json)
        self.last_status = status
        return data

    def put(self, path: str, json: dict | None = None) -> Any:
        status, data = self._session.put(path, json=json)
        self.last_status = status
        return data

    def patch(self, path: str, json: dict | None = None) -> Any:
        status, data = self._session.patch(path, json=json)
        self.last_status = status
        return data

    def delete(self, path: str) -> Any:
        status, data = self._session.delete(path)
        self.last_status = status
        return data
