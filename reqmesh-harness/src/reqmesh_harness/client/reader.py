"""只读视图：工具层唯一能看到的客户端接口——结构上只有 get()。

这是 P1 只读护栏的落地：P2 的写路径经审批门包装的写视图另行引入；本包客户端
对象类型上不存在任何非 GET 方法，工具处理器无法发出写请求。
"""

from __future__ import annotations

from typing import Any


class ReadOnlyClient:
    """只暴露 get() 的客户端视图（P1 只读护栏）。"""

    __slots__ = ("_session",)

    def __init__(self, session: Any) -> None:
        self._session = session

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._session.get(path, params=params)
