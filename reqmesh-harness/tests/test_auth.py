"""#8 认证客户端：登录成败、会话维护、401 重登一次、Bearer 兜底、离线打桩。"""

from __future__ import annotations

import os
import stat

import httpx
import pytest
import respx
from httpx import Response

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.client.state import SessionState
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import LoginFailedError, SessionExpiredError, TransportError, UpstreamError

BASE = "http://reqmesh.test"
LOGIN_BODY = {
    "username": "dev",
    "role": "contributor",
    "csrf_token": "csrf-body-token",
    "password_change_required": False,
}
LOGIN_HEADERS = [
    ("Set-Cookie", "token=fake.jwt.token; HttpOnly; Path=/api; SameSite=Lax"),
    ("Set-Cookie", "csrftoken=csrf-body-token; Path=/api; SameSite=Lax"),
]


def _settings(tmp_path, **overrides) -> Settings:
    kw = dict(base_url=BASE, username="dev", password="dev-pass", session_file=tmp_path / "session.json")
    kw.update(overrides)
    return Settings(**kw)


def _preseed_session(session: AuthSession) -> None:
    session.store.save(
        SessionState(
            username="dev",
            role="contributor",
            csrf_token="csrf-body-token",
            cookies={"token": "fake.jwt.token", "csrftoken": "csrf-body-token"},
        )
    )


def test_login_success_captures_cookies_and_csrf(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        body = session.login()
        assert body["csrf_token"] == "csrf-body-token"
        state = session.store.load()
        assert state is not None
        assert state.cookies == {"token": "fake.jwt.token", "csrftoken": "csrf-body-token"}
        assert state.csrf_token == "csrf-body-token"
        assert len(router.calls) == 1
    mode = stat.S_IMODE(os.stat(session.store.path).st_mode)
    assert mode == 0o600
    raw = session.store.path.read_text(encoding="utf-8")
    assert "dev-pass" not in raw
    assert "dev-pass" not in repr(session)


def test_login_wrong_password_typed_error_without_credentials(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        with pytest.raises(LoginFailedError) as exc:
            session.login()
        assert "dev-pass" not in str(exc.value)
        assert "dev-pass" not in repr(exc.value)


def test_login_missing_credentials_typed_error() -> None:
    session = AuthSession(Settings(base_url=BASE, username="", password=""))
    with pytest.raises(LoginFailedError):
        session.login()


def test_instance_unreachable_transport_error(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(TransportError):
            session.login()
        assert len(router.calls) == 1  # POST 不重试（仅幂等 GET 允许有限重试）


def test_401_rerelogin_once_then_success(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    state = {"n": 0}

    def _proj(request):
        state["n"] += 1
        if state["n"] == 1:
            return Response(401, json={"detail": "Invalid credentials"})
        return Response(200, json={"items": ["a"], "total": 1})

    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        router.get("/api/projects").mock(side_effect=_proj)
        result = session.get("/api/projects")
        assert result == {"items": ["a"], "total": 1}
        posts = [c for c in router.calls if c.request.method == "POST"]
        assert len(posts) == 1  # 401 → 重登一次
        gets = [c for c in router.calls if c.request.method == "GET"]
        assert len(gets) == 2  # 一次失败 + 一次重试


def test_401_rerelogin_fails_typed_error(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)

    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        router.get("/api/projects").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        with pytest.raises(LoginFailedError):
            session.get("/api/projects")


def test_401_after_successful_rerelogin_session_expired_error(tmp_path) -> None:
    """重登成功（200）但重试仍 401 → SessionExpiredError（含诊断）。"""
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)

    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        router.get("/api/projects").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        with pytest.raises(SessionExpiredError) as exc:
            session.get("/api/projects")
        assert "401" in str(exc.value)


def test_persisted_session_reused_without_login(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    with respx.mock(base_url=BASE) as router:
        router.get("/api/auth/whoami").mock(return_value=Response(200, json={"username": "dev"}))
        router.get("/api/projects").mock(return_value=Response(200, json=[{"id": "cessna-172"}]))
        session.ensure_ready(validate=True)
        session.get("/api/projects")
        assert all(c.request.method == "GET" for c in router.calls)
        assert len([c for c in router.calls if c.request.method == "POST"]) == 0


def test_stale_session_falls_back_to_login(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    with respx.mock(base_url=BASE) as router:
        router.get("/api/auth/whoami").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        session.ensure_ready(validate=True)
        posts = [c for c in router.calls if c.request.method == "POST"]
        assert len(posts) == 1
        whoamis = [c for c in router.calls if c.request.url.path == "/api/auth/whoami"]
        assert len(whoamis) == 1


def test_bearer_fallback_no_login(tmp_path) -> None:
    # 兜底：未配置用户名/密码时才用 Bearer
    session = AuthSession(Settings(base_url=BASE, username="", password="", token="bearer-token", session_file=tmp_path / "s.json"))
    seen: list[httpx.Request] = []

    def _proj(request):
        seen.append(request)
        return Response(200, json={"ok": True})

    with respx.mock(base_url=BASE) as router:
        router.get("/api/projects").mock(side_effect=_proj)
        session.ensure_ready(validate=True)
        session.get("/api/projects")
        assert len(seen) == 1
        assert seen[0].headers["authorization"] == "Bearer bearer-token"
        assert all(c.request.method == "GET" for c in router.calls)


def test_bearer_is_not_priority_when_credentials_set(tmp_path) -> None:
    """已配置用户名/密码时：token 仅兜底，cookie 流程优先（不发 Bearer 头）。"""
    session = AuthSession(_settings(tmp_path, token="bearer-token"))
    _preseed_session(session)
    seen: list[httpx.Request] = []

    def _proj(request):
        seen.append(request)
        return Response(200, json={"ok": True})

    with respx.mock(base_url=BASE) as router:
        router.get("/api/projects").mock(side_effect=_proj)
        session.get("/api/projects")
    assert "authorization" not in seen[0].headers


def test_get_connect_error_retried_once(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    state = {"n": 0}

    def _proj(request):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("boom")
        return Response(200, json={"items": ["a"]})

    with respx.mock(base_url=BASE) as router:
        router.get("/api/projects").mock(side_effect=_proj)
        result = session.get("/api/projects")
    assert result == {"items": ["a"]}
    assert state["n"] == 2  # 连接错误重试一次


def test_upstream_error_typed_with_detail(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    with respx.mock(base_url=BASE) as router:
        router.get("/api/projects").mock(return_value=Response(404, json={"detail": "project not found"}))
        with pytest.raises(UpstreamError) as exc:
            session.get("/api/projects")
        assert exc.value.status_code == 404
        assert "project not found" in str(exc.value)


def test_logout_sends_csrf_header_and_clears_state(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed_session(session)
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/logout").mock(return_value=Response(200, json={"ok": True}))
        session.logout()
        call = [c for c in router.calls if c.request.method == "POST"][0]
        assert call.request.headers.get("x-csrf-token") == "csrf-body-token"
        assert session.store.load() is None


def test_logs_never_contain_password(caplog, tmp_path) -> None:
    """凭据不进日志：登录成败日志只含用户名，不出现密码。"""
    import logging

    with caplog.at_level(logging.INFO, logger="reqmesh_harness.auth"):
        session = AuthSession(_settings(tmp_path))
        with respx.mock(base_url=BASE) as router:
            router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
            session.login()
        with respx.mock(base_url=BASE) as router:
            router.post("/api/auth/login").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
            with pytest.raises(LoginFailedError):
                session.login()
    assert "dev" in " ".join(r.message for r in caplog.records)
    assert all("dev-pass" not in r.message for r in caplog.records)


def test_corrupt_session_file_falls_back_to_login(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    session.store.path.write_text("{not-json", encoding="utf-8")
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        session.ensure_ready(validate=True)
        assert len([c for c in router.calls if c.request.method == "POST"]) == 1
