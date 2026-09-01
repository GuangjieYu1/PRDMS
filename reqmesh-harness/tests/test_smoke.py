"""#16 冒烟：network-tagged（默认 pytest 集合不含；uv run pytest -m network 运行）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SMOKE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke_p1.py"


@pytest.mark.network
def test_smoke_cessna172(tmp_path) -> None:
    if not (os.environ.get("REQMESH_USERNAME") and os.environ.get("REQMESH_PASSWORD")) and not os.environ.get(
        "REQMESH_TOKEN"
    ):
        pytest.skip("需要真实实例凭据（REQMESH_USERNAME/REQMESH_PASSWORD 或 REQMESH_TOKEN）")
    out = tmp_path / "P1-cessna-172.md"
    env = {**os.environ, "REQMESH_SMOKE_OUT": str(out), "REQMESH_SESSION_FILE": str(tmp_path / "session.json")}
    proc = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr
    record = out.read_text(encoding="utf-8")
    assert "**通过**" in record
    assert "无副作用声明" in record
    assert "total=57" in record
