"""认证会话：登录/登出、Cookie+CSRF 维护、持久化、401 重登一次、Bearer 兜底。"""

from __future__ import annotations

import logging
import weakref
from typing import Any

import httpx

from ..config import Settings
from ..errors import LoginFailedError, SessionExpiredError, TransportError, UpstreamError
from .state import SessionState, SessionStore, cookie_targets

_LOGIN_PATH = "/api/auth/login"
_LOGOUT_PATH = "/api/auth/logout"
_WHOAMI_PATH = "/api/auth/whoami"

logger = logging.getLogger("reqmesh_harness.auth")


class AuthSession:
    """一个面向 reqmesh 实例的认证会话（认证会话，非运行时会话——见 CONTEXT.md 词表）。

    - 凭据仅来自 Settings（环境变量），不落盘、不进日志；
    - 登录后把 cookie + csrf_token 持久化到会话文件（0600），重启免重登；
    - 任何 GET 遇 401 → 自动重登一次并重试；仍 401 → SessionExpiredError；
    - 幂等 GET 连接错误允许重试一次（POST 不重试，登录/登出失败即类型化错误）；
    - Bearer 兜底：仅在未配置用户名/密码时使用 REQMESH_TOKEN（cookie 流程优先）。
    """

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None) -> None:
        self.settings = settings or Settings()
        self.store = SessionStore(self.settings.resolved_session_file())
        # Bearer 兜底：仅在未配置用户名/密码时使用（cookie 流程优先）
        self._use_bearer = bool(self.settings.token.get_secret_value()) and not (
            self.settings.has_password_credentials()
        )
        self._csrf = ""
        self._authenticated = False
        if client is not None:
            self._client = client
        else:
            self._client = httpx.Client(
                base_url=self.settings.base_url.rstrip("/"),
                timeout=self.settings.timeout,
                follow_redirects=False,
            )
            # 只关闭自建的 client；注入的 client 生命周期归所有者
            weakref.finalize(self, self._client.close)

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
            logger.info("登录被拒：%s", username)  # 记录用户但不记录密码
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
        logger.info("登录成功: %s (role=%s)", username, body.get("role", ""))
        return body

    def logout(self) -> dict:
        """登出：带 X-CSRF-Token 调 /api/auth/logout 并清除会话文件。"""
        if not self._authenticated and not self._use_bearer:
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

        - Bearer 兜底：未配置凭据且设置 REQMESH_TOKEN 时直接复用（不做 cookie 校验）；
        - 有持久化会话：载入；validate=True 时以 whoami 校验，失效则重新登录；
        - 无持久化会话且已配置凭据：登录；
        - 无凭据：保持未认证（匿名只读：后续请求经上游 401/403 以 UpstreamError 透传）。
        """
        if self._use_bearer:
            return
        state = self.store.load()
        if state is None:
            if self.settings.has_credentials():
                self.login()
            return
        self._restore(state)
        if validate:
            try:
                resp = self._client.get(_WHOAMI_PATH, headers=self._auth_headers())
            except httpx.TransportError as exc:
                raise TransportError(f"实例不可达: {exc}") from exc
            if resp.status_code == 401:
                if self.settings.has_credentials():
                    self.login()
                else:
                    raise UpstreamError(resp.status_code, self._detail_of(resp))
            elif resp.status_code != 200:
                raise UpstreamError(resp.status_code, self._detail_of(resp))
        self._authenticated = True

    # ------------------------------------------------------------------ 只读请求
    def get(self, path: str, params: dict | None = None) -> Any:
        """GET 并返回解析后的 JSON（原始响应透传）。

        - 连接错误：重试一次（幂等 GET 仅允许的有限重试）；
        - 401：重登一次并重试；
        - 仍失败：类型化错误（不含凭据）。
        """
        return self._get_retrying(path, params, retried_connect=False, retried_401=False)

    def _get_retrying(
        self,
        path: str,
        params: dict | None,
        retried_connect: bool,
        retried_401: bool,
    ) -> Any:
        self.ensure_ready(validate=False)
        try:
            resp = self._client.get(path, params=params, headers=self._auth_headers())
        except httpx.TransportError as exc:
            if not retried_connect:
                return self._get_retrying(path, params, True, retried_401)
            raise TransportError(f"实例不可达: {exc}") from exc
        if resp.status_code == 401 and not retried_401:
            if self.settings.has_credentials():
                self.login()
                return self._get_retrying(path, params, retried_connect, True)
            # 未配置凭据：无重登可用，上游 401 原样透传（匿名只读验证语义）
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        if resp.status_code == 401:
            raise SessionExpiredError("会话已失效且自动重登后仍被拒绝（401）。请检查凭据。")
        if resp.status_code != 200:
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        return resp.json()

    # ------------------------------------------------------------------ 写请求（P2）
    def post(self, path: str, json: dict | None = None) -> tuple[int, Any]:
        """POST 并返回 (状态码, 解析后的 JSON)。"""
        return self._write("post", path, json)

    def put(self, path: str, json: dict | None = None) -> tuple[int, Any]:
        """PUT 并返回 (状态码, 解析后的 JSON)。"""
        return self._write("put", path, json)

    def patch(self, path: str, json: dict | None = None) -> tuple[int, Any]:
        """PATCH 并返回 (状态码, 解析后的 JSON)。"""
        return self._write("patch", path, json)

    def delete(self, path: str) -> tuple[int, Any]:
        """DELETE 并返回 (状态码, 解析后的 JSON)。"""
        return self._write("delete", path, None)

    def _write(self, method: str, path: str, json: dict | None, retried_401: bool = False) -> tuple[int, Any]:
        """写请求统一路径（P2 契约）：

        - 全部写请求挂 `X-CSRF-Token`（Bearer 兜底路径下同 Authorization 头）；
        - 连接错误**不重试**（写请求非幂等）;
        - 401 重登一次并重试；仍 401 抛 SessionExpiredError；
        - 非 2xx 归一化为 UpstreamError(status_code, detail)（两种错误形状）。
        """
        self.ensure_ready(validate=False)
        headers = {**self._auth_headers(), **self._csrf_headers()}
        kwargs: dict[str, Any] = {"headers": headers}
        if method != "delete":  # httpx delete() 不接受 json 参数
            kwargs["json"] = json
        try:
            resp = getattr(self._client, method)(path, **kwargs)
        except httpx.TransportError as exc:
            raise TransportError(f"实例不可达: {exc}") from exc
        if resp.status_code == 401 and not retried_401:
            if self.settings.has_credentials():
                self.login()
                return self._write(method, path, json, retried_401=True)
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        if resp.status_code == 401:
            raise SessionExpiredError("会话已失效且自动重登后仍被拒绝（401）。请检查凭据。")
        if not 200 <= resp.status_code < 300:
            raise UpstreamError(resp.status_code, self._detail_of(resp))
        if resp.status_code == 204 or not resp.content:
            return resp.status_code, {}
        return resp.status_code, resp.json()

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
        if self._use_bearer:
            return {"Authorization": f"Bearer {self.settings.token.get_secret_value()}"}
        return {}

    def __repr__(self) -> str:  # 防泄漏：不打印密码
        return f"AuthSession(authenticated={self._authenticated})"

    @staticmethod
    def _detail_of(resp: httpx.Response) -> str:
        """上游错误归一化（两种形状 → 单一 detail 字符串）：

        - `{"detail": "<str>"}`（FastAPI 默认）；
        - `{"error": ..., "message": ..., ...}` envelope（reqmesh 自定义形状）。
        """
        try:
            data = resp.json()
        except ValueError:
            return (resp.text or "")[:500]
        if isinstance(data, dict):
            if isinstance(data.get("detail"), str):
                return data["detail"]
            if data.get("detail") is not None:
                return str(data["detail"])
            if data.get("error") is not None or data.get("message") is not None:
                return f"{data.get('error', 'upstream_error')}: {data.get('message', '')}".strip(": ")
        return (resp.text or "")[:500]
