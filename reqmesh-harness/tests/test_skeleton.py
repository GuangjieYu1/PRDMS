"""#7 骨架：工程结构与配置默认值。"""

from __future__ import annotations

import importlib.metadata

import reqmesh_harness
from reqmesh_harness.config import DEFAULT_BASE_URL, Settings


def test_package_is_installed() -> None:
    assert importlib.metadata.version("reqmesh-harness") == reqmesh_harness.__version__


def test_settings_defaults() -> None:
    s = Settings()
    assert s.base_url == DEFAULT_BASE_URL
    assert s.timeout == 30.0
    assert s.harness_host == "127.0.0.1"
    assert s.harness_port == 8123
    assert s.resolved_session_file().name == "session.json"
    assert s.resolved_session_file().parts[-3:-1] == ("reqmesh-harness",) or "reqmesh-harness" in str(
        s.resolved_session_file()
    )


def test_settings_env_override(monkeypatch) -> None:
    monkeypatch.setenv("REQMESH_BASE_URL", "http://example.test:9999")
    monkeypatch.setenv("REQMESH_TIMEOUT", "7.5")
    monkeypatch.setenv("REQMESH_HARNESS_PORT", "9000")
    s = Settings()
    assert s.base_url == "http://example.test:9999"
    assert s.timeout == 7.5
    assert s.harness_port == 9000
