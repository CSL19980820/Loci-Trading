r"""历史日 K 同步引擎：取数并发扇出 + 落库按批合并。

拆出来的原因是 ``sync.py`` 已经贴着 600 行上限，而这里是全仓最热的一条路径，
值得单独一个文件讲清楚它为什么这么排。

旧结构（每票一条流水线）在全市场 5544 只上的实测是 1.61 票/秒、57.5 分钟：

- 每票新建一条 SQLite 连接（含 5 条 PRAGMA），跑完就关
- 每票 4 条点查（watermark / 最早日 / 非 spot 末日 / 因子时间）
- 每票一次 ``BEGIN IMMEDIATE`` 写事务，几个 worker 互抢同一把写锁
- 全局串行限速器，5500 只 × 2 次 × 0.15s ≈ 1650s 的排队地板

新结构把「取数」和「落库」拆成两段：

1. **预热**：几条全市场聚合查询代替 2.2 万次点查（``sync_prefetch``）。
2. **取数**：``workers`` 条线程只做网络，完全不碰 SQLite；结果进有界队列。
3. **落库**：单写线程按批取，一个事务写整批日 K + 回执 + 水位。

队列有界是刻意的——全量回填时单票几千行，无界队列会把内存吃穿；
队列满了自然回压取数线程，等于自动限流。

**有界队列的代价:收尾必须是主动的。** 「队列有界」加上「消费者可能提前离场」
就是一条确定性死锁 —— ``drain`` 一抛异常,还没跑完的 worker 就永远堵在满队列的
``put()`` 上,上层 ``finally: pool.shutdown(wait=True)`` 于是 join 一条永不返回的
线程,同步线程与进程退出双双挂死。所以这里的队列不是裸 ``queue.Queue``,而是带
abort 闸的 ``OutcomeQueue``,线程池也不是裸 ``ThreadPoolExecutor``,而是收尾会
「掀闸 → cancel 未起跑任务 → 边抽干边等」的 ``FetchPool``。细节见这两个类的
文档串;回归测试在 ``tests/market/test_sync_engine_shutdown.py``。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
import queue
import threading
import time
from typing import Any, Callable, Sequence


logger = logging.getLogger(__name__)

#: 增量近窗时的落库批大小。一批 = 一个写事务。
CHUNK_INCREMENTAL = 200
#: 全量回填时的落库批大小。单票动辄六千行，批太大会把一次事务撑成几十万行。
CHUNK_FULL = 40
#: 取数队列相对批大小的倍数；给写线程留缓冲，又不至于囤太多 DataFrame。
_QUEUE_DEPTH_FACTOR = 3
#: drain 的轮询粒度。见 ``drain`` 的注释:超时**不是**放弃条件,
#: 只是让主线程周期性醒过来看一眼 abort 闸。
_DRAIN_POLL_SEC = 0.5
#: worker 在满队列上等一格的粒度;abort 掀闸后最迟这么久它就能醒。
_PUT_POLL_SEC = 0.1
#: 收尾时最多陪没跑完的 worker 等多久。正常是毫秒级。
_SHUTDOWN_GRACE_SEC = 30.0
#: 收尾等待里「抽一次队列」的节奏。
_SHUTDOWN_POLL_SEC = 0.02


@dataclass
class Outcome:
    """一只票的取数终态。写线程只认这个结构，不再回头碰网络。"""

    code: str
    kind: str
    receipt: dict[str, Any] = field(default_factory=dict)
    frame: Any = None
    source: str = ""
    last_date: str = ""
    message: str = ""
    #: (因子表, 来源)；只有本轮判定过期并成功取到时才有值。
    factors: tuple[Any, str] | None = None


def chunk_size_for(force: bool, explicit: int | None) -> int:
    """全量回填用小批、增量用大批；调用方可显式覆盖。"""
    if explicit and explicit > 0:
        return int(explicit)
    return CHUNK_FULL if force else CHUNK_INCREMENTAL


class BatchWriter:
    """单写线程：攒够一批就用一个事务落库。

    SQLite 同一时刻只能有一个写者，多 worker 各开事务只会互相等锁；
    与其让四条线程抢锁，不如一条线程按批写。
    """

    def __init__(
        self,
        store: Any,
        *,
        chunk_size: int,
        on_written: Callable[[str, int, dict[str, Any], str], None],
        on_failed: Callable[[str, str, dict[str, Any]], None],
        on_skipped: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._store = store
        self._chunk = max(1, int(chunk_size))
        self._on_written = on_written
        self._on_failed = on_failed
        self._on_skipped = on_skipped
        self._pending_ok: list[Outcome] = []
        self._pending_other: list[Outcome] = []

    def add(self, outcome: Outcome) -> None:
        if outcome.kind == "ok":
            self._pending_ok.append(outcome)
        else:
            self._pending_other.append(outcome)
        if len(self._pending_ok) >= self._chunk:
            self._flush_ok()
        if len(self._pending_other) >= self._chunk:
            self._flush_other()

    def close(self) -> None:
        self._flush_ok()
        self._flush_other()

    def _write_factors(self, batch: list[Outcome]) -> None:
        """因子与日 K 分开事务：因子稀疏，取失败不该拖垮整批日 K。"""
        for item in batch:
            if item.factors is None:
                continue
            frame, factor_source = item.factors
            try:
                self._store.upsert_adjust_factors(item.code, frame, source=factor_source)
            except Exception as exc:
                logger.debug("写 %s 复权因子失败：%s", item.code, exc)

    def _flush_ok(self) -> None:
        batch = self._pending_ok
        self._pending_ok = []
        if not batch:
            return
        self._write_factors(batch)
        try:
            written_by_code = self._store.persist_quote_frame_receipts(
                [(item.receipt, item.frame, item.source) for item in batch]
            )
        except Exception as exc:
            # 整批事务失败时逐票重试一次：一只坏票不该让另外 199 只也丢。
            logger.warning("批量落库失败，改逐票重试：%s", exc)
            written_by_code = self._retry_one_by_one(batch)
        marks = [
            (item.code, item.last_date)
            for item in batch
            if written_by_code.get(item.code) is not None
        ]
        if marks:
            self._set_watermarks(marks, batch)
        for item in batch:
            written = written_by_code.get(item.code)
            if written is None:
                self._on_failed(item.code, item.message or "落库失败", item.receipt)
            else:
                self._on_written(item.code, int(written), item.receipt, item.source)

    def _retry_one_by_one(self, batch: list[Outcome]) -> dict[str, int]:
        out: dict[str, int] = {}
        for item in batch:
            try:
                out[item.code] = int(
                    self._store.persist_quote_receipt(
                        item.receipt, item.frame, source=item.source
                    )
                )
            except Exception as exc:
                item.message = f"{type(exc).__name__}: {exc}"
                logger.warning("落库 %s 失败：%s", item.code, item.message)
        return out

    def _set_watermarks(self, marks: list[tuple[str, str]], batch: list[Outcome]) -> None:
        """一批水位一次写完。

        这里**曾经把 `except TypeError` 也吞掉**:调用写的是 `sources=`(复数),
        而 store 侧的形参是 `source=`(单数),于是每次批量写都必然 TypeError、
        必然落到下面的逐票兜底——一次全市场同步 5500 多个独立事务,而且没有任何
        日志说它退化了。签名对齐之后不再吞 TypeError:接口对不上是**代码 bug**,
        要当场炸出来,不是运行时悄悄降级的理由。
        """
        sources = {item.code: item.source for item in batch}
        try:
            self._store.set_watermarks(marks, status="ok", sources=sources)
            return
        except Exception as exc:
            # 只兜运行时故障(库忙/锁冲突),逐票重试还有机会成功。
            logger.warning("批量水位写入失败,改逐票:%s", exc)
        for code, last_date in marks:
            try:
                self._store.set_watermark(
                    code,
                    last_trade_date=last_date,
                    status="ok",
                    source=sources.get(code, ""),
                )
            except Exception as exc:
                logger.debug("写 %s 水位失败：%s", code, exc)

    def _flush_other(self) -> None:
        batch = self._pending_other
        self._pending_other = []
        if not batch:
            return
        # watermark 命中而跳过的票同样可能带回刚刷的复权因子，别丢。
        self._write_factors(batch)
        failures = [item for item in batch if item.kind == "fail"]
        if failures:
            for item in failures:
                try:
                    self._store.set_watermark(
                        item.code,
                        status="failed",
                        message=item.message,
                        source=item.source,
                    )
                except Exception:
                    logger.exception("写 %s 的失败 watermark 时又出错", item.code)
        try:
            self._store.persist_source_receipts([item.receipt for item in batch])
        except Exception:
            logger.exception("批量持久化终态回执失败")
        for item in batch:
            if item.kind == "fail":
                self._on_failed(item.code, item.message, item.receipt)
            else:
                self._on_skipped(item.code, item.receipt)


class OutcomeQueue(queue.Queue):
    """有界结果队列,外加一道 **abort 闸**。

    有界是刻意的(见模块头),但「有界」碰上「消费者可能提前离场」就是一条
    确定性死锁:队列满了之后 worker 卡在 ``put()`` 上,而 ``put()`` 只有等消费者
    再 ``get()`` 一次才会返回 —— 消费者已经带着异常走了,永远不会再来。上层的
    ``pool.shutdown(wait=True)`` 于是在 join 一条永不返回的线程。

    闸门把「无限期阻塞」换成「叫得醒的阻塞」:``put_or_abort`` 每
    ``_PUT_POLL_SEC`` 回头看一眼闸,闸一掀就丢下这条结果直接返回。
    丢结果是对的 —— 走到这一步整轮同步已经在异常退出了,再攒也没人写库。
    """

    def __init__(self, maxsize: int) -> None:
        super().__init__(maxsize=maxsize)
        self.aborted = threading.Event()

    def abort(self) -> None:
        """掀闸。之后所有 ``put_or_abort`` 立即返回,不再等消费者。"""
        self.aborted.set()

    def put_or_abort(self, item: "Outcome | None") -> bool:
        """放进队列;闸掀了就放弃。返回是否真的放进去了。"""
        while not self.aborted.is_set():
            try:
                self.put(item, timeout=_PUT_POLL_SEC)
                return True
            except queue.Full:
                continue
        return False

    def purge(self) -> int:
        """抽干队列,返回丢弃条数。抽干本身也是在给 ``put()`` 腾位置。"""
        return _purge(self)


def _is_aborted(outcomes: "queue.Queue[Outcome | None]") -> bool:
    aborted = getattr(outcomes, "aborted", None)
    return bool(aborted is not None and aborted.is_set())


def _abort(outcomes: "queue.Queue[Outcome | None]") -> None:
    """掀闸;传进来的要是普通 Queue(老调用方/测试替身)就静默跳过。"""
    abort = getattr(outcomes, "abort", None)
    if callable(abort):
        abort()


def _purge(outcomes: "queue.Queue[Outcome | None]") -> int:
    dropped = 0
    while True:
        try:
            outcomes.get_nowait()
        except queue.Empty:
            return dropped
        dropped += 1


def _put(outcomes: "queue.Queue[Outcome | None]", item: "Outcome | None") -> bool:
    put_or_abort = getattr(outcomes, "put_or_abort", None)
    if callable(put_or_abort):
        return bool(put_or_abort(item))
    outcomes.put(item)
    return True


class FetchPool(ThreadPoolExecutor):
    """取数线程池,自带一条**有限时间**的收尾路径。

    ``sync.py`` 的收尾写死在 ``finally: pool.shutdown(wait=True)``,所以解锁的
    责任只能落在 shutdown 这一侧。三步缺一不可:

    1. **先掀 abort 闸** —— 卡在满队列 ``put()`` 上的 worker 由此醒来。
        只做第 2 步是不够的:``cancel_futures`` 取消的是**还没起跑**的任务,
        已经跑起来、正堵在 ``put()`` 上的那几条它一根都动不了,而恰恰是它们
        让 ``shutdown(wait=True)`` 永远 join 不完。
    2. **cancel 掉没起跑的任务** —— 否则等于在用户已经 Ctrl-C 之后,还把剩下
        五千多只票老老实实拉完才肯收工。
    3. **边抽干边等** —— 兜住第 1 步的时间差:worker 可能刚好在掀闸前一瞬
        进了 ``put()``,抽干队列能立刻给它腾出位置,不必等它自己超时。

    为什么「光给 ``drain`` 的 ``get()`` 加 timeout」不算修好:超时之后 drain
    无非是再等一轮,真正堵着的是 worker 那一侧的 ``put()``。不从那头把人放出来,
    ``shutdown(wait=True)`` 照样挂死。

    ``cancel_futures`` 的默认值在这里**故意翻成 True**:调用方写的是裸
    ``shutdown(wait=True)``,而到了收尾这一步,没起跑的取数任务一律不该再跑。
    """

    def __init__(
        self, max_workers: int, outcomes: "queue.Queue[Outcome | None]"
    ) -> None:
        super().__init__(max_workers=max_workers, thread_name_prefix="market-fetch")
        self._outcomes = outcomes
        self._counter_lock = threading.Lock()
        self._outstanding = 0
        # 用计数器而不是遍历 futures:全市场 5544 个 future,收尾时每 20ms
        # 扫一遍纯属浪费。
        self._idle = threading.Event()
        self._idle.set()

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        future = super().submit(fn, *args, **kwargs)
        with self._counter_lock:
            self._outstanding += 1
            self._idle.clear()
        # 先加计数再挂回调:任务若已跑完,回调在本线程同步触发,净效果仍是 0。
        future.add_done_callback(self._one_settled)
        return future

    def _one_settled(self, future: Any) -> None:  # noqa: ARG002
        with self._counter_lock:
            self._outstanding -= 1
            if self._outstanding <= 0:
                self._idle.set()

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = True) -> None:
        _abort(self._outcomes)
        super().shutdown(wait=False, cancel_futures=cancel_futures)
        if not wait:
            _purge(self._outcomes)
            return

        deadline = time.monotonic() + _SHUTDOWN_GRACE_SEC
        while not self._idle.wait(_SHUTDOWN_POLL_SEC):
            _purge(self._outcomes)
            if time.monotonic() >= deadline:
                logger.warning(
                    "取数线程池 %.0fs 内没收干净,还有 %d 个任务在跑,放弃等待。"
                    "多半是某个 worker 卡在没有超时的网络调用里 —— 让调用方带着"
                    "错误返回,也好过把整个进程钉死在这里",
                    _SHUTDOWN_GRACE_SEC,
                    self._outstanding,
                )
                return
        _purge(self._outcomes)
        # 走到这儿所有任务都已终结,worker 只会在取下一件活时看到 None 哨兵后退出,
        # join 是有限的。
        super().shutdown(wait=True)


def drain(
    outcomes: "queue.Queue[Outcome | None]",
    writer: BatchWriter,
    expected: int,
    *,
    progress: Callable[[int, str], None] | None = None,
    poll_interval: float = _DRAIN_POLL_SEC,
) -> None:
    """主线程把取数结果排干净。每个 code 恰好产出一个 Outcome。

    ``get`` 上的 timeout **不是**「等不到就放弃」:单票取数几秒钟很正常
    (TDX 冷启探服务器就要 2s),超时即放弃会把慢源误判成结束,让同步报告
    凭空少票 —— 那是比死锁更难查的静默错误。它只是让主线程周期性醒过来
    看一眼 abort 闸,不再是一睡不醒的阻塞。

    真正的修复在异常出口:循环体里任何一处抛异常(progress 回调、writer 的
    MemoryError、Ctrl-C),都必须**先掀闸再抽干**,然后才把异常放出去。
    上层的 ``finally: pool.shutdown(wait=True)`` 这才有可能返回 —— 否则 worker
    还堵在满队列的 ``put()`` 上,join 永远等不到头。顺序不能反:先抽干再掀闸,
    会给 worker 留下一个「刚腾空、闸还没掀」的窗口重新把队列灌满。
    """
    done = 0
    try:
        while done < expected:
            try:
                item = outcomes.get(timeout=poll_interval)
            except queue.Empty:
                if _is_aborted(outcomes):
                    # 取数侧已经被收掉了(比如 fan_out 扇出到一半就炸了),
                    # 剩下的 Outcome 永远不会来,再等就是干等。
                    logger.warning("取数侧已中止,drain 收到 %d/%d 即收尾", done, expected)
                    break
                continue
            if item is None:
                break
            done += 1
            writer.add(item)
            if progress:
                progress(done, item.code)
    except BaseException:
        # BaseException 而不是 Exception:KeyboardInterrupt / SystemExit 走的正是
        # 这条路,而它们恰恰是最常把同步线程留在死锁里的那两个。
        _abort(outcomes)
        dropped = _purge(outcomes)
        logger.warning("drain 异常退出(已消费 %d/%d),丢弃积压 %d 条", done, expected, dropped)
        raise
    writer.close()


def fan_out(
    codes: Sequence[str],
    fetch_one: Callable[[str], Outcome],
    outcomes: "queue.Queue[Outcome | None]",
    *,
    workers: int,
) -> ThreadPoolExecutor:
    """起取数线程池。worker 只做网络与解析,不碰 SQLite。

    每个 code 必须恰好 put 一次,否则主线程的 ``drain`` 会永远等不到收尾 ——
    除非闸已经掀了,那时候少 put 才是对的。

    扇出循环整个包在 try 里:``submit`` 在中途抛错(线程耗尽、MemoryError)时,
    调用方连 pool 引用都拿不到,已经起跑的 worker 会堵在满队列上变成孤儿。
    所以 fan_out 得在把异常放出去之前先自己把池收干净。
    """

    def run(code: str) -> None:
        if _is_aborted(outcomes):
            # 闸已掀:剩下的任务只是排队等着被 cancel,别再打网络了。
            return
        try:
            item = fetch_one(code)
        except BaseException as exc:  # noqa: BLE001 - 少 put 一次就会让 drain 空等
            item = Outcome(
                code=str(code),
                kind="fail",
                message=f"{type(exc).__name__}: {exc}",
            )
        _put(outcomes, item)

    pool = FetchPool(max(1, int(workers)), outcomes)
    try:
        for code in codes:
            pool.submit(run, code)
    except BaseException:
        logger.exception("扇出取数任务时中断,提前收掉线程池,免得它成为孤儿")
        pool.shutdown(wait=True)
        raise
    return pool


def make_queue(chunk_size: int) -> OutcomeQueue:
    return OutcomeQueue(maxsize=max(1, chunk_size) * _QUEUE_DEPTH_FACTOR)


class RateLimiter:
    """请求节奏闸：``min_interval`` 是**每个 worker 槽位**的最小间隔，
    而不是全进程一条串行队列。

    旧实现是全局互斥 + 单调水位：无论开几个 worker，全市场同步都要付
    ``票数 × 2 × min_interval`` 的排队地板（5500 只 × 2 次 × 0.15s ≈ 1650s），
    并发调多大都推不动——这是「同步为什么这么慢」的头号原因。

    真正的礼貌约束在别处：每个 (lane, 源) 的在途名额门闩（``router_live``）
    限的是并发连接数，那才是来源会介意的东西。这里只保留「单槽位别打太密」，
    聚合速率 = ``slots / min_interval``。
    """

    def __init__(self, min_interval: float, *, slots: int = 1) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.slots = max(1, int(slots))
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        if self.min_interval <= 0:
            return
        spacing = self.min_interval / float(self.slots)
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + spacing
        if sleep_for > 0:
            time.sleep(sleep_for)
