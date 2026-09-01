"""本地打桩上游：线程 http.server，按路径返回 fixture JSON 并记录全部请求。

供 stdio 子进程级与 streamable-HTTP 级测试使用（全部离线：仅绑定 127.0.0.1 随机端口）。
认证端点按上游行为打桩：login 返回 token/csrftoken cookie + body csrf_token。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator


class StubServer:
    def __init__(self, fixtures_dir: Path, routes: dict[str, str] | None = None) -> None:
        self.fixtures = fixtures_dir
        self.routes: dict[str, str] = routes or {}
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self._lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_factory())
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        port = self.httpd.server_address[1]
        return f"http://127.0.0.1:{port}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def method_counts(self) -> dict[str, int]:
        with self._lock:
            out: dict[str, int] = {}
            for method, _, _ in self.requests:
                out[method] = out.get(method, 0) + 1
            return out

    def _handler_factory(self) -> type[BaseHTTPRequestHandler]:
        server_ref = self

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args) -> None:  # type: ignore[no-untyped-def]
                pass

            def _record(self, query: dict[str, str]) -> None:
                with server_ref._lock:
                    server_ref.requests.append((self.command, self.path.split("?", 1)[0], query))

            def do_GET(self) -> None:
                query = {}
                if "?" in self.path:
                    from urllib.parse import parse_qs

                    query = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
                self._record(query)
                path = self.path.split("?", 1)[0]
                fixture = server_ref.routes.get(path)
                if fixture is None:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                data = (server_ref.fixtures / fixture).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                self._record({})
                if self.path == "/api/auth/login":
                    payload = json.dumps(
                        {
                            "username": "dev",
                            "role": "contributor",
                            "csrf_token": "csrf-body-token",
                            "password_change_required": False,
                        }
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header(
                        "Set-Cookie", "token=fake.jwt.token; HttpOnly; Path=/api; SameSite=Lax"
                    )
                    self.send_header("Set-Cookie", "csrftoken=csrf-body-token; Path=/api; SameSite=Lax")
                    self.end_headers()
                    self.wfile.write(payload)
                elif self.path == "/api/auth/logout":
                    payload = b'{"ok": true}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")

        return _Handler
