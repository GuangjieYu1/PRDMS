"""共享 fixtures：离线环境（respx 打桩 + fixture 文件）+ runtime 重置。"""

from __future__ import annotations

from pathlib import Path

import pytest

from reqmesh_harness.tools.runtime import set_runtime

FIXTURES = Path(__file__).parent / "fixtures"
HTTP_FIXTURES = FIXTURES / "http"


@pytest.fixture
def reset_runtime():
    set_runtime(None)
    yield
    set_runtime(None)


@pytest.fixture
def reqmesh_env(monkeypatch, tmp_path, reset_runtime):
    """工具级测试环境：打桩上游 reqmesh.test + 已持久化的假会话 + P2 临时护栏文件。

    会话文件预置（cookies token/csrftoken + csrf_token），因此工具调用不做登录；
    审批白名单/审计日志均在 tmp_path（绝不含真实用户目录），ADMIN 默认关闭。
    """
    monkeypatch.setenv("REQMESH_BASE_URL", "http://reqmesh.test")
    monkeypatch.setenv("REQMESH_USERNAME", "dev")
    monkeypatch.setenv("REQMESH_PASSWORD", "dev-pass")
    monkeypatch.setenv("REQMESH_TOKEN", "")
    monkeypatch.setenv("REQMESH_TIMEOUT", "10")
    monkeypatch.setenv("REQMESH_ENABLE_ADMIN", "0")
    monkeypatch.setenv("REQMESH_APPROVALS_FILE", str(tmp_path / "approvals.toml"))
    monkeypatch.setenv("REQMESH_AUDIT_FILE", str(tmp_path / "audit.jsonl"))
    session_file = tmp_path / "session.json"
    session_file.write_text((FIXTURES / "session.json").read_text(encoding="utf-8"))
    monkeypatch.setenv("REQMESH_SESSION_FILE", str(session_file))
    return {"session_file": session_file}
