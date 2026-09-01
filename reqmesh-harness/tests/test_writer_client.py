"""#17 写路径客户端：CSRF 头、四种写方法、连接错误不重试、401 重登一次、错误归一化、GateToken 护栏。"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from reqmesh_harness.client.session import AuthSession
from reqmesh_harness.client.writer import WriteClient
from reqmesh_harness.client.state import SessionState
from reqmesh_harness.config import Settings
from reqmesh_harness.errors import (
    LoginFailedError,
    SessionExpiredError,
    TransportError,
    UpstreamError,
)
from reqmesh_harness.guardrails.gate import ApprovalGate, GateToken

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


def _preseed(session: AuthSession) -> None:
    session.store.save(
        SessionState(
            username="dev",
            role="contributor",
            csrf_token="csrf-body-token",
            cookies={"token": "fake.jwt.token", "csrftoken": "csrf-body-token"},
        )
    )


@pytest.mark.parametrize("method,path,payload", [
    ("post", "/api/projects/p/requirements", {"id": "X"}),
    ("put", "/api/projects/p/requirements/X", {"description": None}),
    ("patch", "/api/projects/p/requirements/X", {"description": "d"}),
    ("delete", "/api/projects/p/requirements/X", None),
])
def test_write_methods_send_csrf_header_and_body(tmp_path, method, path, payload) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    resp_body = {"ok": True} if method != "delete" else {}
    with respx.mock(base_url=BASE) as router:
        router.route(method=method.upper(), path=path).mock(return_value=Response(200, json=resp_body))
        if method == "delete":
            status, data = session.delete(path)
        else:
            status, data = getattr(session, method)(path, json=payload)
        assert (status, data) == (200, resp_body)
        call = router.calls[0]
        assert call.request.headers.get("x-csrf-token") == "csrf-body-token"
        if payload is not None:
            import json as _json

            assert _json.loads(call.request.content) == payload
        else:
            assert call.request.content == b""


def test_write_connect_error_is_not_retried(tmp_path) -> None:
    """非幂等：连接错误不重试（与 GET 的有限重试对称相反）。"""
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    with respx.mock(base_url=BASE) as router:
        router.post("/api/projects/p/requirements").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(TransportError):
            session.post("/api/projects/p/requirements", json={"id": "X"})
        assert len(router.calls) == 1


def test_write_401_relogin_once_then_retry(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    state = {"n": 0}

    def _post(request):
        state["n"] += 1
        if state["n"] == 1:
            return Response(401, json={"detail": "Invalid credentials"})
        return Response(201, json={"id": "X"})

    status = data = None
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        router.post("/api/projects/p/requirements").mock(side_effect=_post)
        status, data = session.post("/api/projects/p/requirements", json={"id": "X"})
        assert (status, data) == (201, {"id": "X"})
        assert state["n"] == 2  # 一次失败 + 一次重试
        posts = [c for c in router.calls if c.request.method == "POST"]
        assert len(posts) == 3  # 重登 + 写请求（两次）


def test_write_401_after_relogin_session_expired(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    with respx.mock(base_url=BASE) as router:
        router.post("/api/auth/login").mock(return_value=Response(200, json=LOGIN_BODY, headers=LOGIN_HEADERS))
        router.post("/api/projects/p/requirements").mock(return_value=Response(401, json={"detail": "Invalid credentials"}))
        with pytest.raises(SessionExpiredError):
            session.post("/api/projects/p/requirements", json={"id": "X"})


@pytest.mark.parametrize("error_body,expected_detail", [
    ({"detail": "project not found"}, "project not found"),
    ({"error": "validation_error", "message": "禁止写入"}, "validation_error: 禁止写入"),
])
def test_write_upstream_error_two_shapes_normalized(tmp_path, error_body, expected_detail) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    with respx.mock(base_url=BASE) as router:
        router.post("/api/projects/p/requirements").mock(return_value=Response(400, json=error_body))
        with pytest.raises(UpstreamError) as exc:
            session.post("/api/projects/p/requirements", json={"id": "X"})
    assert exc.value.status_code == 400
    assert expected_detail in str(exc.value)


def test_write_204_returns_empty_dict(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    with respx.mock(base_url=BASE) as router:
        router.delete("/api/projects/p/requirements/X").mock(return_value=Response(204))
        status, data = session.delete("/api/projects/p/requirements/X")
    assert (status, data) == (204, {})


def test_bearer_fallback_write_sends_authorization(tmp_path) -> None:
    session = AuthSession(Settings(base_url=BASE, username="", password="", token="bearer-token",
                                   session_file=tmp_path / "s.json"))
    seen: list[httpx.Request] = []

    def _post(request):
        seen.append(request)
        return Response(201, json={"id": "X"})

    with respx.mock(base_url=BASE) as router:
        router.post("/api/projects/p/requirements").mock(side_effect=_post)
        session.post("/api/projects/p/requirements", json={"id": "X"})
    assert seen[0].headers["authorization"] == "Bearer bearer-token"


# ------------------------------------------------------------------ WriteClient 结构护栏
def test_write_client_requires_gate_token(tmp_path) -> None:
    session = AuthSession(_settings(tmp_path))
    _preseed(session)
    with pytest.raises(TypeError):
        WriteClient(session, token="forged")  # type: ignore[arg-type]


def test_write_client_accepts_gate_issued_token(tmp_path) -> None:
    """GateToken 只由审批门批准时签发——写视图与裁决同源。"""
    approvals = tmp_path / "a.toml"
    approvals.write_text('[[approvals]]\ntool = "create_requirement"\nproject = "cessna-172"\n', encoding="utf-8")
    gate = ApprovalGate(Settings(base_url=BASE, username="dev", password="dev-pass", approvals_file=approvals))
    decision = gate.decide("create_requirement", "cessna-172", dry_run=False, level="DRAFT")
    assert decision.approved
    assert isinstance(decision.token, GateToken)


def test_gate_token_cannot_be_forged_without_gate(tmp_path) -> None:
    """GateToken 无公开构造入口（内部签发键不可伪造）。"""
    with pytest.raises(TypeError):
        GateToken("create_requirement", "cessna-172", None)  # type: ignore[arg-type]
