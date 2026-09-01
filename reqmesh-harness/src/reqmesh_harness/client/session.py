"""认证会话：登录/登出、Cookie+CSRF 维护、持久化、401 重登一次、Bearer 兜底。"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from ..errors import LoginFailedError, SessionExpiredError, TransportError, UpstreamError
from .state import SessionState, SessionStore, cookie_targets

_LOGIN_PATH = "/api/auth/login"
_LOGOUT_PATH = "/api/auth/logout"
_WHOAMI_PATH = "/api/auth/whoami"


class AuthSession:
    """一个面向 reqmesh 实例的认证会话。

    - 凭据仅来自 Settings（环境变量），不落盘、不进日志；
    - 登录后把 cookie + csrf_token 持久化到会话文件（0600），重启免重登；
    - 任何请求遇 401 → 自动重登一次并重试；仍 401 → SessionExpiredError；
    - REQMESH_TOKEN 设置时使用 Authorization: Bearer 兜底（cookie 流程跳过）。
    """

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or Settings()
        self.store = SessionStore(self.settings.resolved_session_file())
        self._bearer = self.settings.token.get_secret_value()
        self._csrf = ""
        self._authenticated = False
        self._client = client or httpx.Client(
            base_url=self.settings.base_url.rstrip("/"),
            timeout=self.settings.timeout,
            follow_redirects=False,
            transport=httpx.HTTPTransport(retries=2),
        )

    # ------------------------------------------------------------------ 登录/登出
    def login(self) -> dict:
        """用环境变量凭据登录；失败抛类型化错误（不含凭据）。"""
        username = self.settings.username
        password = self.settings.password.get_secret_value()
        if not username or not password:
            raise LoginFailedError("未配置 REQMESH_USERNAME/REQMESH_PASSWORD，无法登录")
        try:
            resp = self._client.post(_LOGIN_PATH, json={"username": username, "password": password})
        except httpx.TransportError as exc:
            raise TransportError(f"实例不可达: {exc}") from exc
        if resp.status_code == 401:
            raise LoginFailedError("登录被拒绝：凭据错误或账号被禁用")
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        body = resp.json()
        self._csrf = str(body.get("csrf_token") or "")
        self._authenticated = True
        state = SessionState(
            username=str(body.get("username") or username),
            role=str(body.get("role") or ""),
            csrf_token=self._csrf,
            cookies=self._cookies_from_jar(),
        )
        self.store.save(state)
        return body

    def logout(self) -> dict:
        """登出：带 X-CSRF-Token 调 /api/auth/logout 并清除会话文件。"""
        if not self._authenticated and not self._bearer:
            state = self.store.load()
            if state is not None:
                self._restore(state)
        try:
            resp = self._client.post(_LOGOUT_PATH, headers=self._csrf_headers())
        except httpx.TransportError as exc:
            raise TransportError(f"实例不可达: {exc}") from exc
        self._authenticated = False
        self._csrf = ""
        self.store.clear()
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        return resp.json()

    # ------------------------------------------------------------------ 就绪
    def ensure_ready(self, validate: bool = True) -> None:
        """确保会话就绪。

        - Bearer 兜底：设置过则直接复用（不做 cookie 校验）；
        - 有持久化会话：载入；validate=True 时以 whoami 校验，失效则重新登录；
        - 无持久化会话：登录。
        """
        if self._bearer:
            return
        state = self.store.load()
        if state is None:
            self.login()
            return
        self._restore(state)
        if validate:
            try:
                resp = self._client.get(_WHOAMI_PATH, headers=self._auth_headers())
            except httpx.TransportError as exc:
                raise TransportError(f"实例不可达: {exc}") from exc
            if resp.status_code == 401:
                self.login()
            elif resp.status_code != 200:
                raise UpstreamError(resp.status_code, self._detail_of(resp))
        self._authenticated = True

    # ------------------------------------------------------------------ 只读请求
    def get(self, path: str, params: dict | None = None) -> Any:
        """GET 并返回解析后的 JSON（原始响应透传）；401 → 重登一次并重试。"""
        return self._get_with_retry(path, params, retried=False)

    def _get_with_retry(self, path: str, params: dict | None, retried: bool) -> Any:
        self.ensure_ready(validate=False)
        try:
            resp = self._client.get(path, params=params, headers=self._auth_headers())
        except httpx.TransportError as exc:
            raise TransportError(f"实例不可达: {exc}") from exc
        if resp.status_code == 401 and not retried:
            self.login()
            return self._get_with_retry(path, params, retried=True)
        if resp.status_code == 401:
            raise SessionExpiredError("会话已失效且自动重登后仍被拒绝（401）。请检查凭据。")
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        return resp.json()

    # ------------------------------------------------------------------ 内部
    def _restore(self, state: SessionState) -> None:
        host, path = cookie_targets(self.settings.base_url)
        jar = self._client.cookies
        for name, value in state.cookies.items():
            jar.set(name, value, domain=host, path=path)
        self._csrf = state.csrf_token
        if state.cookies.get("token"):
            cookie_csrf = jar.get("csrftoken", domain=host, path=path)
            if cookie_csrf:
                self._csrf = cookie_csrf

    def _cookies_from_jar(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for cookie in self._client.cookies.jar:
            if cookie.name in ("token", "csrftoken"):
                out[cookie.name] = cookie.value
        return out

    def _csrf_headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self._csrf} if self._csrf else {}

    def _auth_headers(self) -> dict[str, str]:
        if self._bearer:
            return {"Authorization": f"Bearer {self._bearer}"}
        return {}

    def __repr__(self) -> str:  # 防泄漏：不打印密码
        return f"AuthSession(authenticated={self._authenticated})"

    @staticmethod
    def _detail_of(resp: httpx.Response) -> str:
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("detail"):
                return str(data["detail"])
        except ValueError:
            pass
        return (resp.text or "")[:500]
