"""P5 测试子代理补充用例（会话内存边缘）：spec ⑤ / 验收 3 的未覆盖分支。

- 损坏 context.json fail-fast（既有只测 run.jsonl 损坏；spec ⑤「损坏文件 fail-fast」应含 context.json）；
- run.jsonl 大文本截断（task 2000 / tool_result summary 500 / done final_text 2000）。

这些用例是测试子代理的产出，供开发会话决策是否合并/修复；全部离线（tmp_path），
不改动既有测试与 src/。
"""

from __future__ import annotations

import pytest

from reqmesh_harness.runtime.memory import RunRecorder


def test_corrupt_context_json_fails_fast(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.dir.joinpath("context.json").write_text("{not-json\n", encoding="utf-8")
    with pytest.raises(ValueError):
        rec.read_context()


def test_non_object_context_json_fails_fast(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.dir.joinpath("context.json").write_text('["not", "an", "object"]', encoding="utf-8")
    with pytest.raises(ValueError):
        rec.read_context()


def test_record_task_truncates_to_2000(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_task("长" * 5000)
    (e,) = rec.read_events()
    assert e["kind"] == "task"
    assert len(e["task"]) == 2000


def test_record_tool_result_summary_truncates_to_500(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_tool_result("review_item", False, "x" * 1000)
    (e,) = rec.read_events()
    assert e["kind"] == "tool_result"
    assert len(e["summary"]) == 500


def test_record_done_final_text_truncates_to_2000(tmp_path) -> None:
    rec = RunRecorder.create(tmp_path / "runs")
    rec.init_context(task="t", project_context=None, provider="fake")
    rec.record_done("completed", "y" * 5000, tool_calls=0, questions=0)
    (e,) = rec.read_events()
    assert e["kind"] == "done"
    assert len(e["final_text"]) == 2000
