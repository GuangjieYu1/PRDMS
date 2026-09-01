"""#22 工具调用级审计日志：每次写调用一行（approved/denied/dry_run/错误路径）、READ 零行、
字段契约齐全（version=1）、参数摘要截断/容器摘要、文件 0600 append-only、写入失败不阻断。"""

from __future__ import annotations

import json
import logging
import os
import stat
from datetime import datetime

import httpx
import pytest
import respx
from httpx import Response

from reqmesh_harness.errors import ApprovalDeniedError, TransportError, UpstreamError
from reqmesh_harness.guardrails.audit import AuditLog, summarize_params
from reqmesh_harness.guardrails.whitelist import WhitelistEntry, WhitelistStore
from reqmesh_harness.tools.groups import writes

REQUIRED_FIELDS = {
    "ts": str,
    "tool": str,
    "level": str,
    "project_id": str,
    "dry_run": bool,
    "params_summary": dict,
    "reason": str,
    "decision": str,
    "approved_by": (str, type(None)),
    "deny_reason": (str, type(None)),
    "upstream": (dict, type(None)),
    "http_status": (int, type(None)),
    "result": str,
    "duration_ms": int,
    "version": int,
}


def _rows(tmp_path) -> list[dict]:
    return AuditLog(tmp_path / "audit.jsonl").read_all()


def _approve(monkeypatch, tmp_path, tool: str) -> None:
    WhitelistStore(tmp_path / "approvals.toml").append(WhitelistEntry(tool=tool, project="cessna-172"))


def test_every_write_call_one_line(reqmesh_env, monkeypatch) -> None:
    """批准真实写 / dry_run / 拒绝 / 上游错误：各自一行，字段齐全。"""
    tmp = reqmesh_env["session_file"].parent
    _approve(monkeypatch, tmp, "create_requirement")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/requirements").mock(return_value=Response(201, json={"id": "A"}))
        writes.create_requirement(project_id="cessna-172", id="A", name="n")
        router.post("/api/projects/cessna-172/requirements").mock(return_value=Response(400, json={"detail": "bad"}))
        with pytest.raises(UpstreamError):
            writes.create_requirement(project_id="cessna-172", id="B")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get().mock(return_value=Response(404, json={"detail": "nf"}))
        writes.create_requirement(project_id="cessna-172", id="C", dry_run=True)
    with pytest.raises(ApprovalDeniedError):
        writes.create_risk(project_id="cessna-172", id="R")  # 无白名单：denied
    rows = _rows(tmp)
    assert len(rows) == 4
    assert [r["result"] for r in rows] == ["ok", "upstream_error", "ok", "blocked"]
    assert [r["decision"] for r in rows] == ["approved", "approved", "approved", "denied"]
    assert [r["http_status"] for r in rows] == [201, 400, None, None]
    assert rows[2]["upstream"] == {"method": "POST", "path": "/api/projects/cessna-172/requirements"}
    assert rows[2]["dry_run"] is True
    assert rows[2]["reason"] == ""
    assert rows[2]["approved_by"] == "create_requirement+cessna-172"
    for row in rows:
        for field, typ in REQUIRED_FIELDS.items():
            assert isinstance(row[field], typ), f"{field}={row[field]!r} 类型不符"
        assert row["version"] == 1
        datetime.fromisoformat(row["ts"])  # ISO8601 可解析


def test_audit_field_values_complete(reqmesh_env, monkeypatch) -> None:
    """MUTATE：reason 记入审计；denied 行 deny_reason 非空、approved_by 为 None。"""
    tmp = reqmesh_env["session_file"].parent
    with pytest.raises(ApprovalDeniedError):
        writes.update_requirement(project_id="cessna-172", req_id="ACFT0000", reason="改描述")
    row = _rows(tmp)[0]
    assert row["reason"] == "改描述"
    assert row["deny_reason"] and "白名单" in row["deny_reason"]
    assert row["approved_by"] is None
    assert row["upstream"] is None
    assert row["result"] == "blocked"


def test_read_tools_never_audit(reqmesh_env, monkeypatch) -> None:
    """READ 工具调用不写审计（噪声控制）。"""
    tmp = reqmesh_env["session_file"].parent
    from reqmesh_harness.tools import build_registry

    with respx.mock(base_url="http://reqmesh.test") as router:
        router.get("/api/projects/cessna-172/unreviewed").mock(return_value=Response(200, json={"items": []}))
        build_registry().call("get_unreviewed_requirements", project_id="cessna-172")
    assert _rows(tmp) == []


def test_params_summary_truncation_and_containers(reqmesh_env, monkeypatch) -> None:
    """参数摘要：标量截断 200 字符；容器记类型与长度；无凭据。"""
    tmp = reqmesh_env["session_file"].parent
    _approve(monkeypatch, tmp, "create_requirement")
    long_text = "x" * 500
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/requirements").mock(return_value=Response(201, json={}))
        writes.create_requirement(
            project_id="cessna-172", id="A", name=long_text, attributes=[{"key": "k", "value": "v"}], dry_run=False
        )
    summary = _rows(tmp)[0]["params_summary"]
    assert len(summary["name"]) == 201 and summary["name"].endswith("…")
    assert summary["attributes"] == {"type": "list", "length": 1}
    assert summary["project_id"] == "cessna-172"


def test_audit_file_0600_append_only(reqmesh_env, monkeypatch) -> None:
    tmp = reqmesh_env["session_file"].parent
    audit_path = tmp / "audit.jsonl"
    _approve(monkeypatch, tmp, "create_risk")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/risks").mock(return_value=Response(200, json={}))
        writes.create_risk(project_id="cessna-172", id="R1")
        writes.create_risk(project_id="cessna-172", id="R2")
    mode = stat.S_IMODE(audit_path.stat().st_mode)
    assert mode == 0o600
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])  # 每行独立有效 JSON
    second = json.loads(lines[1])
    assert first["tool"] == second["tool"] == "create_risk"
    assert first["params_summary"]["id"] == "R1"
    assert second["params_summary"]["id"] == "R2"


def test_audit_connect_error_path(reqmesh_env, monkeypatch) -> None:
    """运输错误（连接失败）也记审计：result=transport_error（非幂等写不重试）。"""
    tmp = reqmesh_env["session_file"].parent
    _approve(monkeypatch, tmp, "create_risk")
    with respx.mock(base_url="http://reqmesh.test") as router:
        router.post("/api/projects/cessna-172/risks").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(TransportError):
            writes.create_risk(project_id="cessna-172", id="R1")
    row = _rows(tmp)[0]
    assert row["result"] == "transport_error"
    assert row["decision"] == "approved"
    assert row["http_status"] is None


def test_dry_run_checks_exception_never_breaks_preview(reqmesh_env, monkeypatch) -> None:
    """本地校验异常 → 降级为 check 提示，dry_run 预览照常返回（且记审计）。"""
    tmp = reqmesh_env["session_file"].parent
    _approve(monkeypatch, tmp, "create_risk")
    with respx.mock(base_url="http://reqmesh.test") as router:
        # 不 stub checks 的 GET：respx 会抛 AllMockedAssertionError（非 HarnessError）
        result = writes.create_risk(project_id="cessna-172", id="R1", dry_run=True)
    assert result["dry_run"] is True
    assert result["checks"][0]["kind"] == "check_error"
    assert _rows(tmp)[0]["result"] == "ok"


def test_audit_write_failure_does_not_block(reqmesh_env, monkeypatch, caplog) -> None:
    """审计写入失败：降级告警，工具调用照常成功。"""
    tmp = reqmesh_env["session_file"].parent
    _approve(monkeypatch, tmp, "create_risk")
    # 把审计文件指向一个目录：open 追加必然失败
    (tmp / "audit.jsonl").mkdir()
    with caplog.at_level(logging.WARNING, logger="reqmesh_harness.audit"):
        with respx.mock(base_url="http://reqmesh.test") as router:
            router.post("/api/projects/cessna-172/risks").mock(return_value=Response(200, json={}))
            result = writes.create_risk(project_id="cessna-172", id="R1")
    assert result == {}
    assert any("审计日志写入失败" in r.message for r in caplog.records)


# ------------------------------------------------------------------ summarize_params（单元）
def test_summarize_params_shapes() -> None:
    """摘要形状：标量原值截断、容器记类型长度；工具参数中不存在凭据字段（双保险）。"""
    summary = summarize_params({"id": "A", "password_placeholder": "x"})
    assert summary["id"] == "A"
    # 凭据不进工具参数：写工具参数名集合内无 password/token 字段（在工具层测试对账）


def test_summarize_params_boundary_values() -> None:
    summary = summarize_params({"none": None, "num": 3.5, "ok": True, "lst": [1, 2], "tup": (1,), "setx": {"a"}})
    assert summary["none"] is None or summary["none"] == "None"
    assert summary["num"] == "3.5"
    assert summary["ok"] == "True"
    assert summary["lst"] == {"type": "list", "length": 2}
    assert summary["tup"] == {"type": "tuple", "length": 1}
    assert summary["setx"] == {"type": "set", "length": 1}


def test_no_write_tool_param_is_credential_named() -> None:
    """双保险：12 个写工具参数名集合不含凭据字段名。"""
    from tests.mapping import WRITE_TOOLS

    forbidden = {"password", "token", "secret", "api_key", "credential"}
    for toolmap in WRITE_TOOLS:
        names = {p.name for p in toolmap.params}
        assert not (names & forbidden), toolmap.name
