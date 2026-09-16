r"""通达信（TDX）日线读取：二进制协议，全市场主数据源。

选它做 hist_daily 主源的实测依据（``scripts/benchmark_data_sources.py``）：
单票 p50 28ms、并发 8 路 166 票/秒，全市场 5544 只约 33s；同口径下腾讯 445s、
新浪 315s、证券宝 9726s。价格与成交量对照库内 3000 个格点零偏差。

成交额还比腾讯准：腾讯日 K 的 ``amount`` 是 ``close * volume`` 合成值
（库内实测比值恒为 1.0000），TDX 给的是真实成交额。

协议是二进制、没有中文源列，按 ``src/market/README.md`` 的既定例外，
单位在本 fetcher 内定死（``vol`` 是手，×100 转股），出去就是仓内口径。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from itertools import count
import os
from pathlib import Path
import threading
import time
from typing import Any

import pandas as pd

from src.market.infrastructure.store_codes import normalize_code
from src.market.infrastructure.tdx_servers import _SERVERS


#: 服务器排序缓存有效期。行情服务器名单变化以周计，6 小时足够新，
#: 又能让桌面端反复启动不再每次白等一轮探测。
_CACHE_TTL_SEC = 6 * 3600.0


class TdxDailyError(RuntimeError):
    """通达信日线读取失败。"""


#: 单次请求最多 800 根——协议上限，再大服务端直接截断。
PAGE_BARS = 800
#: 全历史翻页硬上限：A 股最长约 8800 个交易日，给到 16000 根足够且能防呆。
_MAX_BARS = 16000
#: 日线类别号（0=5分钟 … 9=日线）。
_CATEGORY_DAY = 9
#: 指数所在市场。中证/沪深系列指数（000300 / 000905 / 000852）在 TDX 全部
#: 挂在 market 1，且必须用 ``get_index_bars``——用 ``get_security_bars`` 问
#: 同一个代码拿到的是深市同号**股票**，静默串号。
_INDEX_MARKET = 1
#: 握手超时。公开服务器丢包常见，短超时 + 换机器比长等划算。
_CONNECT_TIMEOUT = 4.0
#: 一条连接连续失败这么多次就重建——TDX 长连接被服务端静默掐掉时
#: 表现为「返回空」而不是抛错，只靠异常判活会一直拿空表。
_MAX_CONN_FAILURES = 3

_LOCAL = threading.local()
_HOST_SEQUENCE = count()
_RANKED: list[tuple[str, int]] = []
_RANK_LOCK = threading.Lock()
#: 单次建连最多试几台。整池挂掉时走完全池 × 4s 超时 = 152s，而这条路径
#: 每一票都会重来；4 台足够躲开个别机器抽风，又把最坏情况压在 16s 内。
_CONNECT_HOST_BUDGET = 4

#: 整池重探后仍无一台可用时的冷却期。没有它，主源被限流期间每一票都要再
#: 付一次全池并发探测（约 2s）+ 4 台建连（约 16s），全市场同步等于原地罚站。
#: 冷却期内直接快速失败，让路由立刻换源——降级要快，不是要执着。
_POOL_DOWN_COOLDOWN_SEC = 120.0
_pool_down_until = 0.0


def tdx_market(code: str) -> int:
    """仓内 6 位代码 → TDX 市场号。

    0=深、1=沪、2=北。北交所 ``920xxx`` 只在 market 2 上有数据（实测 market 0/1
    返回空表），漏了这条会让 339 只北交所票静默缺数。
    """
    plain = str(code).strip()
    if plain.startswith("92") or plain.startswith("83") or plain.startswith("87"):
        return 2
    if plain.startswith("43"):
        return 2
    if plain[:1] in ("6", "9") or plain[:2] in ("11", "13"):
        return 1
    return 0


def _servers() -> tuple[tuple[str, int], ...]:
    """允许用环境变量覆盖服务器池（内网镜像 / 自建行情机）。"""
    raw = str(os.environ.get("LOCI_TDX_SERVERS") or "").strip()
    if not raw:
        return _SERVERS
    out: list[tuple[str, int]] = []
    for item in raw.split(","):
        piece = item.strip()
        if not piece:
            continue
        host, _, port = piece.partition(":")
        try:
            out.append((host.strip(), int(port or 7709)))
        except ValueError:
            continue
    return tuple(out) or _SERVERS


def _api_class() -> Any:
    """tdxpy 只在真正取数时导入；缺依赖时错误要说人话。"""
    try:
        from tdxpy.hq import TdxHq_API
    except Exception as exc:  # pragma: no cover - 依赖缺失
        raise TdxDailyError("未安装 tdxpy，无法使用通达信日线") from exc
    return TdxHq_API


def _cache_path():
    """服务器排序缓存文件。取不到数据目录就返回 None（纯内存降级）。"""
    try:
        from src.shared import paths

        return Path(paths.data_dir()) / "tdx_servers.json"
    except Exception:
        return None


def _read_cache():
    """读磁盘缓存的存活服务器；过期或损坏返回空。"""
    path = _cache_path()
    if path is None or not path.exists():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(blob.get("at") or 0) > _CACHE_TTL_SEC:
            return []
        return [(str(h), int(p)) for h, p in blob.get("hosts") or []]
    except Exception:
        return []


def _drop_cache() -> None:
    """作废服务器排序缓存。缓存里那几台一起挂掉时必须能重探，否则 TTL 内
    整条主源静默全废。"""
    path = _cache_path()
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _write_cache(hosts) -> None:
    path = _cache_path()
    if path is None or not hosts:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            dict(at=time.time(), hosts=[[h, p] for h, p in hosts]), ensure_ascii=False
        )
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        # 缓存只是加速，写不进去不该影响取数。
        pass


def _probe_one(host: str, port: int, timeout: float):
    """握手 + 一次小请求，返回往返耗时；不可用返回 None。"""
    api_class = _api_class()
    api = api_class(raise_exception=True, auto_retry=False)
    began = time.perf_counter()
    try:
        with api.connect(host, port, time_out=timeout):
            probe = api.get_security_bars(_CATEGORY_DAY, 1, "600000", 0, 4)
    except Exception:
        return None
    if not probe:
        return None
    return time.perf_counter() - began


def rank_servers(*, timeout: float = 2.0, use_cache: bool = True) -> list:
    """按往返耗时给服务器排序，只留活着的。

    **并发探测**：公开服务器里常有大半是死的，串行探测每台都要吃满超时，
    实测 10 台串行 10.4s、只有 2 台活着。并发后压到一次超时的时间。

    结果落磁盘缓存（TTL 6 小时）：桌面端每次启动都重新探测一遍，
    等于每次开机白等十秒。
    """
    if use_cache:
        cached = _read_cache()
        if cached:
            return cached
    pool = ThreadPoolExecutor(max_workers=len(_servers()) or 1)
    scored = []
    try:
        futures = {
            pool.submit(_probe_one, host, port, timeout): (host, port)
            for host, port in _servers()
        }
        for future in as_completed(futures, timeout=timeout * 3):
            host, port = futures[future]
            try:
                rtt = future.result()
            except Exception:
                continue
            if rtt is not None:
                scored.append((rtt, host, port))
    except TimeoutError:
        pass  # 慢节点不能抹掉已经返回的健康节点。
    finally:
        pool.shutdown(wait=False)
    scored.sort()
    hosts = [(host, port) for _rtt, host, port in scored]
    if use_cache:
        _write_cache(hosts)
    return hosts


def _ranked_servers() -> list[tuple[str, int]]:
    with _RANK_LOCK:
        if not _RANKED:
            _RANKED.extend(rank_servers() or list(_servers()))
        return list(_RANKED)


def reset_servers() -> None:
    """测试/排障用：清空排序结果、整池冷却与本线程连接，下次取数重新探测。"""
    with _RANK_LOCK:
        _RANKED.clear()
    _clear_pool_down()
    _drop_connection()


def _drop_connection() -> None:
    api = getattr(_LOCAL, "api", None)
    _LOCAL.api = None
    _LOCAL.failures = 0
    if api is None:
        return
    try:
        api.disconnect()
    except Exception:
        pass


def _try_hosts(hosts: list, api_class: Any, *, budget: int) -> tuple[Any, list[str]]:
    """按轮询序号错开起点连，**最多试 ``budget`` 台**；返回 (连接, 失败原因)。

    有预算这件事是必需的：整池不可用时，走完 38 台 × 4s 超时就是 152s，
    而这条路径在每一票上都会重来一次——全市场同步会直接跑不完。
    """
    if not hosts:
        return None, []
    # 线程 ID 常按 8/16 对齐，取模会让所有线程挤在同一台；用原生计数器轮询。
    offset = next(_HOST_SEQUENCE) % len(hosts)
    errors: list[str] = []
    for step in range(min(len(hosts), max(1, int(budget)))):
        host, port = hosts[(offset + step) % len(hosts)]
        candidate = api_class(raise_exception=True, auto_retry=True)
        try:
            candidate.connect(host, port, time_out=_CONNECT_TIMEOUT)
            # 握手/证券数量可用，不代表 K 线可用；坏节点会只回数量头。
            if not candidate.get_security_bars(_CATEGORY_DAY, 1, "600000", 0, 1):
                raise TdxDailyError("握手成功但日 K 探测为空")
        except Exception as exc:
            cause = exc.__cause__ or exc.__context__ or exc
            errors.append(f"{host}:{port} {type(cause).__name__}: {cause}")
            try:
                candidate.disconnect()
            except Exception:
                pass
            continue
        _LOCAL.api = candidate
        _LOCAL.host = f"{host}:{port}"
        _LOCAL.failures = 0
        return candidate, errors
    return None, errors
def _pool_down() -> bool:
    """整池刚被判死且还在冷却期内。"""
    return time.monotonic() < _pool_down_until


def _mark_pool_down() -> None:
    global _pool_down_until
    _pool_down_until = time.monotonic() + _POOL_DOWN_COOLDOWN_SEC


def _clear_pool_down() -> None:
    global _pool_down_until
    _pool_down_until = 0.0


def _connection() -> Any:
    """当前线程的长连接；没有就按 RTT 顺序建一条。

    每线程一条连接是这个源快的关键：TDX 是有状态长连接，逐次请求复用同一条
    socket 时单请求只有 ~28ms；每票重连会把握手成本（~200ms）加回来。

    三条护栏，都是踩出来的：

    1. **缓存要能自愈**：排序结果落磁盘（TTL 6 小时）本为省启动探测，但缓存
       钉住的那几台一起挂掉时，旧实现会在 6 小时里每次都失败且永不重探——
       整条主源静默全废。所以缓存名单连不上就作废缓存、对全池重探一次。
    2. **单次建连有预算**：整池不可用时走完 38 台 × 4s = 152s，而这条路径每票
     都会重来。只试 ``_CONNECT_HOST_BUDGET`` 台。
    3. **整池判死后进冷却**：没有冷却，被限流期间每一票都要再付一次全池探测 +
       建连（实测单票 308s，全市场根本跑不完）。冷却期内直接快速失败，
       让路由立刻换源。降级要快，不是要执着。
    """
    api = getattr(_LOCAL, "api", None)
    if api is not None:
        return api
    if _pool_down():
        raise TdxDailyError(
            "通达信整池刚判定不可用，冷却中（%ds 内不再重试）"
            % int(_POOL_DOWN_COOLDOWN_SEC)
        )
    api_class = _api_class()

    candidate, errors = _try_hosts(
        _ranked_servers(), api_class, budget=_CONNECT_HOST_BUDGET
    )
    if candidate is not None:
        _clear_pool_down()
        return candidate

    # 缓存名单连不上：清缓存 + 全池并发重探（约 2s），再试一轮。
    with _RANK_LOCK:
        _RANKED.clear()
    _drop_cache()
    fresh = rank_servers(use_cache=False)
    with _RANK_LOCK:
        _RANKED.clear()
        _RANKED.extend(fresh)
    candidate, retry_errors = _try_hosts(
        fresh, api_class, budget=_CONNECT_HOST_BUDGET
    )
    if candidate is not None:
        _clear_pool_down()
        return candidate
    _mark_pool_down()
    raise TdxDailyError(
        "通达信服务器全部连接失败（全池 %d 台重探后仍无可用，冷却 %ds）-> "
        % (len(_servers()), int(_POOL_DOWN_COOLDOWN_SEC))
        + " | ".join((retry_errors or errors)[-4:])
    )


def current_server() -> str:
    """本线程当前连的服务器，供回执/诊断记录。"""
    return str(getattr(_LOCAL, "host", "") or "")


def _note_failure() -> None:
    """连续拿空/报错到阈值就丢连接重建。"""
    count = int(getattr(_LOCAL, "failures", 0)) + 1
    _LOCAL.failures = count
    if count >= _MAX_CONN_FAILURES:
        _drop_connection()


def _pull_pages(
    code: str, market: int, want: int, *, is_index: bool = False
) -> list[dict]:
    """从最新往回翻页，直到够 ``want`` 根或源没有更早数据。

    ``start`` 是「距最新第几根」，所以每页拿到的是更早的一段，要前插。

    指数走 ``get_index_bars``：同一个代码在两套协议里指向不同证券，
    用错的那套不报错、只是把别人的行情给你。
    """
    api = _connection()
    pull = api.get_index_bars if is_index else api.get_security_bars
    out: list[dict] = []
    start = 0
    while len(out) < want and start < _MAX_BARS:
        count = min(PAGE_BARS, want - len(out))
        page = pull(_CATEGORY_DAY, market, code, start, count)
        if not page:
            break
        out = list(page) + out
        start += len(page)
        if len(page) < count:
            break
    return out


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["date", "open", "high", "low", "close", "volume", "amount"]
    )


def _rows_to_frame(rows: list[dict]) -> pd.DataFrame:
    """原始 bar 列表 → 仓内口径日线表。

    这里就是本源的单位定义处：``vol`` 是手，×100 得股；``amount`` 已是元。
    换手率源侧没有，留给仓内 ``turnover_repair`` 用流通股本推。
    """
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame(rows)
    if "datetime" not in frame.columns:
        return _empty_frame()
    # pytdx 的 bar 里 ``datetime`` 是 ``YYYY-MM-DD HH:MM`` 文本（日线固定 15:00），
    # year-first。显式 format 省掉逐值推断，也避免推断错格式后整列静默变 NaT——
    # 下面 dropna 会把它们当成「源没给数据」丢掉，比不优化坏得多。
    stamp = pd.to_datetime(frame["datetime"], format="ISO8601", errors="coerce")
    out = pd.DataFrame({"date": stamp.dt.strftime("%Y-%m-%d")})
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(frame.get(column), errors="coerce")
    out["volume"] = pd.to_numeric(frame.get("vol"), errors="coerce") * 100.0
    out["amount"] = pd.to_numeric(frame.get("amount"), errors="coerce")
    out = out.dropna(subset=["date", "close"])
    # 翻页边界可能重复同一天；保留最后一条（最新那次返回）。
    out = out.drop_duplicates(subset=["date"], keep="last")
    return out.sort_values("date").reset_index(drop=True)


def fetch_daily_bars(
    code: str, *, bars: int | None = None, instrument_type: str = "STOCK"
) -> pd.DataFrame:
    """取单票日线。``bars=None`` 翻页取全历史。

    返回列：date/open/high/low/close/volume/amount，已是仓内口径。

    ``instrument_type`` **必须传对**：指数与股票在 TDX 是两套协议，走错那套
    不会报错，会安静地返回**另一个证券**的行情。实测 ``get_security_bars``
    问 ``000905`` 拿回的是深市股票（收盘 8.54），而中证 500 指数当天是
    7717——两个数量级的差别，落进基准指数后所有相对收益都会错。
    """
    plain = normalize_code(code)
    is_index = str(instrument_type or "STOCK").upper() == "INDEX"
    market = _INDEX_MARKET if is_index else tdx_market(plain)
    want = _MAX_BARS if bars is None else max(1, min(int(bars), _MAX_BARS))
    try:
        rows = _pull_pages(plain, market, want, is_index=is_index)
    except TdxDailyError:
        raise
    except Exception as exc:
        _note_failure()
        raise TdxDailyError(f"通达信日线 {plain} 失败：{type(exc).__name__}: {exc}") from exc
    if not rows:
        # 空表既可能是「这只票真没数据」，也可能是连接被静默掐断；
        # 计一次失败，连着几次就重建连接，避免整条线程后续全空。
        _note_failure()
        raise TdxDailyError(f"通达信日线 {plain} 返回空数据")
    _LOCAL.failures = 0
    frame = _rows_to_frame(rows)
    if frame.empty:
        raise TdxDailyError(f"通达信日线 {plain} 解析后为空")
    return frame


def fetch_daily_many(
    codes: list[str],
    *,
    bars: int | None = None,
    workers: int = 8,
    instrument_types: dict[str, str] | None = None,
) -> dict[str, pd.DataFrame]:
    """批量取日线：一条线程一条长连接，按票扇出。

    这是本源相对 HTTP 源的真正优势位——单请求 28ms 且服务端不按票限流，
    8~16 路并发能到 170~220 票/秒。失败的票不进返回值，由调用方决定回退。

    ``instrument_types`` 缺省时按股票处理；指数**必须**显式声明，
    否则会取回同代码的那只股票（见 ``fetch_daily_bars``）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    types = dict(instrument_types or ())
    wanted = [str(c).strip() for c in codes if str(c).strip()]
    if not wanted:
        return {}
    out: dict[str, pd.DataFrame] = {}
    lock = threading.Lock()

    def one(code: str) -> None:
        try:
            frame = fetch_daily_bars(
                code, bars=bars, instrument_type=types.get(code, "STOCK")
            )
        except Exception:
            return
        with lock:
            out[normalize_code(code)] = frame

    width = max(1, min(int(workers), len(wanted)))
    with ThreadPoolExecutor(max_workers=width) as pool:
        futures = [pool.submit(one, code) for code in wanted]
        for future in as_completed(futures):
            future.result()
    return out


def fetch_instrument_codes() -> dict[str, list[str]]:
    """从 TDX 证券列表拉全市场代码，按市场分组。诊断/覆盖核对用。"""
    api = _connection()
    out: dict[str, list[str]] = {"sz": [], "sh": [], "bj": []}
    names = {0: "sz", 1: "sh", 2: "bj"}
    for market, key in names.items():
        start = 0
        while True:
            try:
                page = api.get_security_list(market, start)
            except Exception:
                break
            if not page:
                break
            out[key].extend(str(item.get("code") or "") for item in page)
            start += len(page)
            if len(page) < 1000 or start > 40000:
                break
    return out
