"""ops.db 的实时信号两张表：规则阈值配置 + 信号日志（含保留策略）。

**为什么信号能落 ops.db，而实时链号称「绝不写库」**：
``src/market/application/realtime_signals.py`` 的模块 docstring 第 1 条禁的是
**往行情库 / 研究库写行情与研究产物**（不调 ``apply_today_spot``、不走
``board?persist=true``、不落 research run card）——那条铁律保护的是「行情事实
只有一条写入路径」。而「我今天收到过哪些提醒」「我把涨速阈值调到了几」是**运维
事实**，本来就归 ops.db。这两张表整表删掉，行情数据一个字节都不会错。

两张表的分工：

- ``signal_rule_config`` —— **只存被改过的那几条**。六条规则的默认阈值写死在
  ``realtime_signals.RULES`` 里，库里没有行 = 全部用默认。反过来做（首启把默认
  值灌进库）会把默认值钉死在旧版本上：以后改代码里的默认值、给规则加一个新
  参数，老用户全都吃不到。
- ``signal_journal`` —— 信号日志。``id`` 是**确定性去重键**而非随机 uuid，见
  ``signal_dedup_id``。

保留策略两道闸门（用户需求 5）在**写入时顺带执行**，不另起定时任务：这张表一天
最多几十行，清理成本比调度一个 job 的成本低一个数量级，而且「写进来的那一刻就
已经满足保留策略」比「等 02:30 的清理任务」更好解释。
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import math
import sqlite3
from typing import Any, Iterable, Mapping

from src.ops.infrastructure.store_helpers import dumps, loads

#: 信号日志的时间闸：早于 N 天的行在下一次写入时被物理删除。
#: 出处：**用户需求 5**（「只保留 7 天」）。大屏历史面板只回看一周，再久的盘中
#: 未定稿信号既没人看，也早被当天的收盘事实推翻了。
SIGNAL_RETENTION_DAYS = 7

#: 信号日志的条数闸：**每租户**只保留最新 N 条，超出的物理删除。
#: 出处：**用户需求 5**（「最多 80 条」）。与 ``GET /api/market/signals/recent``
#: 的默认 ``limit=80`` 是同一个数——服务端永远不会有第 81 条可返回。
SIGNAL_JOURNAL_MAX_ROWS = 80

#: 日志时间戳格式。**必须与 ``realtime_signals._signal_row`` 的 ``at`` 一致**：
#: 两道保留闸门与 ``ORDER BY`` 都靠字符串比较，混进 ISO8601（带 ``T`` 与时区
#: 偏移）会让 ``'2026-08-27T10:00' < '2026-08-27 10:00'`` 这种荒谬结论成立，
#: 于是刚写进去的新行被当成过期行删掉。定长同格式是这里唯一安全的做法。
JOURNAL_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

#: 日志行的列顺序（写入与读取共用一份，避免两处漂移）。
_JOURNAL_COLUMNS = (
    "id",
    "tenant",
    "code",
    "name",
    "rule_id",
    "rule_label",
    "title",
    "detail",
    "direction",
    "strength",
    "price",
    "pct",
    "triggered_at",
    "trade_day",
)

_INSERT_JOURNAL_SQL = (
    "INSERT INTO signal_journal("
    + ", ".join(_JOURNAL_COLUMNS)
    + ") VALUES ("
    + ", ".join(f":{name}" for name in _JOURNAL_COLUMNS)
    + ") ON CONFLICT(id) DO NOTHING"
)

_SELECT_JOURNAL_SQL = (
    "SELECT "
    + ", ".join(_JOURNAL_COLUMNS)
    + " FROM signal_journal WHERE tenant = ? AND triggered_at >= ?"
    + " ORDER BY triggered_at DESC, id DESC LIMIT ?"
)


def _text(value: Any, default: str = "") -> str:
    return default if value is None else str(value)


def _real(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def signal_dedup_id(
    *,
    tenant: str,
    code: str,
    rule_id: str,
    trade_day: str,
    triggered_at: str,
    repeatable: bool,
) -> str:
    """一条信号的**确定性**主键。

    引擎自己有内存去抖（同租户/代码/规则/交易日只报一次），但内存表**一重启就
    没了**：进程重启后同一条金叉会被重新报一次，直接 INSERT 就多一行。把去重语义
    也钉在主键上，配合 ``ON CONFLICT(id) DO NOTHING``，重启、多进程、重放同一帧
    快照都只会留下一行。

    可重复规则（涨速、临近涨停）**把 ``triggered_at`` 也算进 key**：它们本来就允许
    一天多条，用时刻区分才是对的语义——否则一天只剩第一条，「9:35 涨速 3%、
    14:55 又涨速 3%」在历史里会退化成一条。
    """
    parts = [tenant, code, rule_id, trade_day]
    if repeatable:
        parts.append(triggered_at)
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"SIG-{digest[:20]}"


def _retention_cutoff(now: datetime) -> str:
    """时间闸的边界值。与 ``triggered_at`` 同格式，直接字符串比较。"""
    return (now - timedelta(days=SIGNAL_RETENTION_DAYS)).strftime(JOURNAL_TIME_FORMAT)


def _journal_row(
    signal: Mapping[str, Any], *, tenant: str, moment: datetime
) -> dict[str, Any] | None:
    """一条引擎信号 → 一行日志。字段缺失一律给默认值，脏行直接丢。"""
    code = _text(signal.get("code")).strip()
    rule_id = _text(signal.get("rule_id") or signal.get("rule")).strip()
    if not code or not rule_id:
        # 没有代码或没有规则的「信号」不是信号，是上游 bug；宁可丢也不落脏行。
        return None
    triggered_at = _text(signal.get("at")).strip() or moment.strftime(JOURNAL_TIME_FORMAT)
    trade_day = _text(signal.get("trade_day") or signal.get("trade_date")).strip()
    name = _text(signal.get("name"))
    label = _text(signal.get("rule_label"))
    row: dict[str, Any] = dict(
        tenant=str(tenant),
        code=code,
        name=name,
        rule_id=rule_id,
        rule_label=label,
        title=_text(signal.get("title")) or f"{name}({code}) {label}".strip(),
        detail=_text(signal.get("detail")),
        direction=_text(signal.get("direction")),
        strength=_real(signal.get("strength")),
        price=_real(signal.get("price")),
        pct=_real(signal.get("pct")),
        triggered_at=triggered_at,
        trade_day=trade_day or triggered_at[:10],
    )
    row["id"] = signal_dedup_id(
        tenant=str(tenant),
        code=code,
        rule_id=rule_id,
        trade_day=str(row["trade_day"]),
        triggered_at=triggered_at,
        repeatable=bool(signal.get("repeatable")),
    )
    return row


def _prune(cursor: sqlite3.Cursor, *, tenant: str, moment: datetime) -> dict[str, Any]:
    """两道闸门（用户需求 5）：① 早于 7 天的删 ② 每租户只留最新 80 条。

    两道都**按租户**收窄：A 写一批不能把 B 的历史挤掉。先按时间删再按条数删，省掉
    对已过期行的排序。
    """
    cursor.execute(
        "DELETE FROM signal_journal WHERE tenant = ? AND triggered_at < ?",
        (tenant, _retention_cutoff(moment)),
    )
    expired = int(cursor.rowcount or 0)
    # id 是稳定主键；triggered_at 打平时再按 id 定序，保证「留哪 80 条」可复现。
    cursor.execute(
        "DELETE FROM signal_journal WHERE tenant = ? AND id NOT IN ("
        " SELECT id FROM signal_journal WHERE tenant = ?"
        " ORDER BY triggered_at DESC, id DESC LIMIT ?)",
        (tenant, tenant, SIGNAL_JOURNAL_MAX_ROWS),
    )
    overflow = int(cursor.rowcount or 0)
    return dict(
        expired=expired,
        overflow=overflow,
        retention_days=SIGNAL_RETENTION_DAYS,
        max_rows=SIGNAL_JOURNAL_MAX_ROWS,
    )


def _rule_config_row(row: sqlite3.Row) -> dict[str, Any]:
    raw = loads(row["params"], dict())
    return dict(
        rule_id=str(row["rule_id"]),
        enabled=bool(row["enabled"]),
        params=raw if isinstance(raw, dict) else dict(),
        updated_at=str(row["updated_at"] or ""),
    )


def _journal_out(row: sqlite3.Row) -> dict[str, Any]:
    """对外的一行历史。``tenant`` 不出库外——调用方本来就只能查自己那份。"""
    return dict(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        rule_id=str(row["rule_id"]),
        rule_label=str(row["rule_label"]),
        title=str(row["title"]),
        detail=str(row["detail"]),
        direction=str(row["direction"]),
        strength=float(row["strength"]),
        price=float(row["price"]),
        pct=float(row["pct"]),
        triggered_at=str(row["triggered_at"]),
        trade_day=str(row["trade_day"]),
    )


class OpsSignalsMixin:
    """实时信号规则配置与信号日志的读写。依赖宿主提供 ``conn`` / ``_transaction``。"""

    conn: Any

    # --------------------------------------------------------------- 规则配置

    def list_signal_rule_config(self, *, tenant: str) -> list[dict[str, Any]]:
        """本租户**被改过的**规则行。没被改过的规则不在结果里（也不该在）。"""
        rows = self.conn.execute(
            "SELECT rule_id, enabled, params, updated_at FROM signal_rule_config"
            " WHERE tenant = ? ORDER BY rule_id",
            (str(tenant),),
        ).fetchall()
        return [_rule_config_row(row) for row in rows]

    def get_signal_rule_config(self, rule_id: str, *, tenant: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT rule_id, enabled, params, updated_at FROM signal_rule_config"
            " WHERE tenant = ? AND rule_id = ?",
            (str(tenant), str(rule_id)),
        ).fetchone()
        return _rule_config_row(row) if row else None

    def upsert_signal_rule_config(
        self,
        rule_id: str,
        *,
        tenant: str,
        enabled: bool,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """写一条覆盖。``params`` 只放**与默认值不同**的键，由调用方负责裁剪。"""
        payload = {str(key): value for key, value in dict(params or dict()).items()}
        now = self._now()  # type: ignore[attr-defined]
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "INSERT INTO signal_rule_config(tenant, rule_id, enabled, params, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(tenant, rule_id) DO UPDATE SET"
                " enabled=excluded.enabled,"
                " params=excluded.params,"
                " updated_at=excluded.updated_at",
                (str(tenant), str(rule_id), 1 if enabled else 0, dumps(payload), now),
            )
        return self.get_signal_rule_config(rule_id, tenant=tenant) or dict()

    def delete_signal_rule_config(self, rule_id: str, *, tenant: str) -> bool:
        """删掉覆盖 = 恢复代码里的默认值。"""
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                "DELETE FROM signal_rule_config WHERE tenant = ? AND rule_id = ?",
                (str(tenant), str(rule_id)),
            )
            return cursor.rowcount > 0

    # --------------------------------------------------------------- 信号日志

    def append_signal_journal(
        self,
        signals: Iterable[Mapping[str, Any]],
        *,
        tenant: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """写入一批信号并**顺带**执行保留策略。返回写入 / 去重 / 删除的条数。

        整个批次一个事务：要么这一帧的信号全进去、保留闸门也跑完，要么什么都没
        发生。半写半清的中间态没人能解释。
        """
        moment = now or datetime.now()
        candidates = [_journal_row(item, tenant=tenant, moment=moment) for item in signals]
        rows = [row for row in candidates if row is not None]
        inserted = 0
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            for row in rows:
                cursor.execute(_INSERT_JOURNAL_SQL, row)
                inserted += int(cursor.rowcount or 0)
            pruned = _prune(cursor, tenant=str(tenant), moment=moment)
        out = dict(received=len(rows), inserted=inserted, deduped=len(rows) - inserted)
        out.update(pruned)
        return out

    def prune_signal_journal(self, *, tenant: str, now: datetime | None = None) -> dict[str, Any]:
        """单独跑一遍保留策略。正常路径不需要——``append_signal_journal`` 自带。"""
        moment = now or datetime.now()
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            return _prune(cursor, tenant=str(tenant), moment=moment)

    def list_signal_journal(
        self,
        *,
        tenant: str,
        limit: int = SIGNAL_JOURNAL_MAX_ROWS,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """最近的信号，倒序。**读这一侧也压 7 天 + 80 条**。

        写入时已经清过了，为什么读还要再压一遍：清理只在**有新信号写入**时发生。
        收盘后没有任何 tick，第 8 天打开页面时库里那批「7 天零 3 小时前」的行还在。
        读侧不压，用户就会看到一条本该消失的历史——两处用同一套常量，任何一处
        失灵都不会漏出去。
        """
        size = max(1, min(int(limit or SIGNAL_JOURNAL_MAX_ROWS), SIGNAL_JOURNAL_MAX_ROWS))
        cutoff = _retention_cutoff(now or datetime.now())
        rows = self.conn.execute(_SELECT_JOURNAL_SQL, (str(tenant), cutoff, size)).fetchall()
        return [_journal_out(row) for row in rows]


__all__ = [
    "JOURNAL_TIME_FORMAT",
    "OpsSignalsMixin",
    "SIGNAL_JOURNAL_MAX_ROWS",
    "SIGNAL_RETENTION_DAYS",
    "signal_dedup_id",
]
