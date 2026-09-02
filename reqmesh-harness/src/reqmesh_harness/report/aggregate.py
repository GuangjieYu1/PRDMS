"""追踪/覆盖缺口报告聚合内核（P4 #31）：六源 → 12 类维度提取 → 实体去重合并 → 排序 → schema 组装。

纯函数、零网络副作用（对齐 P3 lint/ 模式）：输入为六源原始 JSON 响应（dict），
输出为报告 schema（spec「工具契约」）。工具层负责采集（6 个 GET）与 fail-fast
（任一源 UpstreamError 整体报错——本模块只做形状防御：非 dict/缺关键字段 →
HarnessError）。

口径（spec ②/③/⑤，实现按此固定）：
- 维度类型 12 值（templates.DIMENSION_TYPES，模板表逐行对应）；
- 主清单 gaps：按实体 id 去重合并（六源缺口均为需求中心；suspect-links 按 target
  并入），含 info 级（coverage.unwanted）维度——「六源缺口 id 并集」= 带任一维度
  注解的实体集合（无丢失、无编造；信息级标注本身是报告内容，带建议动作）；
- 排序：主清单三重键（最高严重度降序 → 维度数降序 → id 升序）；条目内 dimensions
  （严重度降序, type 升序）、actions（严重度降序, action 文本升序）；
- 过滤（dimensions 白名单）：只作用于 chapters 的 items（带维度注解的条目）与
  gaps 主清单；summary 与章节标量（total/count/links/rows/unallocated 等）保持全量
  （计数口径稳定，报告间可比）；
- 确定性：同输入必同输出（generated_at 由调用方注入——工具层传当前时间）。
"""

from __future__ import annotations

from typing import Any

from ..errors import HarnessError
from .templates import (
    SEVERITY_RANK,
    render_action,
    severity_of,
    template_for,
    uncovered_type,
)

_GAP_ISSUE_TO_DIM = {
    "no_description": "content.no_description",
    "no_rationale": "content.no_rationale",
    "no_source": "content.no_source",
    "unlinked": "trace.unlinked",
}


def _require_dict(payload: Any, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HarnessError(f"{source} 响应形状未知: {type(payload).__name__}")
    return payload


def _require_keys(payload: dict[str, Any], source: str, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key not in payload:
            raise HarnessError(f"{source} 响应缺少字段 {key!r}")


def _severity_rank(severity: str) -> int:
    return SEVERITY_RANK[severity]


def _sort_dim_key(dim: dict[str, Any]) -> tuple[int, str]:
    return (-_severity_rank(dim["severity"]), dim["type"])


def _sort_action_key(action: dict[str, Any]) -> tuple[int, str]:
    return (-_severity_rank(action["severity"]), action["action"])


def _dim(
    dimension_type: str,
    evidence: dict[str, Any] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    dim: dict[str, Any] = {
        "type": dimension_type,
        "severity": severity_of(dimension_type),
    }
    if source is not None:
        dim["source"] = source
    if evidence is not None:
        dim["evidence"] = evidence
    return dim


# ------------------------------------------------------------------ 章节提取（每源 → 带维度注解条目）
def _coverage_dims(item: dict[str, Any]) -> list[dict[str, Any]]:
    dims: list[dict[str, Any]] = []
    uncovered = item.get("uncovered_types") or []
    for need in uncovered:
        dims.append(
            _dim(
                uncovered_type(need),
                evidence={
                    "need_type": need,
                    "needs": item.get("needs", []),
                    "covered_types": item.get("covered_types", []),
                    "uncovered_types": item.get("uncovered_types", []),
                },
            )
        )
    if item.get("broken_chain"):
        dims.append(
            _dim(
                "coverage.chain_broken",
                evidence={
                    "shallow": item.get("shallow"),
                    "deep": item.get("deep"),
                    "needs": item.get("needs", []),
                },
            )
        )
    if item.get("unwanted_coverage"):
        dims.append(
            _dim(
                "coverage.unwanted",
                evidence={
                    "unwanted_coverage": item.get("unwanted_coverage", []),
                    "covered_types": item.get("covered_types", []),
                    "needs": item.get("needs", []),
                },
            )
        )
    return sorted(dims, key=_sort_dim_key)


def coverage_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload["items"]
    annotated: list[dict[str, Any]] = []
    for item in items:
        dims = _coverage_dims(item)
        if not dims:
            continue
        annotated.append(
            {
                "id": item["id"],
                "name": item.get("name"),
                "needs": item.get("needs", []),
                "uncovered_types": item.get("uncovered_types", []),
                "unwanted_coverage": item.get("unwanted_coverage", []),
                "shallow": bool(item.get("shallow")),
                "deep": bool(item.get("deep")),
                "broken_chain": bool(item.get("broken_chain")),
                "dimensions": dims,
            }
        )
    annotated.sort(key=lambda x: x["id"])
    return {
        "total_analyzed": payload["total"],
        "count": len(annotated),
        "items": annotated,
    }


def gap_analysis_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    for item in payload["items"]:
        issues = list(item.get("issues") or [])
        dims = [
            _dim(dtype, evidence={"issues": issues})
            for issue in issues
            if (dtype := _GAP_ISSUE_TO_DIM.get(issue))
        ]
        if not dims:
            continue
        annotated.append(
            {
                "id": item["id"],
                "name": item.get("name"),
                "issues": issues,
                "dimensions": sorted(dims, key=_sort_dim_key),
            }
        )
    annotated.sort(key=lambda x: x["id"])
    return {
        "total": payload["total"],
        "gaps": payload["gaps"],
        "count": len(annotated),
        "items": annotated,
    }


def traces_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    """traces 章为链接清单作上下文，非缺口（spec ②：无维度注解）。"""
    links = sorted(
        (
            {
                "source": l.get("source"),
                "target": l.get("target"),
                "type": l.get("type"),
            }
            for l in payload["links"]
        ),
        key=lambda x: (x["source"] or "", x["target"] or "", x["type"] or ""),
    )
    types: dict[str, int] = {}
    for l in links:
        t = l["type"] or ""
        types[t] = types.get(t, 0) + 1
    return {"links": len(links), "types": dict(sorted(types.items())), "items": links}


def suspect_links_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for link in payload["links"]:
        items.append(
            {
                "source": link.get("source"),
                "source_collection": link.get("source_collection"),
                "target": link.get("target"),
                "type": link.get("type"),
                "reason": link.get("reason"),
                "dimensions": [
                    _dim(
                        "trace.stale",
                        evidence={
                            "link_type": link.get("type"),
                            "from": link.get("source"),
                            "target": link.get("target"),
                            "reason": link.get("reason"),
                        },
                    )
                ],
            }
        )
    items.sort(
        key=lambda x: (
            x["source"] or "",
            x["target"] or "",
            x["type"] or "",
            x["reason"] or "",
        )
    )
    count = (
        payload.get("count") if isinstance(payload.get("count"), int) else len(items)
    )
    return {"count": count, "items": items}


def unreviewed_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload["items"]
    never = 0
    stale = 0
    annotated: list[dict[str, Any]] = []
    for item in items:
        reviewed = item.get("reviewed")
        fingerprint = item.get("current_fingerprint")
        if reviewed is None:
            dim = _dim(
                "review.never",
                evidence={
                    "reviewed": None,
                    "current_fingerprint": fingerprint,
                },
            )
            never += 1
        elif reviewed != fingerprint:
            dim = _dim(
                "review.stale",
                evidence={
                    "reviewed": reviewed,
                    "current_fingerprint": fingerprint,
                },
            )
            stale += 1
        else:
            continue  # 已评审且指纹一致：非缺口（上游不应出现，防御性过滤）
        annotated.append(
            {
                "id": item["id"],
                "name": item.get("name"),
                "reviewed": reviewed,
                "current_fingerprint": fingerprint,
                "dimensions": [dim],
            }
        )
    annotated.sort(key=lambda x: x["id"])
    return {"count": len(items), "never": never, "stale": stale, "items": annotated}


def allocation_chapter(payload: dict[str, Any]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    for row in payload["rows"]:
        allocated_to = row.get("allocated_to")
        if allocated_to not in (None, ""):
            continue
        annotated.append(
            {
                "req_id": row.get("req_id"),
                "req_name": row.get("req_name"),
                "req_type": row.get("req_type"),
                "row_id": row.get("row_id"),
                "row_name": row.get("row_name"),
                "allocated_to": allocated_to,
                "dimensions": [
                    _dim(
                        "allocation.missing",
                        evidence={
                            "row_id": row.get("row_id"),
                            "row_name": row.get("row_name"),
                            "allocated_to": allocated_to,
                            "req_type": row.get("req_type"),
                        },
                    )
                ],
            }
        )
    annotated.sort(key=lambda x: x["row_id"] or "")
    return {
        "rows": len(payload["rows"]),
        "unallocated": len(annotated),
        "items": annotated,
    }


# ------------------------------------------------------------------ 主清单（实体去重合并）
def _merge_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """records: [{id, name, dimensions(带 source)}, ...] → 按 id 并集（name 取首个已知）。"""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for rec in records:
        entity_id = rec["id"]
        if entity_id is None:
            continue
        if entity_id not in merged:
            merged[entity_id] = {
                "id": entity_id,
                "name": rec.get("name"),
                "dimensions": [],
            }
            order.append(entity_id)
        if merged[entity_id]["name"] is None and rec.get("name") is not None:
            merged[entity_id]["name"] = rec["name"]
        merged[entity_id]["dimensions"].extend(rec["dimensions"])
    return [
        (merged[e_id]["id"], merged[e_id]["name"], merged[e_id]["dimensions"])
        for e_id in order
    ]


def _actions_for(entity_id: str, dims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for dim in dims:
        row = template_for(dim["type"])
        if row is None:
            continue
        evidence = dim.get("evidence") or {}
        actions.append(
            {
                "action": render_action(
                    dim["type"], entity_id, evidence.get("need_type")
                ),
                "tool_hint": list(row.tool_hint),
                "severity": dim["severity"],
            }
        )
    return sorted(actions, key=_sort_action_key)


def _max_severity(dims: list[dict[str, Any]]) -> str:
    return max((d["severity"] for d in dims), key=_severity_rank)


def master_gaps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for entity_id, name, dims in _merge_records(records):
        dims = sorted(dims, key=_sort_dim_key)
        entries.append(
            {
                "id": entity_id,
                "collection": "requirements",
                "name": name,
                "dimensions": dims,
                "actions": _actions_for(entity_id, dims),
                "max_severity": _max_severity(dims),
            }
        )
    entries.sort(
        key=lambda e: (
            -_severity_rank(e["max_severity"]),
            -len(e["dimensions"]),
            e["id"],
        )
    )
    return entries


# ------------------------------------------------------------------ 白名单过滤（无维度注解章节不动；summary/章节标量全量）
def _filter_items(chapters: dict[str, Any], keep: set[str]) -> None:
    for chapter in chapters.values():
        if not isinstance(chapter, dict):
            continue
        items = chapter.get("items")
        if not isinstance(items, list):
            continue
        kept: list[dict[str, Any]] = []
        for item in items:
            if "dimensions" not in item:
                kept.append(item)  # traces 章：上下文清单，非缺口，不参与过滤
                continue
            dims = [d for d in item["dimensions"] if d["type"] in keep]
            if not dims:
                continue
            kept.append({**item, "dimensions": dims})
        chapter["items"] = kept


def filter_gaps(gaps: list[dict[str, Any]], keep: set[str]) -> list[dict[str, Any]]:
    """白名单过滤：只留含白名单维度的条目并**按重算键重排**（过滤会改变条目的
    max_severity 与维度数——不重排会破坏三重键排序契约，spec AC#6）。"""
    kept: list[dict[str, Any]] = []
    for entry in gaps:
        dims = [d for d in entry["dimensions"] if d["type"] in keep]
        if not dims:
            continue
        kept.append(
            {
                **entry,
                "dimensions": dims,
                "actions": _actions_for(entry["id"], dims),
                "max_severity": _max_severity(dims),
            }
        )
    kept.sort(
        key=lambda e: (
            -_severity_rank(e["max_severity"]),
            -len(e["dimensions"]),
            e["id"],
        )
    )
    return kept


# ------------------------------------------------------------------ summary
def _summary(
    raw_coverage: dict[str, Any],
    raw_gap: dict[str, Any],
    chapters: dict[str, Any],
    full_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    cov_items = raw_coverage["items"]
    breakdown: dict[str, int] = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for entry in full_gaps:
        for dim in entry["dimensions"]:
            sev = dim["severity"]
            breakdown[sev] = breakdown.get(sev, 0) + 1
    traces = chapters["traces"]
    unrev = chapters["unreviewed"]
    return {
        "requirements_total": raw_gap["total"],
        "coverage": {
            "total": raw_coverage["total"],
            "shallow_covered": raw_coverage["shallow_covered"],
            "deep_covered": raw_coverage["deep_covered"],
            "coverage_pct": raw_coverage["coverage_pct"],
            "deep_pct": raw_coverage["deep_pct"],
            "broken_chain": sum(1 for i in cov_items if i.get("broken_chain")),
            "uncovered_items": sum(1 for i in cov_items if i.get("uncovered_types")),
            "unwanted_items": sum(1 for i in cov_items if i.get("unwanted_coverage")),
        },
        "gap_analysis": {"total": raw_gap["total"], "gaps": raw_gap["gaps"]},
        "traces": {
            "links": traces["links"],
            "types": dict(sorted(traces["types"].items())),
        },
        "suspect_links": {"count": chapters["suspect_links"]["count"]},
        "unreviewed": {
            "count": unrev["count"],
            "never": unrev["never"],
            "stale": unrev["stale"],
        },
        "allocation": {
            "rows": chapters["allocation"]["rows"],
            "unallocated": chapters["allocation"]["unallocated"],
        },
        "gap_entities": len(full_gaps),
        "dimension_breakdown": {
            "high": breakdown["high"],
            "medium": breakdown["medium"],
            "low": breakdown["low"],
            "info": breakdown["info"],
        },
    }


# ------------------------------------------------------------------ 组装
def build_report(
    *,
    project_id: str,
    coverage: Any,
    gap_analysis: Any,
    traces: Any,
    suspect_links: Any,
    unreviewed: Any,
    allocation: Any,
    dimensions: list[str] | None = None,
    generated_at: str,
) -> dict[str, Any]:
    """六源 → 报告 schema（v1）。fail-fast：任一源形状非法 → HarnessError（不产部分报告）。"""
    cov = _require_dict(coverage, "coverage")
    _require_keys(cov, "coverage", ("total", "items"))
    gap = _require_dict(gap_analysis, "gap_analysis")
    _require_keys(gap, "gap_analysis", ("total", "gaps", "items"))
    trc = _require_dict(traces, "traces")
    _require_keys(trc, "traces", ("links",))
    sus = _require_dict(suspect_links, "suspect_links")
    _require_keys(sus, "suspect_links", ("links",))
    unrev = _require_dict(unreviewed, "unreviewed")
    _require_keys(unrev, "unreviewed", ("items",))
    alloc = _require_dict(allocation, "allocation")
    _require_keys(alloc, "allocation", ("rows",))

    # 章节（全量标量；items 为带维度注解条目）
    chapters: dict[str, Any] = {
        "coverage": coverage_chapter(cov),
        "gap_analysis": gap_analysis_chapter(gap),
        "traces": traces_chapter(trc),
        "suspect_links": suspect_links_chapter(sus),
        "unreviewed": unreviewed_chapter(unrev),
        "allocation": allocation_chapter(alloc),
    }

    # 主清单记录（每源缺口实体 → 维度；source ∈ 六源章节名）
    records: list[dict[str, Any]] = []
    for item in chapters["coverage"]["items"]:
        records.append(
            {
                "id": item["id"],
                "name": item["name"],
                "dimensions": [{**d, "source": "coverage"} for d in item["dimensions"]],
            }
        )
    for item in chapters["gap_analysis"]["items"]:
        records.append(
            {
                "id": item["id"],
                "name": item["name"],
                "dimensions": [
                    {**d, "source": "gap_analysis"} for d in item["dimensions"]
                ],
            }
        )
    for item in chapters["suspect_links"]["items"]:
        records.append(
            {
                "id": item["target"],
                "name": None,
                "dimensions": [
                    {**d, "source": "suspect_links"} for d in item["dimensions"]
                ],
            }
        )
    for item in chapters["unreviewed"]["items"]:
        records.append(
            {
                "id": item["id"],
                "name": item["name"],
                "dimensions": [
                    {**d, "source": "unreviewed"} for d in item["dimensions"]
                ],
            }
        )
    for item in chapters["allocation"]["items"]:
        records.append(
            {
                "id": item.get("req_id") or item.get("row_id"),
                "name": item.get("row_name"),
                "dimensions": [
                    {**d, "source": "allocation"} for d in item["dimensions"]
                ],
            }
        )

    full_gaps = master_gaps(records)

    # 过滤：chapters.items + gaps（summary 保持全量）
    # dimensions=[] 归一为 None（未提供 = 全部；空白名单按「不过滤」语义，避免
    # 全量报告却记录空 filter 的不一致——L1 审核项）
    if dimensions is not None and len(dimensions) == 0:
        dimensions = None
    if dimensions:
        keep = set(dimensions)
        _filter_items(chapters, keep)
        gaps = filter_gaps(full_gaps, keep)
    else:
        gaps = full_gaps

    return {
        "project_id": project_id,
        "generated_at": generated_at,
        "summary": _summary(cov, gap, chapters, full_gaps),
        "chapters": chapters,
        "gaps": gaps,
        "meta": {
            "tool": "get_traceability_gap_report",
            "version": 1,
            "filters": {
                "dimensions": list(dimensions) if dimensions is not None else None
            },
        },
    }
