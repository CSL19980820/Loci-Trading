r"""行情数据源全面测量：单票时延、并发吞吐、批量宽度、字段完整度。

用法（仓库根目录）::

    .\.venv\Scripts\python.exe scripts\benchmark_data_sources.py --codes 40

只读网络与 market.db，不写任何库。结果落 output/data-source-benchmark/。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CANONICAL = ("date", "open", "high", "low", "close", "volume", "amount", "turnover")


# ---------------------------------------------------------------- sampling
def sample_codes(n: int, seed: int = 7) -> list[str]:
    """从真实 market.db 抽样；取不到就用内置兜底名单。"""
    from src.shared import paths
    
    fallback = ["600000", "000001", "600519", "000002", "300750", "688981",
               "002594", "601318", "000858", "600036"]
    db = Path(paths.market_db())
    if not db.exists() or db.stat().st_size == 0:
        return (fallback * ((n // len(fallback)) + 1))[:n]
    conn = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=20)
    try:
        rows = conn.execute(
            "SELECT code FROM instruments WHERE instrument_type='STOCK' ORDER BY code"
        ).fetchall()
    finally:
        conn.close()
    codes = [str(r[0]) for r in rows if str(r[0]).isdigit()]
    if not codes:
        return (fallback * ((n // len(fallback)) + 1))[:n]
    rng = random.Random(seed)
    rng.shuffle(codes)
    return codes[:n]


def universe_size() -> int:
    from src.shared import paths
    
    db = Path(paths.market_db())
    if not db.exists() or db.stat().st_size == 0:
        return 5500
    conn = sqlite3.connect("file:%s?mode=ro" % db.as_posix(), uri=True, timeout=20)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM instruments WHERE instrument_type='STOCK'"
        ).fetchone()
    finally:
        conn.close()
    return int(row[0] or 5500)


# ---------------------------------------------------------------- fetchers
def _repo_adapter(adapter_id: str):
    from src.market.infrastructure.adapters import get_adapter
    
    return get_adapter(adapter_id)


def make_repo_fetcher(adapter_id: str, bars: int | None):
    """仓内适配器 → (code) -> (rows, columns)。bars=None 取全历史。"""
    adapter = _repo_adapter(adapter_id)
    
    def fetch(code: str):
        if bars is None:
            frame = adapter.fetch_daily(code)
        else:
            frame = adapter.fetch_daily_window(code, bars=bars)
        return int(len(frame)), tuple(str(c) for c in frame.columns)
    
    return fetch


# --- TDX 二进制协议（tdxpy）：每线程一条长连接 -------------------------------
TDX_HOSTS = (
    ("115.238.90.165", 7709), ("124.71.187.122", 7709), ("119.147.212.81", 7709),
    ("218.6.170.47", 7709), ("123.125.108.14", 7709), ("124.160.88.183", 7709),
    ("110.41.147.114", 7709), ("47.103.48.45", 7709), ("222.161.249.101", 7709),
)

_TDX_LOCAL = threading.local()
_TDX_BEST: list = []
_TDX_BEST_LOCK = threading.Lock()


def tdx_market(code: str) -> int:
    """0=深/北, 1=沪。TDX 把北交所并入深市段（8/4 开头走 market 2 在部分服务端不可用）。"""
    head = code[:1]
    if head in ("6", "9"):
        return 1
    if code[:2] in ("11", "13"):
        return 1
    return 0


def rank_tdx_hosts(timeout: float = 2.0) -> list:
    """按握手 + 一次探测报文的 RTT 给服务器排序，只保留活着的。"""
    from tdxpy.hq import TdxHq_API
    
    scored = []
    for host, port in TDX_HOSTS:
        api = TdxHq_API(raise_exception=True, auto_retry=False)
        started = time.perf_counter()
        try:
            with api.connect(host, port, time_out=timeout):
                bars = api.get_security_bars(9, 1, "600000", 0, 8)
            if bars:
                scored.append((time.perf_counter() - started, host, port))
        except Exception:
            continue
    scored.sort()
    return [(h, p) for _rtt, h, p in scored]


def tdx_conn():
    """取当前线程的 TDX 连接；断了就换下一台服务器重连。"""
    from tdxpy.hq import TdxHq_API
    
    api = getattr(_TDX_LOCAL, "api", None)
    if api is not None:
        return api
    with _TDX_BEST_LOCK:
        if not _TDX_BEST:
            _TDX_BEST.extend(rank_tdx_hosts() or list(TDX_HOSTS))
        hosts = list(_TDX_BEST)
    ident = threading.get_ident()
    for offset in range(len(hosts)):
        host, port = hosts[(ident + offset) % len(hosts)]
        candidate = TdxHq_API(raise_exception=True, auto_retry=True)
        try:
            candidate.connect(host, port, time_out=6)
        except Exception:
            continue
        _TDX_LOCAL.api = candidate
        _TDX_LOCAL.host = host
        return candidate
    raise RuntimeError("no reachable tdx host")


TDX_PAGE = 800


def tdx_fetch_daily(code: str, bars: int | None):
    """TDX 日线。bars=None 时翻页取全历史（每页 800 根）。"""
    api = tdx_conn()
    market = tdx_market(code)
    want = bars if bars else 10 ** 6
    out = []
    start = 0
    while len(out) < want:
        count = min(TDX_PAGE, want - len(out))
        page = api.get_security_bars(9, market, code, start, count)
        if not page:
            break
        out = list(page) + out
        start += len(page)
        if len(page) < count:
            break
    cols = tuple(sorted(out[0].keys())) if out else ()
    return len(out), cols


def make_tdx_fetcher(bars: int | None):
    def fetch(code: str):
        return tdx_fetch_daily(code, bars)
    
    return fetch


# --- 东财全市场快照（一次请求拿全市场当日行情） ------------------------------
EM_CLIST_FIELDS = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f14,f15,f16,f17,f18,f20,f21,f23"
EM_CLIST_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"


def em_clist_page(page: int, size: int):
    import requests
    
    params = {
        "pn": page, "pz": size, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f3", "fs": EM_CLIST_FS, "fields": EM_CLIST_FIELDS,
    }
    resp = requests.get(
        "https://push2.eastmoney.com/api/qt/clist/get",
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=15,
    )
    data = resp.json().get("data") or {}
    return int(data.get("total") or 0), list(data.get("diff") or []), len(resp.content)


def measure_em_clist() -> dict:
    """量东财全市场快照的真实分页上限与全量耗时。"""
    probe = {}
    for size in (100, 200, 500, 1000, 2000, 6000):
        try:
            total, rows, _b = em_clist_page(1, size)
            probe[size] = len(rows)
        except Exception as exc:
            probe[size] = "ERR %s" % type(exc).__name__
    usable = [s for s, got in probe.items() if isinstance(got, int) and got > 0]
    best = max(usable) if usable else 100
    per_page = probe.get(best) or 100
    started = time.perf_counter()
    total, rows, nbytes = em_clist_page(1, best)
    collected = list(rows)
    pages = 1
    while len(collected) < total and pages < 80:
        pages += 1
        _t, more, extra = em_clist_page(pages, best)
        if not more:
            break
        collected.extend(more)
        nbytes += extra
    elapsed = time.perf_counter() - started
    return {
        "page_size_probe": probe,
        "rows_per_request": per_page,
        "total_reported": total,
        "rows_fetched": len(collected),
        "requests": pages,
        "seconds": round(elapsed, 3),
        "bytes": nbytes,
    }


# ---------------------------------------------------------------- measuring
def run_lane(fetch, codes: list[str], workers: int, budget_sec: float = 240.0) -> dict:
    """并发跑一批代码，记录每票时延与失败。budget 到点就停，避免整轮卡死。"""
    lat: list[float] = []
    cols_seen: set = set()
    errors: dict = {}
    lock = threading.Lock()
    deadline = time.perf_counter() + budget_sec
    
    def one(code: str):
        if time.perf_counter() > deadline:
            return
        started = time.perf_counter()
        try:
            nrows, cols = fetch(code)
        except Exception as exc:
            with lock:
                key = type(exc).__name__
                errors[key] = errors.get(key, 0) + 1
            return
        took = time.perf_counter() - started
        with lock:
            lat.append(took)
            cols_seen.update(cols)
        return nrows
    
    wall = time.perf_counter()
    collected = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(one, c) for c in codes]
        for fut in as_completed(futures):
            got = fut.result()
            if got:
                collected.append(got)
    wall = time.perf_counter() - wall
    ok = len(lat)
    return {
        "workers": workers,
        "asked": len(codes),
        "ok": ok,
        "failed": len(codes) - ok,
        "errors": errors,
        "wall_sec": round(wall, 3),
        "codes_per_sec": round(ok / wall, 2) if wall > 0 else 0.0,
        "p50_ms": round(statistics.median(lat) * 1000, 1) if lat else None,
        "p90_ms": round(sorted(lat)[int(len(lat) * 0.9)] * 1000, 1) if len(lat) > 4 else None,
        "bars_median": int(statistics.median(collected)) if collected else 0,
        "columns": sorted(cols_seen),
    }


def coverage(columns) -> dict:
    """字段完整度：命中几个仓内规范列。"""
    lower = {str(c).lower() for c in columns}
    alias = {
        "date": ("date", "trade_date", "datetime", "day"),
        "open": ("open",),
        "high": ("high",),
        "low": ("low",),
        "close": ("close", "price"),
        "volume": ("volume", "vol"),
        "amount": ("amount", "turnover_amount"),
        "turnover": ("turnover", "turn", "turnover_rate"),
    }
    hit = {}
    for canon, names in alias.items():
        hit[canon] = any(n in lower for n in names)
    return hit


# ---------------------------------------------------------------- scenarios
def build_sources(bars: int | None):
    """(id, label, fetcher) 列表。仓内适配器懒构造，缺依赖不炸整轮。"""
    out = []
    for adapter_id, label in (
        ("tencent", "腾讯 fqkline"),
        ("eastmoney", "东财 akshare hist"),
        ("baostock", "证券宝"),
        ("sina", "新浪"),
    ):
        try:
            out.append((adapter_id, label, make_repo_fetcher(adapter_id, bars)))
        except Exception as exc:
            print("  skip %-10s %s: %s" % (adapter_id, label, exc))
    try:
        import tdxpy  # noqa: F401
        out.append(("tdx", "通达信二进制", make_tdx_fetcher(bars)))
    except Exception as exc:
        print("  skip tdx: %s" % exc)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="行情数据源全面测量")
    parser.add_argument("--codes", type=int, default=30, help="抽样标的数")
    parser.add_argument("--bars", type=int, default=320, help="近窗根数；0=全历史")
    parser.add_argument("--workers", default="1,4,8,16", help="并发梯度")
    parser.add_argument("--budget", type=float, default=180.0, help="单场景墙钟预算秒")
    parser.add_argument("--skip-clist", action="store_true")
    parser.add_argument("--only", default="", help="只测这些源，逗号分隔")
    args = parser.parse_args()
    
    os.environ.setdefault("LOCI_MARKET_BENCH", "1")
    bars = None if args.bars <= 0 else int(args.bars)
    codes = sample_codes(args.codes)
    total_codes = universe_size()
    gradient = [int(x) for x in str(args.workers).split(",") if x.strip()]
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    
    print("=" * 78)
    print("行情数据源测量  样本=%d 只  窗口=%s  全市场=%d 只" % (
        len(codes), ("全历史" if bars is None else "%d 根" % bars), total_codes))
    print("=" * 78)
    
    report: dict = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample_codes": codes,
        "universe": total_codes,
        "window_bars": bars,
        "per_code": {},
        "batch": {},
    }
    
    if not args.skip_clist:
        print("\n[批量] 东财全市场快照 clist ...")
        try:
            clist = measure_em_clist()
            report["batch"]["eastmoney_clist"] = clist
            print("  分页探测: %s" % clist["page_size_probe"])
            print("  全市场 %d 行 / %d 次请求 / %.2fs  → %.0f 行/秒" % (
                clist["rows_fetched"], clist["requests"], clist["seconds"],
                clist["rows_fetched"] / max(clist["seconds"], 1e-6)))
        except Exception as exc:
            print("  失败: %s: %s" % (type(exc).__name__, exc))
            report["batch"]["eastmoney_clist"] = {"error": str(exc)[:200]}
    
    sources = build_sources(bars)
    for source_id, label, fetch in sources:
        if only and source_id not in only:
            continue
        print("\n[逐票] %s (%s)" % (source_id, label))
        runs = []
        for workers in gradient:
            try:
                res = run_lane(fetch, codes, workers, budget_sec=args.budget)
            except Exception as exc:
                print("  workers=%-3d 整轮失败 %s: %s" % (workers, type(exc).__name__, exc))
                break
            runs.append(res)
            projected = (total_codes / res["codes_per_sec"]) if res["codes_per_sec"] else None
            res["projected_full_market_sec"] = round(projected, 1) if projected else None
            print("  workers=%-3d ok=%-3d fail=%-3d %6.2f 票/秒  p50=%sms  "
                "全市场约 %s  %s" % (
                workers, res["ok"], res["failed"], res["codes_per_sec"], res["p50_ms"],
                ("%.0fs" % projected) if projected else "-",
                ("errors=%s" % res["errors"]) if res["errors"] else ""))
            if res["ok"] == 0:
                break
        if runs:
            best = max(runs, key=lambda r: r["codes_per_sec"])
            cov = coverage(best["columns"])
            missing = [k for k, v in cov.items() if not v]
            print("  字段: %d/%d  缺 %s" % (len(cov) - len(missing), len(cov), missing or "无"))
            print("  单票根数中位数: %s" % best["bars_median"])
            report["per_code"][source_id] = {
                "label": label, "runs": runs, "coverage": cov,
                "missing_fields": missing, "columns": best["columns"],
            }
    
    outdir = ROOT / "output" / "data-source-benchmark"
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = outdir / ("benchmark-%s.json" % stamp)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n报告: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
