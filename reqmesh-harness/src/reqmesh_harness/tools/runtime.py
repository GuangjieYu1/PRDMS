"""运行时：把认证会话包装成只读视图，供全部工具处理器取用。

- 每次取用构建一个 `ReadOnlyClient`（会话文件共享；HTTP stateless 模式下
  每个请求作用域各自构建，符合 P1 spec「无服务端长驻项目上下文」）；
- stdio server 启动时以 `get_runtime().validate()` 做一次 whoami 校验
  （失效则重新登录），后续调用不发重复校验（401 兜底重登一次）。
"""

from __future__ import annotations

import threading

from ..client.reader import ReadOnlyClient
from ..client.session import AuthSession
from ..config import Settings

_lock = threading.Lock()
_runtime: "Runtime | None" = None


class Runtime:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def reader(self, validate: bool = False) -> ReadOnlyClient:
        session = AuthSession(self.settings)
        session.ensure_ready(validate=validate)
        return ReadOnlyClient(session)

    def validate(self) -> ReadOnlyClient:
        """启动校验：加载持久化会话并以 whoami 检查（失效则重新登录）。"""
        return self.reader(validate=True)


def get_runtime() -> Runtime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = Runtime()
        return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    """测试/嵌入方注入（None 恢复懒加载默认）。"""
    global _runtime
    with _lock:
        _runtime = runtime
