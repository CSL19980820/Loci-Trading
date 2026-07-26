"""提前发现雷达 CLI。

输入 watchlist CSV，按“产业证据 + 位置趋势 + 量价资金 + 财务前置信号 + 反证”输出观察池。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from src.discovery import (  # noqa: E402
    analyze_discovery_candidate,
    flatten_result,
    load_watchlist,
    render_discovery_markdown,
)
from src.fetcher import StockFetcher  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="A 股提前发现雷达 - 观察池排序，不构成投资建议",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--watchlist", required=True, help="观察池 CSV，格式见 examples/discovery_watchlist.sample.csv")
    p.add_argument("--days", type=int, default=90, help="K 线回看天数")
    p.add_argument("--output", default=None, help="输出目录，默认 output/discovery_radar_{timestamp}")
    p.add_argument("--formats", default="md,json,csv", help="输出格式: md,json,csv,all")
    p.add_argument("--kline-dir", default=None, help="离线 K 线目录，文件名支持 {code}.csv 或 {code}*.csv")
    p.add_argument("--offline", action="store_true", help="只使用 --kline-dir，不访问网络")
    p.add_argument("--no-fund", action="store_true", help="不拉取资金流")
    p.add_argument("--with-financial", action="store_true", help="额外拉取财务摘要用于前置信号评分")
    p.add_argument("--limit", type=int, default=None, help="最多处理前 N 行 watchlist")
    p.add_argument("--sleep", type=float, default=0.4, help="网络请求之间的暂停秒数")
    return p.parse_args()


def parse_formats(raw: str) -> set[str]:
    formats = {x.strip().lower() for x in raw.split(",") if x.strip()}
    if "all" in formats:
        return {"md", "json", "csv"}
    allowed = {"md", "json", "csv"}
    unknown = formats - allowed
    if unknown:
        raise ValueError(f"未知输出格式: {', '.join(sorted(unknown))}; 可选: md,json,csv,all")
    return formats or {"md", "json", "csv"}


def load_kline_from_dir(kline_dir: str | None, code: str) -> pd.DataFrame | None:
    if not kline_dir:
        return None
    root = Path(kline_dir)
    candidates = [root / f"{code}.csv", root / f"{code}_kline.csv"]
    candidates.extend(sorted(root.glob(f"{code}*.csv")))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            return StockFetcher.load_kline_from_csv(str(path))
    return None


def fetch_candidate_data(args: argparse.Namespace, code: str, name: str) -> dict[str, Any]:
    data: dict[str, Any] = {"kline": load_kline_from_dir(args.kline_dir, code), "fund_flow": None, "financial": None}
    if args.offline:
        return data

    fetcher = StockFetcher(code, name=name)
    if data["kline"] is None:
        print(f"  -> {code} {name}: K线")
        data["kline"] = fetcher.fetch_kline(days=args.days, adjust="qfq")
    if not args.no_fund:
        print(f"  -> {code} {name}: 资金流")
        data["fund_flow"] = fetcher.fetch_fund_flow(days=20)
    if args.with_financial:
        print(f"  -> {code} {name}: 财务摘要")
        data["financial"] = fetcher.fetch_financial_abstract()
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        formats = parse_formats(args.formats)
        items = load_watchlist(args.watchlist)
    except Exception as exc:
        print(f"[错误] 参数或 watchlist 读取失败: {exc}")
        return 2

    if args.limit:
        items = items[: args.limit]
    if not items:
        print("[错误] watchlist 为空")
        return 2
    if args.offline and not args.kline_dir:
        print("[错误] --offline 必须配合 --kline-dir 使用")
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output) if args.output else HERE / "output" / f"discovery_radar_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print("  A 股提前发现雷达")
    print(f"  样本: {len(items)} | 输出: {out_dir}")
    print(f"{'=' * 60}\n")

    results: list[dict[str, Any]] = []
    for i, item in enumerate(items, 1):
        print(f"[{i}/{len(items)}] {item.code} {item.name}")
        try:
            data = fetch_candidate_data(args, item.code, item.name)
            result = analyze_discovery_candidate(
                item,
                data.get("kline"),
                fund_flow=data.get("fund_flow"),
                financial=data.get("financial"),
            )
        except Exception as exc:
            result = {
                "code": item.code,
                "name": item.name,
                "theme": item.theme,
                "score": 0,
                "tier": "异常",
                "hard_rejects": [f"{type(exc).__name__}: {exc}"],
                "metrics": {},
                "components": {},
                "notes": item.notes,
            }
        results.append(result)
        if not args.offline and i < len(items) and args.sleep > 0:
            time.sleep(args.sleep)

    ranked = sorted(results, key=lambda x: float(x.get("score") or 0), reverse=True)
    payload = {
        "template_id": "discovery_radar_v1",
        "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "watchlist": str(Path(args.watchlist).resolve()),
        "disclaimer": "以上仅为公开信息整理与观察框架，不构成投资建议。",
        "results": ranked,
    }

    written: list[tuple[str, Path]] = []
    if "json" in formats:
        path = out_dir / "discovery_radar.json"
        write_json(path, payload)
        written.append(("JSON", path))
    if "csv" in formats:
        path = out_dir / "discovery_radar.csv"
        pd.DataFrame([flatten_result(r) for r in ranked]).to_csv(path, index=False, encoding="utf-8-sig")
        written.append(("CSV", path))
    if "md" in formats:
        path = out_dir / "discovery_radar.md"
        path.write_text(render_discovery_markdown(ranked), encoding="utf-8")
        written.append(("Markdown", path))

    counts: dict[str, int] = {}
    for r in ranked:
        counts[str(r.get("tier"))] = counts.get(str(r.get("tier")), 0) + 1

    print(f"\n{'=' * 60}")
    print("  雷达输出完成")
    for label, path in written:
        print(f"  - {label}: {path}")
    print(f"  分层统计: {counts}")
    top = next((r for r in ranked if r.get("tier") in {"重点观察", "观察", "待证据"}), None)
    if top:
        print(f"  当前第一观察: {top['code']} {top['name']} | {top['tier']} | {top['score']}")
    else:
        print("  当前无观察候选")
    print(f"{'=' * 60}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
