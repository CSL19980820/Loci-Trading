"""战法记忆知识图：对齐 codegraph 的「节点 + 边 + explore 子图」用法。

不复用 AST codegraph；存 ops.db，按 slug 隔离。
节点 kind：strategy / rule / watch / lesson / scenario / critique
边 rel：has_rule / watches / learned_from / absorbed_into / reinforces / contradicts / about
"""
from __future__ import annotations

from typing import Any

from src.ops.application.paper_copy_zh import (
    EDGE_REL_ZH,
    NODE_KIND_ZH,
    strategy_display_name,
)
from src.ops.application.paper_style_memory import _DEFAULT_WATCH, default_style_md


def ensure_strategy_root(store: Any, slug: str) -> dict[str, Any]:
    label = strategy_display_name(slug)
    return store.upsert_paper_mem_node(
        {
            "slug": slug,
            "kind": "strategy",
            "key": "root",
            "title": f"战法 {label}",
            "body": "纸面量化舱记忆根节点",
            "weight": 10.0,
        }
    )


def seed_default_graph(
    store: Any, slug: str, *, entry_mode: str = "scenario"
) -> dict[str, Any]:
    """首次把默认买法/观察点种进图（幂等）。"""
    root = ensure_strategy_root(store, slug)
    if entry_mode == "next_open":
        rules = [
            (
                "next_open_buy",
                "开盘接 + 动态调仓",
                "基线开盘接；过高减层或等回踩；一字放弃——调仓择位不是对错",
                {"scenario": "all", "entry_mode": "next_open"},
            ),
            (
                "limit_up_skip",
                "一字涨停放弃",
                "开盘一字/近涨停买不进则放弃——极端择位",
                {"scenario": "gap_up"},
            ),
            (
                "auction_judge_only",
                "竞价只纠偏",
                "09:15-09:25 默认不落开仓成交",
                {"phase": "auction"},
            ),
        ]
        watch_hints = [
            "T+1 开盘基线承接；过高时减层或等回踩舒适带",
            "一字/近涨停放弃——极端择位，不是『高开=错』",
            "持有期止损/到期卖出是否按战法执行",
        ]
    else:
        rules = [
            ("gap_up_stretch", "高开动态择位", "过高可暂缓/浅接/等回踩，不是高开=错误", {"scenario": "gap_up"}),
            ("flat_buy_in_band", "平开按计划接", "平开落在 entry 区间按计划层数接", {"scenario": "flat"}),
            ("gap_down_dip_in_band", "低开低吸带", "仅低吸带内接；深砸暂缓", {"scenario": "gap_down"}),
            ("auction_judge_only", "竞价只纠偏", "09:15-09:25 默认不落开仓成交", {"phase": "auction"}),
        ]
        watch_hints = list(_DEFAULT_WATCH)
    for key, title, body, props in rules:
        node = store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "rule",
                "key": key,
                "title": title,
                "body": body,
                "props": props,
                "weight": 5.0,
            }
        )
        store.upsert_paper_mem_edge(
            {
                "slug": slug,
                "src_id": root["id"],
                "dst_id": node["id"],
                "rel": "has_rule",
                "weight": 1.0,
            }
        )
    for i, hint in enumerate(watch_hints):
        node = store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "watch",
                "key": f"watch_{i}",
                "title": hint[:40],
                "body": hint,
                "weight": 3.0,
            }
        )
        store.upsert_paper_mem_edge(
            {
                "slug": slug,
                "src_id": root["id"],
                "dst_id": node["id"],
                "rel": "watches",
            }
        )
    for key, title in (
        ("gap_up", "高开情景"),
        ("flat", "平开情景"),
        ("gap_down", "低开情景"),
    ):
        store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "scenario",
                "key": key,
                "title": title,
                "body": f"次日预案情景节点：{title}",
                "weight": 2.0,
            }
        )
    return {"root": root, "nodes": store.list_paper_mem_nodes(slug, limit=50)}


def sync_style_doc_to_graph(store: Any, slug: str, style: dict[str, Any]) -> None:
    """把 style 文档投影到图（规则/观察），保持可 explore。"""
    root = ensure_strategy_root(store, slug)
    buy_rules = style.get("buy_rules") if isinstance(style.get("buy_rules"), dict) else {}
    gap_up = str(buy_rules.get("gap_up_default") or "")
    if gap_up == "no_chase":
        node = store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "rule",
                "key": "gap_up_no_chase",
                "title": "高开默认不追",
                "body": "风格确认：高开不追",
                "props": {"scenario": "gap_up", "from": "style"},
                "weight": 6.0,
            }
        )
        store.upsert_paper_mem_edge(
            {"slug": slug, "src_id": root["id"], "dst_id": node["id"], "rel": "has_rule"}
        )
    elif gap_up == "buy_at_open" or str(buy_rules.get("entry_mode") or "") == "next_open":
        node = store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "rule",
                "key": "next_open_buy",
                "title": "开盘接 + 动态调仓",
                "body": "风格确认：next_open 基线开盘接；过高减层/等回踩；不是对错判决",
                "props": {"scenario": "all", "from": "style", "entry_mode": "next_open"},
                "weight": 6.0,
            }
        )
        store.upsert_paper_mem_edge(
            {"slug": slug, "src_id": root["id"], "dst_id": node["id"], "rel": "has_rule"}
        )
    for i, hint in enumerate(list(style.get("watch_hints") or [])[:12]):
        node = store.upsert_paper_mem_node(
            {
                "slug": slug,
                "kind": "watch",
                "key": f"style_watch_{i}",
                "title": str(hint)[:40],
                "body": str(hint),
                "weight": 4.0,
            }
        )
        store.upsert_paper_mem_edge(
            {"slug": slug, "src_id": root["id"], "dst_id": node["id"], "rel": "watches"}
        )


def ingest_lesson_to_graph(store: Any, lesson: dict[str, Any]) -> dict[str, Any]:
    slug = str(lesson.get("slug") or "")
    root = ensure_strategy_root(store, slug)
    lesson_id = str(lesson.get("id") or lesson.get("key") or "")
    key = f"lesson_{lesson_id or lesson.get('title')}"
    node = store.upsert_paper_mem_node(
        {
            "slug": slug,
            "kind": "lesson",
            "key": key[:120],
            "title": str(lesson.get("title") or "教训"),
            "body": str(lesson.get("content") or ""),
            "props": {
                "lesson_kind": lesson.get("kind"),
                "trade_date": lesson.get("trade_date"),
                "evidence": lesson.get("evidence") or {},
            },
            "weight": 4.0 if lesson.get("kind") == "mistake" else 2.5,
        }
    )
    store.upsert_paper_mem_edge(
        {
            "slug": slug,
            "src_id": root["id"],
            "dst_id": node["id"],
            "rel": "learned_from",
            "weight": 1.0,
        }
    )
    # 高开教训 → 连到 gap_up 情景与 no_chase 规则
    title = str(lesson.get("title") or "") + str(lesson.get("content") or "")
    if "高开" in title:
        scenario = store.get_paper_mem_node_by_key(slug, "scenario", "gap_up")
        rule = store.get_paper_mem_node_by_key(slug, "rule", "gap_up_no_chase")
        if scenario:
            store.upsert_paper_mem_edge(
                {
                    "slug": slug,
                    "src_id": node["id"],
                    "dst_id": scenario["id"],
                    "rel": "about",
                }
            )
        if rule:
            store.upsert_paper_mem_edge(
                {
                    "slug": slug,
                    "src_id": node["id"],
                    "dst_id": rule["id"],
                    "rel": "absorbed_into" if lesson.get("kind") == "mistake" else "reinforces",
                    "weight": 2.0,
                }
            )
    if lesson.get("kind") == "revise":
        for sk in ("flat", "gap_down", "gap_up"):
            scenario = store.get_paper_mem_node_by_key(slug, "scenario", sk)
            if scenario:
                store.upsert_paper_mem_edge(
                    {
                        "slug": slug,
                        "src_id": node["id"],
                        "dst_id": scenario["id"],
                        "rel": "about",
                        "weight": 0.5,
                    }
                )
    return node


def explore_memory(
    store: Any,
    slug: str,
    query: str = "",
    *,
    max_nodes: int = 24,
    hops: int = 1,
) -> dict[str, Any]:
    """类似 codegraph_explore：按查询取种子节点，再扩一跳边与邻接。"""
    if not store.list_paper_mem_nodes(slug, limit=1):
        seed_default_graph(store, slug)

    seeds = store.search_paper_mem_nodes(slug, query, limit=max(8, max_nodes // 2))
    if not seeds:
        seeds = store.list_paper_mem_nodes(slug, limit=12)

    node_map = {n["id"]: n for n in seeds}
    frontier = list(node_map.keys())
    edges: list[dict[str, Any]] = []
    seen_edge: set[str] = set()

    for _ in range(max(1, hops)):
        batch = store.list_paper_mem_edges(slug, node_ids=frontier, limit=400)
        next_frontier: list[str] = []
        for edge in batch:
            if edge["id"] in seen_edge:
                continue
            seen_edge.add(edge["id"])
            edges.append(edge)
            for nid in (edge["src_id"], edge["dst_id"]):
                if nid not in node_map:
                    node = store.get_paper_mem_node(nid)
                    if node and node.get("active", True):
                        node_map[nid] = node
                        next_frontier.append(nid)
        frontier = next_frontier
        if len(node_map) >= max_nodes:
            break

    nodes = list(node_map.values())[:max_nodes]
    keep = {n["id"] for n in nodes}
    edges = [e for e in edges if e["src_id"] in keep and e["dst_id"] in keep]

    by_kind: dict[str, int] = {}
    for n in nodes:
        by_kind[str(n["kind"])] = by_kind.get(str(n["kind"]), 0) + 1

    label = strategy_display_name(slug)
    query_zh = query.strip() if query and str(query).strip() else "全部"
    kind_bits = [
        f"{NODE_KIND_ZH.get(k, k)} {v} 个" for k, v in sorted(by_kind.items())
    ]
    lines = [
        f"【记忆子图】{label} · 检索「{query_zh}」· 节点 {len(nodes)} · 关系 {len(edges)}",
        "种类：" + ("，".join(kind_bits) if kind_bits else "暂无"),
    ]
    for n in nodes[:18]:
        kind_zh = NODE_KIND_ZH.get(str(n["kind"]), str(n["kind"]))
        body = str(n.get("body") or "").strip() or "暂无"
        lines.append(f"- [{kind_zh}] {n.get('title') or '未命名'}：{body[:120]}")
    for e in edges[:12]:
        src = node_map.get(e["src_id"], {}).get("title") or "未知"
        dst = node_map.get(e["dst_id"], {}).get("title") or "未知"
        rel_zh = EDGE_REL_ZH.get(str(e["rel"]), str(e["rel"]))
        lines.append(f"  · {src} —{rel_zh}→ {dst}")

    return {
        "slug": slug,
        "query": query,
        "nodes": nodes,
        "edges": edges,
        "summary": "\n".join(lines),
        "stats": {"nodes": len(nodes), "edges": len(edges), "by_kind": by_kind},
    }


def graph_prompt_block(store: Any, slug: str, query: str = "高开 平开 低开 竞价 教训") -> str:
    result = explore_memory(store, slug, query, max_nodes=20, hops=1)
    return str(result.get("summary") or "")


def rebuild_graph_from_cabin(store: Any, slug: str) -> dict[str, Any]:
    """从 style + lessons 全量重建可 explore 的图。"""
    from src.ops.application.nextday_plan import resolve_entry_mode
    from src.ops.application.paper_style_memory import _default_buy_rules

    mode = resolve_entry_mode(slug)
    seed_default_graph(store, slug, entry_mode=mode)
    style = store.get_paper_style(slug)
    if not style.get("style_md"):
        store.upsert_paper_style(
            slug,
            style_md=default_style_md(slug, entry_mode=mode),
            watch_hints=list(_DEFAULT_WATCH),
            buy_rules=_default_buy_rules(mode),
        )
        style = store.get_paper_style(slug)
    sync_style_doc_to_graph(store, slug, style)
    for lesson in store.list_paper_lessons(slug, limit=80):
        ingest_lesson_to_graph(store, lesson)
    return explore_memory(store, slug, "", max_nodes=40, hops=1)
