"""线程内运行 uvicorn（绑定 127.0.0.1 随机端口），供 streamable-HTTP 离线测试。"""

from __future__ import annotations

import threading
import time

import uvicorn


def serve_app(app) -> tuple[uvicorn.Server, threading.Thread, int]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise TimeoutError("uvicorn 启动超时")
        if not thread.is_alive():
            raise RuntimeError("uvicorn 线程退出")
        time.sleep(0.02)
    port = int(server.servers[0].sockets[0].getsockname()[1])
    return server, thread, port


def stop_app(server: uvicorn.Server, thread: threading.Thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)
