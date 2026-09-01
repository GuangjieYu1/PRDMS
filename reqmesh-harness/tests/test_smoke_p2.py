"""#24 P2 冒烟：network-tagged（默认 pytest 集合不含；uv run pytest -m network 运行）。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SMOKE_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smoke_p2.py"


@pytest.mark.network
def test_smoke_p2_cessna172(tmp_path) -> None:
    if not (os.environ.get("REQMESH_USERNAME") and os.environ.get("REQMESH_PASSWORD")) and not os.environ.get(
        "REQMESH_TOKEN"
    ):
        pytest.skip("需要真实实例凭据（REQMESH_USERNAME/REQMESH_PASSWORD 或 REQMESH_TOKEN）")
    out = tmp_path / "P2-cessna-172.md"
    env = {**os.environ, "REQMESH_SMOKE_OUT": str(out), "REQMESH_SESSION_FILE": str(tmp_path / "session.json")}
    proc = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, proc.stderr
    record = out.read_text(encoding="utf-8")
    assert "**通过**" in record
    # AC：时间戳、实例 URL、每步结果与关键计数
    assert re.search(r"^- 时间：\d{4}-\d{2}-\d{2}T", record, re.MULTILINE)
    assert re.search(r"^- 实例：http", record, re.MULTILINE)
    assert "| A1 空白名单阻断 | ok |" in record
    assert "| A3 全量 dry_run | ok | 12/12" in record
    assert "| A4 零副作用 | ok |" in record
    assert "| git 提交计数 | ok |" in record
    assert "| 审计日志 | ok |" in record
    assert "残渣清单" in record
    assert "历史快照" in record
