"""#37 会话内存：run 目录（XDG state、0700/0600）、context.json/run.jsonl/dsn-session.txt、
resume 两分支（存活追加 / 失活重建摘要）、损坏文件 fail-fast（spec ⑤、验收 3）。"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from reqmesh_harness.runtime.memory import RunRecorder, rebuild_summary

from reqmesh_harness.runtime.provider import ProjectContext

CTX = ProjectContext(
    project_id="cessna-172",
    base_url="http://reqmesh.test",
    created_at="2026-01-01T00:00:00Z",
)


def _is_0600(path: Path) -> bool:
    return stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


def _is_0700(path: Path) -> bool:
    return stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


def test_create_run_dir_name_and_permissions(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    name = rec.dir.name
    assert name.startswith("run-")
    assert "-resume" not in name
    # run-<YYYYmmddTHHMMSS>-<id8>
    ts_part = name[len("run-") : -9]
    datetime.strptime(ts_part, "%Y%m%dT%H%M%S")
    assert len(name.rsplit("-", 1)[1]) == 8
    assert rec.dir.parent == tmp_path / "runs"
    assert _is_0700(rec.dir) or _is_0600(rec.dir)


def test_context_json_snapshot(reqmesh_env, tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="建一条需求", project_context=CTX, provider="dsh")
    ctx = json.loads(rec.dir.joinpath("context.json").read_text(encoding="utf-8"))
    assert ctx["task"] == "建一条需求"
    assert ctx["project_context"] == {
        "project_id": "cessna-172",
        "base_url": "http://reqmesh.test",
        "created_at": "2026-01-01T00:00:00Z",
    }
    assert ctx["provider"] == "dsh"
    assert "created_at" in ctx and ctx["created_at"]
    assert _is_0600(rec.dir.joinpath("context.json"))


def test_run_jsonl_event_kinds_and_recording(reqmesh_env, tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_tool_call("review_item", {"project_id": "cessna-172"})
    rec.record_tool_result("review_item", False, "审批门拒绝")
    rec.record_text("一段文本")
    rec.record_question("是否批准？", answer="已批准")
    rec.record_turn_end("completed")
    rec.record_error("unavailable", "连接失败")
    rec.record_done("completed", "最终文本", tool_calls=1, questions=1)
    events = rec.read_events()
    kinds = [e["kind"] for e in events]
    assert kinds == [
        "tool_call",
        "tool_result",
        "text",
        "question",
        "turn_end",
        "error",
        "done",
    ]
    assert events[0]["name"] == "review_item"
    assert events[1]["ok"] is False
    assert events[3]["answer"] == "已批准"
    assert events[6]["tool_calls"] == 1
    assert all("ts" in e for e in events)
    assert _is_0600(rec.dir.joinpath("run.jsonl"))


def test_dsh_session_mapping_file(reqmesh_env, tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="dsh")
    rec.save_dsh_session("dsn-sess-abc123")
    assert rec.read_dsh_session() == "dsn-sess-abc123"
    assert _is_0600(rec.dir.joinpath("dsn-session.txt"))
    other = RunRecorder.create(tmp_path / "runs")
    assert other.read_dsh_session() is None


def test_resume_branch_new_dir_and_resumed_from(tmp_path) -> None:
    first = RunRecorder.create(tmp_path / "runs")
    first.init_context(task="原任务", project_context=None, provider="dsh")
    resumed = first.create_resume()
    assert resumed is not None
    assert resumed.dir.name.endswith("-resume")
    assert resumed.run_id != first.run_id
    ctx = json.loads(resumed.dir.joinpath("context.json").read_text(encoding="utf-8"))
    assert ctx["resumed_from"] == first.run_id
    assert ctx["task"] == "原任务"


def test_lookup_finds_run_dir(tmp_path) -> None:
    first = RunRecorder.create(tmp_path / "runs")
    first.init_context(task="t", project_context=None, provider="fake")
    assert RunRecorder.lookup(tmp_path / "runs", first.run_id) == first.dir
    resumed = first.create_resume()
    assert RunRecorder.lookup(tmp_path / "runs", resumed.run_id) == resumed.dir
    assert RunRecorder.lookup(tmp_path / "runs", "run-不存在") is None


def test_rebuild_summary_from_run_log_freezes_progress(tmp_path) -> None:
    """失活重建：final text + 工具调用序列 + 未决问题进入摘要（spec ⑤ 分支②）。"""
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="读缺口并评审", project_context=CTX, provider="dsh")
    rec.record_text("报告摘要")
    rec.record_tool_call("get_traceability_gap_report", {"project_id": "cessna-172"})
    rec.record_tool_result("get_traceability_gap_report", True, "报告已生成")
    rec.record_tool_call(
        "review_item", {"project_id": "cessna-172", "req_id": "AFRM0000"}
    )
    rec.record_tool_result("review_item", False, "审批门拒绝 review_item")
    rec.record_question("是否批准 review_item？", answer="已批准，请重试")
    rec.record_done("completed", "任务完成", tool_calls=2, questions=1)
    summary = rebuild_summary(rec.dir)
    assert "此前进展摘要" in summary
    assert "最终文本：任务完成" in summary
    assert "get_traceability_gap_report" in summary
    assert "review_item" in summary and "审批门拒绝" in summary
    assert "是否批准 review_item？" in summary


def test_rebuild_summary_without_done(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_text("部分文本")
    summary = rebuild_summary(rec.dir)
    assert "部分文本" in summary
    assert "未完成" in summary or "未到达完成事件" in summary


def test_corrupt_run_jsonl_fails_fast(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.dir.joinpath("run.jsonl").write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        rec.read_events()


def test_all_events_series_parseable_and_ts_utc(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_turn_end("completed")
    (e,) = rec.read_events()
    datetime.fromisoformat(e["ts"])  # 可解析（UTC ISO）
