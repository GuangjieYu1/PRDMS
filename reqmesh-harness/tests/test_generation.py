"""#7 模型生成管线：确定性、产物头部、fixture 解析。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
GEN_SCRIPT = ROOT / "scripts" / "gen_models.py"
GENERATED = ROOT / "src" / "reqmesh_harness" / "client" / "generated" / "models.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "http"


def _run_gen() -> None:
    subprocess.run(
        [sys.executable, str(GEN_SCRIPT)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        timeout=300,
    )


def test_rerun_is_deterministic() -> None:
    """重跑脚本：第二次与第一次输出字节一致（git diff 为空）。"""
    before = hashlib.sha256(GENERATED.read_bytes()).hexdigest()
    _run_gen()
    mid = hashlib.sha256(GENERATED.read_bytes()).hexdigest()
    _run_gen()
    after = hashlib.sha256(GENERATED.read_bytes()).hexdigest()
    assert mid == after == before


def test_generated_header() -> None:
    text = GENERATED.read_text(encoding="utf-8")
    assert text.startswith("# 此文件由 scripts/gen_models.py 从 vendored openapi 快照确定性生成——请勿手改。")
    assert "datamodel-code-generator" in text
    assert "reqmesh-0.5.0.json" in text


def test_generated_models_import() -> None:
    from reqmesh_harness.client.generated.models import (  # noqa: PLC0415
        LoginRequest,
        RequirementCreate,
        RequirementUpdate,
        RiskCreate,
    )

    assert LoginRequest.model_fields["username"].annotation is str
    assert set(RequirementCreate.model_fields) >= {"id", "type", "name", "description", "priority"}
    assert set(RiskCreate.model_fields) >= {"id", "title", "severity", "likelihood"}


def test_requirement_sample_parses_via_generated_model() -> None:
    """fixture 中 Requirement 样本可被生成模型解析。

    说明（需求会话前提修正）：openapi 快照未文档化实体响应 schema（Requirement/Risk 等
    均缺省），生成模型中最接近的写入契约是 RequirementCreate——样本的存储形状与其
    公共字段类型兼容即可解析（多余计算字段按 pydantic 默认忽略）。
    """
    from reqmesh_harness.client.generated.models import RequirementCreate  # noqa: PLC0415

    page = json.loads((FIXTURES / "requirements_list.json").read_text(encoding="utf-8"))
    items = page["items"]
    assert len(items) >= 1
    req = RequirementCreate.model_validate(items[0])
    assert req.name == "Aircraft System"
    for item in items:
        RequirementCreate.model_validate(item)

    # 非空洞：类型不符时应拒绝
    with pytest.raises(ValidationError):
        RequirementCreate.model_validate({"id": 123, "name": "x"})
