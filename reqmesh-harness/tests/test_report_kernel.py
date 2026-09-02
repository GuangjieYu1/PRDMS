"""P4 #31/#32 报告聚合内核：六源逐项相等 + 12 类维度提取 + 去重合并 + 三重键排序 + 过滤 + fail-fast + 确定性。

全部离线：直接以 tests/fixtures/http/ 六源 fixture 为输入（纯函数，无网络）；
golden 报告（tests/fixtures/http/report_golden.json）以固定 generated_at 构造期望。
金样例点检（spec ⑥ G2）：AFRM0000（coverage.uncovered(design) + allocation.missing
同根并存）；12 类维度全提取用合成语料（no_description/trace.stale/review.stale
在 cessna-172 fixture 中零命中——spec 明示）。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from reqmesh_harness.errors import HarnessError
from reqmesh_harness.report import (
    DIMENSION_TYPES,
    SEVERITY_RANK,
    build_report,
    render_action,
)
from tests.conftest import HTTP_FIXTURES

GENERATED_AT = "2026-09-02T05:38:00+00:00"


def _load(name: str) -> dict:
    return json.loads((HTTP_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def sources() -> dict:
    return {
        "coverage": _load("coverage.json"),
        "gap_analysis": _load("gap_analysis.json"),
        "traces": _load("traces.json"),
        "suspect_links": _load("suspect_links.json"),
        "unreviewed": _load("unreviewed.json"),
        "allocation": _load("allocation_matrix.json"),
    }


@pytest.fixture(scope="module")
def report(sources):
    return build_report(project_id="cessna-172", generated_at=GENERATED_AT, **sources)


def _fixture_gap_ids(sources) -> set[str]:
    """六源缺口 id 并集（独立于实现重算）：带任一缺口/标注的实体。"""
    ids: set[str] = set()
    cov = sources["coverage"]
    for item in cov["items"]:
        if (
            item.get("uncovered_types")
            or item.get("broken_chain")
            or item.get("unwanted_coverage")
        ):
            ids.add(item["id"])
    ids.update(item["id"] for item in sources["gap_analysis"]["items"])
    ids.update(link["target"] for link in sources["suspect_links"]["links"])
    ids.update(item["id"] for item in sources["unreviewed"]["items"])
    for row in sources["allocation"]["rows"]:
        if not row.get("allocated_to"):
            ids.add(row.get("req_id") or row.get("row_id"))
    return ids


# ------------------------------------------------------------------ G1：summary 与六源逐项相等
def test_summary_matches_sources(report, sources) -> None:
    s = report["summary"]
    cov = sources["coverage"]
    gap = sources["gap_analysis"]
    assert s["requirements_total"] == gap["total"]
    assert s["coverage"]["total"] == cov["total"]
    assert s["coverage"]["shallow_covered"] == cov["shallow_covered"]
    assert s["coverage"]["deep_covered"] == cov["deep_covered"]
    assert s["coverage"]["coverage_pct"] == cov["coverage_pct"]
    assert s["coverage"]["deep_pct"] == cov["deep_pct"]
    assert s["coverage"]["broken_chain"] == sum(
        1 for i in cov["items"] if i.get("broken_chain")
    )
    assert s["coverage"]["uncovered_items"] == sum(
        1 for i in cov["items"] if i.get("uncovered_types")
    )
    assert s["coverage"]["unwanted_items"] == sum(
        1 for i in cov["items"] if i.get("unwanted_coverage")
    )
    assert s["gap_analysis"] == {"total": gap["total"], "gaps": gap["gaps"]}
    assert s["traces"]["links"] == len(sources["traces"]["links"])
    assert s["traces"]["types"] == {"refines": len(sources["traces"]["links"])}
    assert s["suspect_links"]["count"] == sources["suspect_links"]["count"]
    unrev_items = sources["unreviewed"]["items"]
    assert s["unreviewed"]["count"] == len(unrev_items)
    assert s["unreviewed"]["never"] == sum(
        1 for i in unrev_items if i.get("reviewed") is None
    )
    assert s["unreviewed"]["stale"] == sum(
        1
        for i in unrev_items
        if i.get("reviewed") is not None
        and i.get("reviewed") != i.get("current_fingerprint")
    )
    rows = sources["allocation"]["rows"]
    assert s["allocation"]["rows"] == len(rows)
    assert s["allocation"]["unallocated"] == sum(
        1 for r in rows if not r.get("allocated_to")
    )
    # fixture 历史基线（P1 期快照；与 spec 事实 3 的双轨基线的差异说明见 spec）
    assert s["requirements_total"] == 57 and s["coverage"]["total"] == 55
    assert (s["coverage"]["shallow_covered"], s["coverage"]["deep_covered"]) == (44, 38)
    assert s["gap_analysis"]["gaps"] == 36 and s["traces"]["links"] == 8


def test_fixture_baseline_counts(report) -> None:
    """spec 事实 3 在 P1 fixture 上的对应快照（55/44/38/80/69/36/8/0/37/4）。"""
    s = report["summary"]
    assert s["coverage"] == {
        "total": 55,
        "shallow_covered": 44,
        "deep_covered": 38,
        "coverage_pct": 80,
        "deep_pct": 69,
        "broken_chain": 6,
        "uncovered_items": 11,
        "unwanted_items": 30,
    }
    assert s["suspect_links"]["count"] == 0
    assert s["unreviewed"] == {"count": 37, "never": 37, "stale": 0}
    assert s["allocation"] == {"rows": 57, "unallocated": 4}
    assert s["gap_entities"] == 53


# ------------------------------------------------------------------ G2：缺口清单完整（无丢失、无编造）
def test_master_gap_ids_equal_six_source_union(report, sources) -> None:
    assert {g["id"] for g in report["gaps"]} == _fixture_gap_ids(sources)
    # 无孤儿维度类型：全部维度类型 ∈ 12 类词表
    all_types = {d["type"] for g in report["gaps"] for d in g["dimensions"]}
    assert all_types <= set(DIMENSION_TYPES)


def test_merged_entry_afrm0000(report) -> None:
    """G2 点检：AFRM0000 = coverage.uncovered(design) + allocation.missing 同根并存
    （另含 trace.unlinked 与 info 级 coverage.unwanted）。"""
    entry = next(g for g in report["gaps"] if g["id"] == "AFRM0000")
    assert entry["collection"] == "requirements" and entry["name"] == "Airframe"
    types = {d["type"] for d in entry["dimensions"]}
    assert "coverage.uncovered:design" in types
    assert "allocation.missing" in types
    assert "trace.unlinked" in types
    assert "coverage.unwanted" in types
    sources = {d["source"] for d in entry["dimensions"]}
    assert sources == {"coverage", "gap_analysis", "allocation"}
    assert entry["max_severity"] == "high"
    assert len(entry["dimensions"]) == 4
    assert (
        len({d["type"] for d in entry["dimensions"]}) == 4
    )  # 无重复维度类型（同源去重）
    # actions 与维度一一对应（每条缺口都带建议——epic #4 验收）
    assert len(entry["actions"]) == 4
    for d in entry["dimensions"]:
        assert any(a["severity"] == d["severity"] for a in entry["actions"])


def test_non_gap_items_excluded(report) -> None:
    ids = {g["id"] for g in report["gaps"]}
    # coverage 无缺口/标注 且 六源其余源均无 → 不进主清单（AVNC0001/AVNC0005/PROP0003/SAFE0001）
    for clean_id in ("AVNC0001", "AVNC0005", "PROP0003", "SAFE0001"):
        assert clean_id not in ids, clean_id
    assert "AD2024001" in ids  # 仅 info 级 unwanted 标注 → 仍进主清单（报告内容带建议）
    assert (
        "OVERVIEW01" in ids
    )  # 仅 gap_analysis/unreviewed/allocation（coverage 跳过 normative=false）
    assert "AFRM0003" in ids  # gap_analysis 命中（unlinked），与 coverage 无缺口不冲突


# ------------------------------------------------------------------ 12 类维度提取 + 证据
def _synthetic_sources() -> dict:
    return {
        "coverage": {
            "total": 4,
            "shallow_covered": 1,
            "deep_covered": 0,
            "coverage_pct": 25,
            "deep_pct": 0,
            "items": [
                {
                    "id": "R1",
                    "name": "R1 需求",
                    "needs": ["design", "verification_case"],
                    "covered_types": [],
                    "uncovered_types": ["design", "verification_case"],
                    "unwanted_coverage": [],
                    "shallow": False,
                    "deep": False,
                    "broken_chain": False,
                },
                {
                    "id": "R2",
                    "name": "R2 需求",
                    "needs": ["design"],
                    "covered_types": ["design"],
                    "uncovered_types": [],
                    "unwanted_coverage": ["analysis_case"],
                    "shallow": True,
                    "deep": True,
                    "broken_chain": False,
                },
                {
                    "id": "R3",
                    "name": "R3 需求",
                    "needs": ["design"],
                    "covered_types": ["design"],
                    "uncovered_types": [],
                    "unwanted_coverage": [],
                    "shallow": True,
                    "deep": False,
                    "broken_chain": True,
                },
                {
                    "id": "R4",
                    "name": "R4 需求",
                    "needs": ["verification_case"],
                    "covered_types": ["verification_case"],
                    "uncovered_types": [],
                    "unwanted_coverage": [],
                    "shallow": True,
                    "deep": True,
                    "broken_chain": False,
                },
            ],
        },
        "gap_analysis": {
            "total": 5,
            "gaps": 2,
            "items": [
                {
                    "id": "R1",
                    "name": "R1 需求",
                    "issues": [
                        "no_description",
                        "no_rationale",
                        "no_source",
                        "unlinked",
                    ],
                },
                {"id": "R5", "name": "R5 需求", "issues": ["no_source"]},
            ],
        },
        "traces": {
            "links": [{"source": "ACFT0000", "target": "R1", "type": "refines"}]
        },
        "suspect_links": {
            "count": 2,
            "links": [
                {
                    "source": "C1",
                    "source_collection": "components",
                    "target": "R1",
                    "type": "satisfies",
                    "stored_fingerprint": "fA",
                    "current_fingerprint": "fB",
                    "reason": "Satisfies a requirement that changed since it was reviewed",
                },
                {
                    "source": "COMMENT-X",
                    "source_collection": "comments",
                    "target": "R1",
                    "type": "comments on",
                    "stored_fingerprint": "fA",
                    "current_fingerprint": "fB",
                    "reason": "Comments on changed item",
                },
            ],
        },
        "unreviewed": {
            "items": [
                {
                    "id": "R1",
                    "name": "R1 需求",
                    "reviewed": None,
                    "current_fingerprint": "f1",
                },
                {
                    "id": "R5",
                    "name": "R5 需求",
                    "reviewed": "old-fp",
                    "current_fingerprint": "new-fp",
                },
            ]
        },
        "allocation": {
            "axis": "components",
            "verb": "is satisfied by",
            "column_label": "Components",
            "row_kind": "requirements",
            "rows": [
                {
                    "row_id": "R1",
                    "row_name": "R1 需求",
                    "row_status": "proposed",
                    "row_type": "functional",
                    "cells": {},
                    "req_id": "R1",
                    "req_name": "R1 需求",
                    "req_status": "proposed",
                    "req_type": "functional",
                    "allocated_to": "",
                },
                {
                    "row_id": "R4",
                    "row_name": "R4 需求",
                    "row_status": "verified",
                    "row_type": "functional",
                    "cells": {"C1": True},
                    "req_id": "R4",
                    "req_name": "R4 需求",
                    "req_status": "verified",
                    "req_type": "functional",
                    "allocated_to": "C1",
                },
            ],
        },
    }


def test_all_twelve_dimensions_extractable() -> None:
    report = build_report(
        project_id="p", generated_at=GENERATED_AT, **_synthetic_sources()
    )
    all_types = {d["type"] for g in report["gaps"] for d in g["dimensions"]}
    assert all_types == set(DIMENSION_TYPES)
    # 每条维度都带建议（12 类全部命中模板）
    for g in report["gaps"]:
        for d in g["dimensions"]:
            assert any(a["severity"] == d["severity"] for a in g["actions"])
    # R1 单条合并了多源维度（source ∈ 六源章节名）
    entry = next(g for g in report["gaps"] if g["id"] == "R1")
    sources_seen = {d["source"] for d in entry["dimensions"]}
    assert sources_seen == {
        "coverage",
        "gap_analysis",
        "suspect_links",
        "unreviewed",
        "allocation",
    }
    assert (
        len(entry["dimensions"]) == 10
    )  # 2 uncovered + 4 content/trace + 2 stale + never + allocation


def test_evidence_fields(report, sources) -> None:
    keys = {
        (d["type"], g["id"]): d.get("evidence")
        for g in report["gaps"]
        for d in g["dimensions"]
    }
    d = keys[("coverage.uncovered:design", "AFRM0000")]
    assert d["need_type"] == "design"
    assert d["uncovered_types"] == ["design"]
    assert {"needs", "covered_types"} <= set(d)
    # chain_broken：shallow=true 且 deep=false（口径事实 2）
    cb = next(
        (
            d
            for g in report["gaps"]
            for d in g["dimensions"]
            if g["id"] == "ACFT0000" and d["type"] == "coverage.chain_broken"
        ),
        None,
    )
    assert (
        cb is not None
        and cb["evidence"]["shallow"] is True
        and cb["evidence"]["deep"] is False
    )
    # unwanted：evidence.unwanted_coverage
    uw = keys[("coverage.unwanted", "AD2024001")]
    assert uw["unwanted_coverage"] == ["verification_case"]
    # allocation：row 字段
    am = keys[("allocation.missing", "OVERVIEW01")]
    assert am["row_id"] == "OVERVIEW01" and am["allocated_to"] in ("", None)


def test_trace_stale_and_review_evidence() -> None:
    report = build_report(
        project_id="p", generated_at=GENERATED_AT, **_synthetic_sources()
    )
    entry = next(g for g in report["gaps"] if g["id"] == "R1")
    stale = [d for d in entry["dimensions"] if d["type"] == "trace.stale"]
    assert len(stale) == 2  # 同 target 两条可疑链接 → 两条维度（source 各自保留）
    ev = stale[0]["evidence"]
    assert set(ev) == {"link_type", "from", "target", "reason"}
    assert (
        ev["link_type"] == "satisfies" and ev["from"] == "C1" and ev["target"] == "R1"
    )
    assert "changed since it was reviewed" in ev["reason"]
    never = next(d for d in entry["dimensions"] if d["type"] == "review.never")
    assert never["evidence"]["reviewed"] is None
    r5 = next(g for g in report["gaps"] if g["id"] == "R5")
    stale_rev = next(d for d in r5["dimensions"] if d["type"] == "review.stale")
    assert stale_rev["evidence"]["reviewed"] == "old-fp"
    assert stale_rev["evidence"]["current_fingerprint"] == "new-fp"


def _action_for(report, gid, dim_type):
    """按模板渲染匹配维度对应的建议动作（唯一匹配：action 文本 = 模板渲染结果）。"""
    g = next(g for g in report["gaps"] if g["id"] == gid)
    dim = next(d for d in g["dimensions"] if d["type"] == dim_type)
    need_type = (dim.get("evidence") or {}).get("need_type")
    expected = render_action(dim_type, gid, need_type)
    return next(a for a in g["actions"] if a["action"] == expected)


def test_template_hits_per_sample(report) -> None:
    """G3 抽样：trace.unlinked → set_relations 读-改-写提示；content.no_source →
    update_requirement(source…)；review.never → review_item；allocation.missing → set_allocation。
    """
    a = _action_for(report, "ACFT0000", "trace.unlinked")
    assert a["tool_hint"] == ["set_relations"] and "读-改-写" in a["action"]
    a = _action_for(report, "ELEC0002", "content.no_source")
    assert (
        a["tool_hint"] == ["update_requirement"]
        and "补充需求 ELEC0002 的来源" in a["action"]
    )
    a = _action_for(report, "SAFE0004", "review.never")
    assert a["tool_hint"] == ["review_item"]
    a = _action_for(report, "OVERVIEW01", "allocation.missing")
    assert (
        a["tool_hint"] == ["set_allocation"]
        and "set_allocation(allocated=true)" in a["action"]
    )


# ------------------------------------------------------------------ 排序（G4）
def test_master_gaps_triple_key_sort(report) -> None:
    gaps = report["gaps"]
    for prev, cur in zip(gaps, gaps[1:]):
        key = lambda g: (
            -SEVERITY_RANK[g["max_severity"]],
            -len(g["dimensions"]),
            g["id"],
        )
        assert key(prev) <= key(cur), (prev["id"], cur["id"])
    # 同最大严重度且同维度数的前缀按 id 升序（AD 组外层保证：取具体样本断言）
    same = [(g["id"], g["max_severity"], len(g["dimensions"])) for g in gaps[:12]]
    assert same == sorted(same, key=lambda t: (-SEVERITY_RANK[t[1]], -t[2], t[0]))


def test_entry_dimension_and_action_sort(report) -> None:
    for g in report["gaps"]:
        dims = g["dimensions"]
        for prev, cur in zip(dims, dims[1:]):
            assert (-SEVERITY_RANK[prev["severity"]], prev["type"]) <= (
                -SEVERITY_RANK[cur["severity"]],
                cur["type"],
            )
        actions = g["actions"]
        for prev, cur in zip(actions, actions[1:]):
            assert (-SEVERITY_RANK[prev["severity"]], prev["action"]) <= (
                -SEVERITY_RANK[cur["severity"]],
                cur["action"],
            )


def test_chapters_items_sorted_by_id(report) -> None:
    for chap in ("coverage", "gap_analysis", "unreviewed"):
        ids = [item["id"] for item in report["chapters"][chap]["items"]]
        assert ids == sorted(ids), chap
    alloc_ids = [item["row_id"] for item in report["chapters"]["allocation"]["items"]]
    assert alloc_ids == sorted(alloc_ids)
    trace_items = report["chapters"]["traces"]["items"]
    assert trace_items == sorted(
        trace_items, key=lambda l: (l["source"], l["target"], l["type"])
    )


def test_chapters_scalars_faithful(report, sources) -> None:
    ch = report["chapters"]
    assert ch["coverage"]["total_analyzed"] == 55
    assert ch["gap_analysis"]["total"] == 57 and ch["gap_analysis"]["gaps"] == 36
    assert ch["traces"]["links"] == 8 and ch["traces"]["types"] == {"refines": 8}
    assert {k: ch["unreviewed"][k] for k in ("count", "never", "stale")} == {
        "count": 37,
        "never": 37,
        "stale": 0,
    }
    assert ch["allocation"]["rows"] == 57 and ch["allocation"]["unallocated"] == 4
    # 章节 items = 带维度注解条目（coverage 全部 55 条中的注解子集；traces 全量上下文）
    assert len(ch["coverage"]["items"]) == ch["coverage"]["count"]
    assert len(ch["traces"]["items"]) == 8
    assert len(ch["allocation"]["items"]) == 4


# ------------------------------------------------------------------ 过滤（⑤）
def test_dimensions_filter_chapters_and_gaps_summary_full(report, sources) -> None:
    filtered = build_report(
        project_id="cessna-172",
        generated_at=GENERATED_AT,
        **sources,
        dimensions=["review.never"],
    )
    assert filtered["summary"] == report["summary"]  # summary 全量
    assert filtered["meta"]["filters"] == {"dimensions": ["review.never"]}
    # gaps 只含 review.never 维度
    assert filtered["gaps"]
    for g in filtered["gaps"]:
        assert [d["type"] for d in g["dimensions"]] == ["review.never"]
        assert all(a["severity"] == "medium" for a in g["actions"])
        assert g["max_severity"] == "medium"
    # chapters：unreviewed items 全保留（本就只有该维度），coverage/gap/suspect/allocation 清空
    ch = filtered["chapters"]
    assert ch["unreviewed"]["items"]
    assert all(
        d["type"] == "review.never"
        for it in ch["unreviewed"]["items"]
        for d in it["dimensions"]
    )
    assert ch["coverage"]["items"] == []
    assert ch["gap_analysis"]["items"] == []
    assert ch["allocation"]["items"] == []
    assert (
        ch["traces"]["items"] == report["chapters"]["traces"]["items"]
    )  # 上下文清单不参与过滤
    # 章节标量保持全量
    assert ch["allocation"]["unallocated"] == 4 and ch["unreviewed"]["count"] == 37


def test_filtered_gaps_still_triple_key_sorted(report, sources) -> None:
    """M1 回归：过滤会改变条目的 max_severity/维度数——filter_gaps 必须按重算键重排。"""
    from reqmesh_harness.report import SEVERITY_RANK as RANK

    filtered = build_report(
        project_id="cessna-172",
        generated_at=GENERATED_AT,
        **sources,
        dimensions=["allocation.missing"],
    )
    gaps = filtered["gaps"]
    for prev, cur in zip(gaps, gaps[1:]):
        key = lambda g: (-RANK[g["max_severity"]], -len(g["dimensions"]), g["id"])
        assert key(prev) <= key(cur), (prev["id"], cur["id"])
    # 点检（审核子代理实证场景）：同为 single-dim medium 的 allocation 条目应 id 升序
    assert [g["id"] for g in gaps] == ["AFRM0000", "AVNC0006", "AVNC0010", "OVERVIEW01"]
    assert all(
        len(g["dimensions"]) == 1 and g["max_severity"] == "medium" for g in gaps
    )


def test_empty_dimensions_list_means_no_filter(report, sources) -> None:
    """L1 回归：dimensions=[] 归一为 None（未提供 = 全部；meta.filters 记录 null）。"""
    filtered = build_report(
        project_id="cessna-172",
        generated_at=GENERATED_AT,
        **sources,
        dimensions=[],
    )
    assert filtered == report
    assert filtered["meta"]["filters"] == {"dimensions": None}


def test_dimensions_filter_info_only(report, sources) -> None:
    filtered = build_report(
        project_id="cessna-172",
        generated_at=GENERATED_AT,
        **sources,
        dimensions=["coverage.unwanted"],
    )
    assert filtered["summary"] == report["summary"]
    for g in filtered["gaps"]:
        assert [d["type"] for d in g["dimensions"]] == ["coverage.unwanted"]
        assert g["max_severity"] == "info"
    assert len(filtered["gaps"]) == 30  # info 级条目保留（报告内容，非剔除）


def test_meta_and_structure(report) -> None:
    assert report["meta"] == {
        "tool": "get_traceability_gap_report",
        "version": 1,
        "filters": {"dimensions": None},
    }
    assert set(report) == {
        "project_id",
        "generated_at",
        "summary",
        "chapters",
        "gaps",
        "meta",
    }
    assert set(report["chapters"]) == {
        "coverage",
        "gap_analysis",
        "traces",
        "suspect_links",
        "unreviewed",
        "allocation",
    }
    assert all(g["collection"] == "requirements" for g in report["gaps"])


# ------------------------------------------------------------------ 确定性 + fail-fast
def test_deterministic_except_generated_at(sources) -> None:
    a = build_report(
        project_id="cessna-172", generated_at="2026-01-01T00:00:00Z", **sources
    )
    b = build_report(
        project_id="cessna-172", generated_at="2026-01-01T00:00:00Z", **sources
    )
    assert a == b
    c = build_report(
        project_id="cessna-172", generated_at="2026-02-02T00:00:00Z", **sources
    )
    assert a["generated_at"] != c["generated_at"]
    ca = {**a, "generated_at": None}
    cc = {**c, "generated_at": None}
    assert ca == cc  # 除 generated_at 外逐字节一致


@pytest.mark.parametrize(
    "bad_source",
    ["coverage", "gap_analysis", "traces", "suspect_links", "unreviewed", "allocation"],
)
def test_fail_fast_on_bad_shape(sources, bad_source) -> None:
    bad = dict(sources)
    bad[bad_source] = ["not", "a", "dict"]
    with pytest.raises(HarnessError):
        build_report(project_id="p", generated_at=GENERATED_AT, **bad)


@pytest.mark.parametrize(
    "bad_source,missing",
    [
        ("coverage", "items"),
        ("gap_analysis", "gaps"),
        ("traces", "links"),
        ("suspect_links", "links"),
        ("unreviewed", "items"),
        ("allocation", "rows"),
    ],
)
def test_fail_fast_on_missing_keys(sources, bad_source, missing) -> None:
    bad = dict(sources)
    bad[bad_source] = {k: v for k, v in bad[bad_source].items() if k != missing}
    with pytest.raises(HarnessError):
        build_report(project_id="p", generated_at=GENERATED_AT, **bad)


def test_inputs_not_mutated(sources) -> None:
    snapshot = deepcopy(sources)
    build_report(project_id="cessna-172", generated_at=GENERATED_AT, **sources)
    assert sources == snapshot  # 内核纯函数：不修改输入


# ------------------------------------------------------------------ golden
def test_golden_report(sources) -> None:
    golden = json.loads(
        (HTTP_FIXTURES / "report_golden.json").read_text(encoding="utf-8")
    )
    assert (
        build_report(project_id="cessna-172", generated_at=GENERATED_AT, **sources)
        == golden
    )
