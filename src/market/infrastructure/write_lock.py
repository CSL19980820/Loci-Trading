"""行情库跨进程写锁：sync / spot 互斥，避免双进程把 SQLite 顶成 locked。

线程闸门（ops.market_gate）只管同进程；桌面壳 Loci.exe 与 CLI/调度是不同进程。
这里用文件锁串行化「会长时间写 market.db」的路径。

同进程可重入（sync 外层占锁后内部 spot 再进不会死锁）。

**进程内排队同样有上限**。早期实现用无超时的 ``with local:`` 串行化同进程线程，
于是「同步卡在某个网络阶段」会升级成全进程写入瘫痪：后来者永远醒不过来，也就
永远不放开自己在 ops.market_gate 里的读槽，日终同步于是天天以「行情库正被选股
占用」收场。现在跨线程等待与文件锁共用一个 deadline —— 等不到就抛
``MarketWriteBusy`` 并指名真正的持锁者，让上层快速失败、放开自己的槽位。

**等待上限 ≠ 卡死阈值**。全市场同步跑十几分钟很正常，旧的 120s deadline 让
「排在正常同步后面」几乎必然超时，还一律写「疑似卡死」，天天造假故障。现在：

- 等待上限 ``_LOCK_WAIT_SEC`` 默认 600s，可用环境变量
  ``LOCI_MARKET_WRITE_WAIT_SEC`` 覆盖；
- 只有持锁时长超过独立的卡死阈值 ``_LOCK_STUCK_SEC``（默认 30 分钟，
  ``LOCI_MARKET_WRITE_STUCK_SEC`` 可覆盖）才说「疑似卡死」，否则文案是
  「行情库正在同步（已 N 分钟），请稍候」。

同线程重入语义不变：``local`` 是 RLock，外层 sync 占锁后内层 spot 直接放行。

**fd 与锁文件必须成对归还。** ``os.open(..., O_CREAT | O_EXCL)`` 一成功,磁盘上就
已经躺着一把锁文件了,所以从那一行往下的每一条出口都得同时 ``close`` 和
``unlink``(见 ``_release_lock_file``)。这里曾经只有 ``os.write`` 一行裸露在保护
之外:它抛 OSError(磁盘满、只读挂载、杀软拦截)时本进程漏 fd,更要命的是残留
锁文件的 holder 前缀不是别的进程的 pid、age 又不到 ``_LOCK_STALE_SEC``,于是把
**其它进程整整挡满 30 分钟** —— 一次写失败换来半小时的行情库全面瘫痪。
回归测试在 ``tests/market/test_write_lock_fd_leak.py``。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import logging
import os
from pathlib import Path
import threading
import time

from src.shared.observability import event, record_lock_wait
from src.shared.process_alive import pid_alive

logger = logging.getLogger(__name__)


def _env_seconds(name: str, default: float, *, minimum: float = 1.0) -> float:
    """读环境变量里的秒数；缺失/非法/过小一律回落，绝不把锁的 deadline 配成 0。"""
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是数字，改用默认 %s 秒", name, raw, default)
        return float(default)
    if value < minimum:
        logger.warning("环境变量 %s=%s 太小，抬到 %s 秒", name, value, minimum)
        return float(minimum)
    return value


#: 等锁上限（秒），``LOCI_MARKET_WRITE_WAIT_SEC`` 可覆盖。
#: 旧值 120s 比一次全市场同步还短，「排在正常同步后面」几乎必然超时。
_LOCK_WAIT_SEC = _env_seconds("LOCI_MARKET_WRITE_WAIT_SEC", 600.0, minimum=5.0)
#: 持锁多久才算「疑似卡死」（秒），``LOCI_MARKET_WRITE_STUCK_SEC`` 可覆盖。
#: 与等锁上限是两回事：等不到 ≠ 对方挂了，只有持锁超过这条线才配说卡死。
_LOCK_STUCK_SEC = _env_seconds("LOCI_MARKET_WRITE_STUCK_SEC", 30 * 60.0, minimum=60.0)
#: 锁文件多旧才算残留可接管。与卡死阈值同口径，免得仓里有两套「多久算挂了」；
#: 也必须大于等锁上限，否则等锁的人会顺手掀掉一把还活着的锁。
_LOCK_STALE_SEC = max(_LOCK_STUCK_SEC, _LOCK_WAIT_SEC + 60.0)
#: 记录的 pid 已经不在了，多旧才允许立刻接管（秒）。
#:
#: 有了 pid 探活，``_LOCK_STALE_SEC``（30 分钟）就只该管「探不出来」的情况。
#: 崩溃 / 被杀 / 关机没跑到 finally 的进程留下的锁文件，holder 前缀既不是本进程
#: 的 pid、age 又远不到 30 分钟——2026-08-26 现场：``.market.db.write.lock`` 里躺着
#: ``18848:sync:full``，那个进程 08-25 就没了，而每一个想写库的人都要先陪它站
#: 满半小时。一次崩溃换来半小时行情库全面瘫痪，代价全在等的人身上。
#:
#: 仍留一小段宽限而不是当场接管：写锁文件与 ``os.write`` 之间有个窗口，
#: pid 也可能被系统回收后复用。宽限期让「刚占上锁的人」不会被路过的进程掀掉。
_LOCK_DEAD_PID_GRACE_SEC = _env_seconds(
    "LOCI_MARKET_WRITE_DEAD_PID_GRACE_SEC", 30.0, minimum=5.0
)
_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_NESTING: dict[Path, int] = {}
#: 本进程当前持锁者 (label, 线程名, 起点 monotonic)；仅供诊断与报错文案。
_HOLDERS: dict[Path, tuple[str, str, float]] = {}


class MarketWriteBusy(RuntimeError):
    """行情写锁被占着 —— 另一个进程，或本进程另一条线程。"""


def _holder_pid_is_dead(holder: str, age_sec: float) -> bool:
    """锁文件里记着的进程是否已经不在了。

    ``holder`` 形如 ``"<pid>:<label>"``（见 ``market_write_lock`` 的 ``os.write``）。
    解析不出 pid（旧格式 / 写坏 / 空文件）一律返回 ``False``——回落到原来的
    ``_LOCK_STALE_SEC`` 时间窗，宁可多等也不掀一把可能还活着的锁。

    ``age_sec`` 的宽限是给「刚刚占上锁」留的窗口：``os.open`` 与 ``os.write``
    之间锁文件是空的，pid 也可能被系统回收后复用。
    """
    if age_sec < _LOCK_DEAD_PID_GRACE_SEC:
        return False
    pid_text = str(holder or "").split(":", 1)[0].strip()
    if not pid_text.isdigit():
        return False
    pid = int(pid_text)
    if pid <= 0:
        return False
    # pid_alive 对「探不出来」一律答活着，所以这里只有明确已死才会返回 True。
    return not pid_alive(pid)


def _lock_path(resolved: Path) -> Path:
    return resolved.with_name(f".{resolved.name}.write.lock")


def current_write_holder(db_path: Path | str) -> dict[str, object] | None:
    """本进程是否正持有该库的写锁；供闸门与运维诊断回答「谁在写、写了多久」。"""
    try:
        resolved = Path(db_path).resolve()
    except (OSError, ValueError):
        return None
    held = _HOLDERS.get(resolved)
    if held is None:
        return None
    label, thread_name, since = held
    return {
        "label": label,
        "thread": thread_name,
        "held_sec": max(0.0, time.monotonic() - since),
    }


def _local_holder_text(resolved: Path) -> str:
    """本进程持锁者的人话标签。时长由 ``_busy_text`` 统一报，这里不重复。"""
    held = _HOLDERS.get(resolved)
    if held is None:
        return "本进程另一条线程"
    label, thread_name, _since = held
    return f"本进程「{label}」（线程 {thread_name}）"


def _busy_text(*, holder: str, held_sec: float, label: str, waited_sec: float) -> str:
    """等不到写锁时的用户可见文案。

    「疑似卡死」是一句很重的话，只有持锁时长真的越过 ``_LOCK_STUCK_SEC`` 才说；
    否则对面只是在正常同步，文案就该是「请稍候」，而不是叫人去停任务。
    """
    minutes = int(max(0.0, held_sec) // 60)
    waited = int(max(0.0, waited_sec))
    if held_sec >= _LOCK_STUCK_SEC:
        return (
            f"行情库写锁被{holder}占着已 {minutes} 分钟，"
            f"超过 {int(_LOCK_STUCK_SEC // 60)} 分钟（疑似卡死）；"
            f"「{label}」等待 {waited} 秒仍未轮到，"
            "请到运维「执行历史」停掉它，或重启应用"
        )
    return (
        f"行情库正在同步（已 {minutes} 分钟），请稍候；"
        f"「{label}」等待 {waited} 秒未轮到（占用方：{holder}），稍后重试即可"
    )


def _release_lock_file(descriptor: int, lock_path: Path) -> None:
    """把 fd 和锁文件一起还回去 —— 两样都还,而且各自兜住自己的异常。

    顺序不能反:Windows 上文件还开着就 unlink 会直接失败。

    两步分开兜:close 失败不该拖着不删文件(残留锁挡人的代价远比漏一个 fd 大),
    unlink 失败也不该盖掉真正的业务异常 —— 这个函数是在 finally 里跑的。
    """
    try:
        os.close(descriptor)
    except OSError:
        logger.warning("关闭写锁 fd 失败（%s）;继续删锁文件", lock_path, exc_info=True)
    try:
        lock_path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        # 删不掉是真会挡人:后来者得等到 age > _LOCK_STALE_SEC 才敢接管。
        logger.error(
            "删除写锁文件失败,其它进程可能被挡到锁过期：%s", lock_path, exc_info=True
        )


@contextmanager
def market_write_lock(db_path: Path | str, *, label: str = "write") -> Iterator[None]:
    """跨进程互斥写 market.db（同进程可重入）。"""
    if str(db_path) == ":memory:":
        # SQLite 内存库不对应共享文件，创建旁路 lock 反而会把路径
        # ``.:memory:.write.lock`` 带入 Windows 非法文件名。
        yield
        return
    resolved = Path(db_path).resolve()
    with _PATH_LOCKS_GUARD:
        local = _PATH_LOCKS.setdefault(resolved, threading.RLock())
    lock_path = _lock_path(resolved)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    deadline = started + _LOCK_WAIT_SEC
    # 同线程重入由 RLock 立即放行；跨线程最多等 _LOCK_WAIT_SEC 秒后明确失败，
    # 绝不无限期挂起——挂起会连带钉死调用方在 market_gate 里的槽位。
    if not local.acquire(timeout=_LOCK_WAIT_SEC):
        wait_ms = max(0, int((time.monotonic() - started) * 1000))
        record_lock_wait(
            component="write_lock",
            kind="write",
            wait_ms=wait_ms,
            outcome="busy",
            reason="local_deadline",
        )
        event(
            logger,
            logging.WARNING,
            "market_write_lock_busy_local",
            fields={"wait_ms": wait_ms, "label": str(label)[:64]},
        )
        held = _HOLDERS.get(resolved)
        held_sec = max(0.0, time.monotonic() - held[2]) if held else 0.0
        raise MarketWriteBusy(
            _busy_text(
                holder=_local_holder_text(resolved),
                held_sec=held_sec,
                label=str(label),
                waited_sec=time.monotonic() - started,
            )
        )
    try:
        # 同进程重入：外层 sync 已占锁时，内层 spot 直接放行。
        if _NESTING.get(resolved, 0) > 0:
            _NESTING[resolved] = _NESTING[resolved] + 1
            record_lock_wait(
                component="write_lock",
                kind="write",
                wait_ms=0,
                outcome="ok",
                reason="reentrant",
            )
            try:
                yield
            finally:
                _NESTING[resolved] = max(0, _NESTING[resolved] - 1)
            return

        # 这个 while 只干一件事:把锁文件抢到手。写 holder / 记账 / yield 全部挪到了
        # 循环外面 —— os.open 成功的那一刻磁盘上就已经躺着一把锁文件,之后每一步都
        # 得共用同一条归还路径,不能再有哪一行裸露在保护之外。
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                # age/holder 在 stat/read 失败时也要有值：报错文案要靠它们判「卡死」。
                age = 0.0
                holder = "?"
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    holder = lock_path.read_text(encoding="ascii", errors="ignore").strip()
                    if holder.startswith(f"{os.getpid()}:"):
                        # 残留本进程锁（异常退出未清）→ 接管
                        lock_path.unlink(missing_ok=True)
                        continue
                    if _holder_pid_is_dead(holder, age):
                        # 写锁的主人已经不在了。等满 _LOCK_STALE_SEC 只是陪一个死进程
                        # 站岗，越早接管越好；WARNING 是为了让「谁掀了锁」留在日志里。
                        logger.warning(
                            "接管残留行情写锁：持有者 %s 的进程已退出（锁文件 %.0f 秒前写下），"
                            "本次由「%s」接手",
                            holder,
                            age,
                            label,
                        )
                        event(
                            logger,
                            logging.WARNING,
                            "market_write_lock_dead_holder_evicted",
                            fields={"holder": holder[:64], "age_sec": int(age)},
                        )
                        lock_path.unlink(missing_ok=True)
                        continue
                    if age > _LOCK_STALE_SEC:
                        lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                except OSError:
                    holder = "?"
                if time.monotonic() >= deadline:
                    wait_ms = max(0, int((time.monotonic() - started) * 1000))
                    record_lock_wait(
                        component="write_lock",
                        kind="write",
                        wait_ms=wait_ms,
                        outcome="busy",
                        reason="deadline",
                    )
                    event(
                        logger,
                        logging.WARNING,
                        "market_write_lock_busy",
                        fields={"wait_ms": wait_ms, "label": str(label)[:64]},
                    )
                    raise MarketWriteBusy(
                        _busy_text(
                            holder=f"其它进程（{holder or '未知'}）",
                            held_sec=age,
                            label=str(label),
                            waited_sec=time.monotonic() - started,
                        )
                    )
                time.sleep(0.1)

        # ---- 从这里起 fd 与锁文件都归我们;每一条出口都必须把两样一起还回去 ----
        #
        # 这段以前只有 ``os.write`` 一行裸露在保护之外。它抛 OSError(磁盘满 ENOSPC、
        # 只读挂载 EROFS、杀软拦截)时,异常会越过整个外层 try,而那层 finally 里
        # **只有** ``local.release()``。于是双重泄漏:
        #
        # - ``descriptor`` 从不 close,本进程一次抽风漏一个 fd,攒够就 EMFILE;
        # - ``lock_path`` 从不 unlink,而残留锁的 holder 前缀不是别的进程的 pid、
        #   age 又远不到 ``_LOCK_STALE_SEC``,于是**别的进程被硬挡满 30 分钟** ——
        #   一次写失败换来半小时的行情库全面瘫痪,这才是贵的那一半。
        #
        # 保护范围是整段而不只是 os.write:中间的 record_lock_wait / logger 一样会抛,
        # 泄漏的形状一模一样,单给 os.write 打补丁只是把同一个洞挪个位置。
        acquired = False
        try:
            payload = f"{os.getpid()}:{label}".encode("ascii", errors="ignore")
            os.write(descriptor, payload)
            wait_ms = max(0, int((time.monotonic() - started) * 1000))
            record_lock_wait(
                component="write_lock",
                kind="write",
                wait_ms=wait_ms,
                outcome="ok",
            )
            _NESTING[resolved] = 1
            _HOLDERS[resolved] = (
                str(label),
                threading.current_thread().name,
                time.monotonic(),
            )
            acquired = True
            logger.info("行情写锁占有：%s pid=%s", label, os.getpid())
            yield
        finally:
            _NESTING[resolved] = 0
            _HOLDERS.pop(resolved, None)
            _release_lock_file(descriptor, lock_path)
            if acquired:
                # 没真正宣告占有过就别报「释放」,否则日志里凭空多一对进出。
                logger.info("行情写锁释放：%s", label)
    finally:
        local.release()
