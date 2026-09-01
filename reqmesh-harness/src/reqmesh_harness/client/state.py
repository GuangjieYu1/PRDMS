"""会话状态持久化：cookie（token/csrftoken）+ body csrf_token。

文件默认在 XDG state 目录（~/.local/state/reqmesh-harness/session.json），
0600 权限，不含密码，只含会话凭据与用户名/角色。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class SessionState:
    username: str = ""
    role: str = ""
    csrf_token: str = ""
    cookies: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.cookies is None:
            self.cookies = {}


class SessionStore:
    def __init__(self, file_path: Path) -> None:
        self._file = file_path

    @property
    def path(self) -> Path:
        return self._file

    def load(self) -> SessionState | None:
        if not self._file.exists():
            return None
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None  # 损坏的会话文件视同无会话（回落登录）
        return SessionState(
            username=str(data.get("username", "")),
            role=str(data.get("role", "")),
            csrf_token=str(data.get("csrf_token", "")),
            cookies={str(k): str(v) for k, v in (data.get("cookies") or {}).items()},
        )

    def save(self, state: SessionState) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(state)
        fd, tmp = tempfile.mkstemp(dir=self._file.parent, prefix=".session-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self._file)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def clear(self) -> None:
        try:
            self._file.unlink()
        except FileNotFoundError:
            pass


def cookie_targets(base_url: str) -> tuple[str, str]:
    """导出 cookie 的 domain 与 path（与上游 set_auth_cookies 一致：path=/api）。"""
    host = urlsplit(base_url).hostname or ""
    return host, "/api"
