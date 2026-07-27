"""潜龙记忆宫殿的本地事件账本。

这个模块只记录事实、预案与复盘结果，不生成自动交易指令。核心原则是：
任何当前仓位都能由 ``position_events`` 回放得到；任何结论都带有日期、来源和
可选的证据字段，便于日后追溯与量化复盘。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Sequence
from uuid import uuid4


SCHEMA_VERSION = 4


class PalaceError(ValueError):
    """用户输入或账本状态不满足约束时抛出。"""


@dataclass(frozen=True, slots=True)
class Position:
    code: str
    name: str
    shares: int
    cost: float
    updated_on: str
    note: str

    @property
    def cost_value(self) -> float:
        return round(self.shares * self.cost, 2)


def normalize_code(value: str) -> str:
    """规范为六位 A 股代码，避免不同写法产生两份账本。"""
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) > 6:
        digits = digits[-6:]
    if len(digits) != 6:
        raise PalaceError("股票代码必须为 6 位数字")
    return digits


def normalize_date(value: str | None) -> str:
    """校验日期并统一输出 ISO 日期；未传时使用当天。"""
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise PalaceError("日期必须为 YYYY-MM-DD") from exc


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


# 进程内已完成 schema 初始化的库路径，避免每个请求都写 meta 表抢锁。
_SCHEMA_READY: set[str] = set()


class PalaceStore:
    """SQLite 账本：当前快照为投影，事件表才是可审计的事实来源。"""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # timeout/busy_timeout：并发读写（多 API 同时打同一库）时等锁而不是立刻失败。
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        journal = self.conn.execute("PRAGMA journal_mode").fetchone()
        if journal is None or str(journal[0]).lower() != "wal":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> PalaceStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN")
            yield cursor
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _schema_is_current(self) -> bool:
        """meta 表已存在且版本一致时无需再跑 DDL。"""
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        return bool(row) and str(row["value"]) == str(SCHEMA_VERSION)

    def init_schema(self) -> None:
        resolved = str(self.db_path.resolve())
        if resolved in _SCHEMA_READY or self._schema_is_current():
            _SCHEMA_READY.add(resolved)
            return

        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS stocks (
                code TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS holdings (
                code TEXT PRIMARY KEY REFERENCES stocks(code),
                name TEXT NOT NULL,
                shares INTEGER NOT NULL CHECK (shares > 0),
                cost REAL NOT NULL CHECK (cost >= 0),
                updated_on TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS position_events (
                id TEXT PRIMARY KEY,
                occurred_on TEXT NOT NULL,
                code TEXT NOT NULL REFERENCES stocks(code),
                name TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action IN ('OPENING', 'BUY', 'SELL')),
                shares INTEGER NOT NULL CHECK (shares > 0),
                price REAL NOT NULL CHECK (price >= 0),
                shares_before INTEGER NOT NULL,
                shares_after INTEGER NOT NULL,
                cost_before REAL NOT NULL,
                cost_after REAL NOT NULL,
                realized_pnl REAL NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                correlation_id TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_position_events_code_date
                ON position_events(code, occurred_on, created_at);

            CREATE TABLE IF NOT EXISTS account_events (
                id TEXT PRIMARY KEY,
                occurred_on TEXT NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('CASHFLOW', 'REALIZED_PNL_IMPORT')),
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS account_snapshots (
                id TEXT PRIMARY KEY,
                occurred_on TEXT NOT NULL,
                total_assets REAL NOT NULL CHECK (total_assets >= 0),
                cash REAL,
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_account_snapshots_date
                ON account_snapshots(occurred_on, created_at);

            CREATE TABLE IF NOT EXISTS candidate_reviews (
                id TEXT PRIMARY KEY,
                occurred_on TEXT NOT NULL,
                pool_id TEXT NOT NULL,
                code TEXT NOT NULL REFERENCES stocks(code),
                name TEXT NOT NULL,
                score REAL,
                decision TEXT NOT NULL,
                timing TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL,
                rule_version TEXT NOT NULL DEFAULT 'qianlong-v1',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                tier TEXT NOT NULL DEFAULT 'core',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_candidates_code_date
                ON candidate_reviews(code, occurred_on, created_at);

            CREATE TABLE IF NOT EXISTS plans (
                id TEXT PRIMARY KEY,
                occurred_on TEXT NOT NULL,
                code TEXT NOT NULL REFERENCES stocks(code),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                scenario TEXT NOT NULL,
                entry_zone TEXT NOT NULL DEFAULT '',
                stop_price REAL,
                target_price REAL,
                layers REAL,
                invalidation TEXT NOT NULL DEFAULT '',
                rule_version TEXT NOT NULL DEFAULT 'qianlong-v1',
                source TEXT NOT NULL DEFAULT 'manual',
                supersedes_id TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plans_code_date ON plans(code, occurred_on, created_at);

            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                reviewed_on TEXT NOT NULL,
                entity_type TEXT NOT NULL CHECK (entity_type IN ('plan', 'candidate', 'trade')),
                entity_id TEXT NOT NULL,
                strategy_tag TEXT NOT NULL DEFAULT 'qianlong',
                outcome TEXT NOT NULL,
                return_pct REAL,
                max_favorable_pct REAL,
                max_adverse_pct REAL,
                lesson TEXT NOT NULL DEFAULT '',
                next_rule TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reviews_entity ON reviews(entity_type, entity_id, reviewed_on);

            -- AI 判定记录：独立于量化选股，记录 AI 筛选结论。
            -- 不记录的话无法事后算 AI 的 alpha（AI 否决的那些天量化 top3 赚了多少）。
            CREATE TABLE IF NOT EXISTS ai_judgments (
                id           TEXT PRIMARY KEY,
                occurred_on  TEXT NOT NULL,
                strategy_tag TEXT NOT NULL,
                decision     TEXT NOT NULL CHECK (decision IN ('buy', 'hold_cash', 'partial')),
                top_codes    TEXT NOT NULL DEFAULT '[]',
                reason       TEXT NOT NULL DEFAULT '',
                provider     TEXT NOT NULL DEFAULT '',
                model        TEXT NOT NULL DEFAULT '',
                token_used   INTEGER NOT NULL DEFAULT 0,
                source       TEXT NOT NULL DEFAULT 'ai',
                created_at   TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_judgments_strategy ON ai_judgments(strategy_tag, occurred_on DESC);

            -- 持仓周期跟踪：记录每个量化候选的 T+N 跟踪窗口。
            -- status: active=追踪中 / closed=已关闭 / expired=到期
            -- 关键用途：区分「还在持仓周期内」vs「周期已结束可以算收益了」，
            --           避免拿一只还在追踪中的票计入当日复盘统计。
            CREATE TABLE IF NOT EXISTS position_tracking (
                id              TEXT PRIMARY KEY,
                strategy_tag    TEXT NOT NULL,
                pool_id         TEXT NOT NULL,
                code            TEXT NOT NULL,
                name            TEXT NOT NULL DEFAULT '',
                tier            TEXT NOT NULL DEFAULT 'core',
                signal_date     TEXT NOT NULL,
                entry_date      TEXT NOT NULL,
                hold_days       INTEGER NOT NULL DEFAULT 3,
                exit_by_date    TEXT NOT NULL,
                entry_price     REAL,
                exit_price      REAL,
                max_price       REAL,
                min_price       REAL,
                actual_return   REAL,
                status          TEXT NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active','closed','expired')),
                closed_reason   TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_pt_strategy ON position_tracking(strategy_tag, signal_date DESC);
            CREATE INDEX IF NOT EXISTS idx_pt_status   ON position_tracking(status, exit_by_date);
            """
        )
        self._dedupe_candidate_reviews()
        self._run_migrations()
        self._set_meta("schema_version", str(SCHEMA_VERSION))
        self.conn.commit()
        _SCHEMA_READY.add(str(self.db_path.resolve()))

    def _run_migrations(self) -> None:
        """增量列迁移：对已有数据库补加新列。

        CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做，
        所以新增的列必须用 ALTER TABLE ADD COLUMN 单独迁移。
        SQLite 的 ALTER TABLE 在列已存在时会报错，用 try/except 跳过。
        """
        migrations = [
            # v4: candidate_reviews 增加 tier 列
            "ALTER TABLE candidate_reviews ADD COLUMN tier TEXT NOT NULL DEFAULT 'core'",
            # v4: ai_judgments 表（若旧库没有 executescript 建出来，补建）
            """CREATE TABLE IF NOT EXISTS ai_judgments (
                id           TEXT PRIMARY KEY,
                occurred_on  TEXT NOT NULL,
                strategy_tag TEXT NOT NULL,
                decision     TEXT NOT NULL,
                top_codes    TEXT NOT NULL DEFAULT '[]',
                reason       TEXT NOT NULL DEFAULT '',
                provider     TEXT NOT NULL DEFAULT '',
                model        TEXT NOT NULL DEFAULT '',
                token_used   INTEGER NOT NULL DEFAULT 0,
                source       TEXT NOT NULL DEFAULT 'ai',
                created_at   TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_ai_judgments_strategy ON ai_judgments(strategy_tag, occurred_on DESC)",
            # v4: position_tracking 表补建
            """CREATE TABLE IF NOT EXISTS position_tracking (
                id              TEXT PRIMARY KEY,
                strategy_tag    TEXT NOT NULL,
                pool_id         TEXT NOT NULL,
                code            TEXT NOT NULL,
                name            TEXT NOT NULL DEFAULT '',
                tier            TEXT NOT NULL DEFAULT 'core',
                signal_date     TEXT NOT NULL,
                entry_date      TEXT NOT NULL,
                hold_days       INTEGER NOT NULL DEFAULT 3,
                exit_by_date    TEXT NOT NULL,
                entry_price     REAL,
                exit_price      REAL,
                max_price       REAL,
                min_price       REAL,
                actual_return   REAL,
                status          TEXT NOT NULL DEFAULT 'active',
                closed_reason   TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_pt_strategy ON position_tracking(strategy_tag, signal_date DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pt_status ON position_tracking(status, exit_by_date)",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except Exception:
                pass  # 列已存在或表已存在，跳过

    def _dedupe_candidate_reviews(self) -> None:
        """清理历史重复：同日同池同标的只留最新一条。"""
        self.conn.execute(
            """
            DELETE FROM candidate_reviews
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY occurred_on, pool_id, code
                               ORDER BY created_at DESC, id DESC
                           ) AS rn
                    FROM candidate_reviews
                ) ranked
                WHERE rn > 1
            )
            """
        )
        # 去重后再确保唯一索引存在（旧库可能缺这个索引）
        self.conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_day_pool_code
            ON candidate_reviews(occurred_on, pool_id, code)
            """
        )

    def _set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO meta(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, _now()),
        )

    def _upsert_stock(self, cursor: sqlite3.Cursor, code: str, name: str, tags: Sequence[str] = (), note: str = "") -> None:
        current = cursor.execute("SELECT name, tags_json, note FROM stocks WHERE code = ?", (code,)).fetchone()
        now = _now()
        if current is None:
            cursor.execute(
                "INSERT INTO stocks(code, name, tags_json, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (code, name or code, _dumps(list(tags)), note, now, now),
            )
            return
        effective_name = name or str(current["name"])
        effective_tags = list(tags) if tags else json.loads(str(current["tags_json"]))
        effective_note = note or str(current["note"])
        cursor.execute(
            "UPDATE stocks SET name = ?, tags_json = ?, note = ?, updated_at = ? WHERE code = ?",
            (effective_name, _dumps(effective_tags), effective_note, now, code),
        )

    def register_stock(self, code: str, name: str, tags: Sequence[str] = (), note: str = "") -> None:
        code = normalize_code(code)
        clean_tags = tuple(tag.strip() for tag in tags if tag.strip())
        if not name.strip():
            raise PalaceError("股票名称不能为空")
        with self._transaction() as cursor:
            self._upsert_stock(cursor, code, name.strip(), clean_tags, note.strip())

    def _position_row(self, cursor: sqlite3.Cursor, code: str) -> sqlite3.Row | None:
        return cursor.execute("SELECT code, name, shares, cost, updated_on, note FROM holdings WHERE code = ?", (code,)).fetchone()

    def record_trade(
        self,
        *,
        action: str,
        code: str,
        shares: int,
        price: float,
        occurred_on: str | None = None,
        name: str = "",
        reason: str = "",
        source: str = "manual",
        correlation_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """记录开仓、买入或卖出，并按潜龙规则重算部分卖出的余票成本。"""
        code = normalize_code(code)
        action = action.upper()
        if action not in {"OPENING", "BUY", "SELL"}:
            raise PalaceError("动作必须为 OPENING、BUY 或 SELL")
        if shares <= 0:
            raise PalaceError("股数必须大于 0")
        if price < 0:
            raise PalaceError("成交价不能为负数")
        occurred_on = normalize_date(occurred_on)
        event_id = f"TX-{uuid4().hex[:12].upper()}"

        with self._transaction() as cursor:
            current = self._position_row(cursor, code)
            shares_before = int(current["shares"]) if current else 0
            cost_before = float(current["cost"]) if current else 0.0
            current_name = str(current["name"]) if current else ""
            effective_name = name.strip() or current_name or code
            self._upsert_stock(cursor, code, effective_name)

            realized_pnl = 0.0
            if action in {"OPENING", "BUY"}:
                if action == "OPENING" and current is not None:
                    raise PalaceError(f"{code} 已有仓位，不能重复导入开仓快照")
                shares_after = shares_before + shares
                cost_after = ((cost_before * shares_before) + (price * shares)) / shares_after
            else:
                if current is None or shares_before <= 0:
                    raise PalaceError(f"{code} 没有可卖出的仓位")
                if shares > shares_before:
                    raise PalaceError(f"卖出 {shares} 股超过当前持仓 {shares_before} 股")
                shares_after = shares_before - shares
                realized_pnl = (price - cost_before) * shares
                # 用户长期规则：部分卖出后，将已实现盈亏摊入余票成本。
                cost_after = ((cost_before * shares_before) - (price * shares)) / shares_after if shares_after else 0.0

            cost_after = round(cost_after, 6)
            realized_pnl = round(realized_pnl, 2)
            cursor.execute(
                """
                INSERT INTO position_events(
                    id, occurred_on, code, name, action, shares, price, shares_before, shares_after,
                    cost_before, cost_after, realized_pnl, reason, source, correlation_id, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id, occurred_on, code, effective_name, action, shares, price, shares_before, shares_after,
                    cost_before, cost_after, realized_pnl, reason.strip(), source.strip() or "manual",
                    correlation_id.strip(), _dumps(metadata), _now(),
                ),
            )
            if shares_after:
                cursor.execute(
                    """
                    INSERT INTO holdings(code, name, shares, cost, updated_on, note) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET name = excluded.name, shares = excluded.shares,
                    cost = excluded.cost, updated_on = excluded.updated_on, note = excluded.note
                    """,
                    (code, effective_name, shares_after, cost_after, occurred_on, reason.strip()),
                )
            else:
                cursor.execute("DELETE FROM holdings WHERE code = ?", (code,))

        return {
            "id": event_id,
            "code": code,
            "name": effective_name,
            "action": action,
            "date": occurred_on,
            "shares_before": shares_before,
            "shares_after": shares_after,
            "cost_before": round(cost_before, 6),
            "cost_after": cost_after,
            "realized_pnl": realized_pnl,
        }

    def record_account_event(
        self,
        *,
        kind: str,
        amount: float,
        occurred_on: str | None = None,
        note: str = "",
        source: str = "manual",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        kind = kind.upper()
        if kind not in {"CASHFLOW", "REALIZED_PNL_IMPORT"}:
            raise PalaceError("账户事件类型必须为 CASHFLOW 或 REALIZED_PNL_IMPORT")
        event_id = f"AC-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO account_events(id, occurred_on, kind, amount, note, source, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, normalize_date(occurred_on), kind, amount, note.strip(), source.strip() or "manual", _dumps(metadata), _now()),
            )
        return event_id

    def record_snapshot(
        self,
        *,
        total_assets: float,
        occurred_on: str | None = None,
        cash: float | None = None,
        note: str = "",
        source: str = "manual",
    ) -> str:
        if total_assets < 0:
            raise PalaceError("总资产不能为负数")
        if cash is not None and cash < 0:
            raise PalaceError("现金不能为负数")
        snapshot_id = f"AS-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO account_snapshots(id, occurred_on, total_assets, cash, note, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, normalize_date(occurred_on), total_assets, cash, note.strip(), source.strip() or "manual", _now()),
            )
        return snapshot_id

    def record_candidate(
        self,
        *,
        code: str,
        name: str,
        decision: str,
        reason: str,
        occurred_on: str | None = None,
        pool_id: str = "",
        score: float | None = None,
        timing: str = "",
        rule_version: str = "qianlong-v1",
        evidence: dict[str, Any] | None = None,
        tier: str = "core",
        source: str = "manual",
    ) -> str:
        """写入候选裁决。同日同池同标的只占一席：重复提交幂等，改判则覆盖。"""
        code = normalize_code(code)
        occurred_on = normalize_date(occurred_on)
        if not decision.strip() or not reason.strip():
            raise PalaceError("候选记录必须有裁决和理由")
        effective_pool = pool_id.strip() or f"POOL-{occurred_on}"
        name_value = name.strip() or code
        decision_value = decision.strip()
        reason_value = reason.strip()
        timing_value = timing.strip()
        rule_value = rule_version.strip() or "qianlong-v1"
        source_value = source.strip() or "manual"
        tier_value = tier.strip() or "core"
        evidence_json = _dumps(evidence)
        with self._transaction() as cursor:
            self._upsert_stock(cursor, code, name_value)
            existing = cursor.execute(
                """
                SELECT id, name, score, decision, timing, reason, rule_version, evidence_json, tier, source
                FROM candidate_reviews
                WHERE occurred_on = ? AND pool_id = ? AND code = ?
                """,
                (occurred_on, effective_pool, code),
            ).fetchone()
            if existing:
                same = (
                    str(existing["name"]) == name_value
                    and (
                        (existing["score"] is None and score is None)
                        or (
                            existing["score"] is not None
                            and score is not None
                            and float(existing["score"]) == float(score)
                        )
                    )
                    and str(existing["decision"]) == decision_value
                    and str(existing["timing"]) == timing_value
                    and str(existing["reason"]) == reason_value
                    and str(existing["rule_version"]) == rule_value
                    and str(existing["evidence_json"]) == evidence_json
                    and str(existing["tier"]) == tier_value
                    and str(existing["source"]) == source_value
                )
                if same:
                    return str(existing["id"])
                cursor.execute(
                    """
                    UPDATE candidate_reviews
                    SET name = ?, score = ?, decision = ?, timing = ?, reason = ?,
                        rule_version = ?, evidence_json = ?, tier = ?, source = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
                        name_value,
                        score,
                        decision_value,
                        timing_value,
                        reason_value,
                        rule_value,
                        evidence_json,
                        tier_value,
                        source_value,
                        _now(),
                        str(existing["id"]),
                    ),
                )
                return str(existing["id"])

            candidate_id = f"CA-{uuid4().hex[:12].upper()}"
            cursor.execute(
                """
                INSERT INTO candidate_reviews(
                    id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                    rule_version, evidence_json, tier, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    occurred_on,
                    effective_pool,
                    code,
                    name_value,
                    score,
                    decision_value,
                    timing_value,
                    reason_value,
                    rule_value,
                    evidence_json,
                    tier_value,
                    source_value,
                    _now(),
                ),
            )
        return candidate_id

    def record_plan(
        self,
        *,
        code: str,
        title: str,
        scenario: str,
        occurred_on: str | None = None,
        entry_zone: str = "",
        stop_price: float | None = None,
        target_price: float | None = None,
        layers: float | None = None,
        invalidation: str = "",
        rule_version: str = "qianlong-v1",
        source: str = "manual",
        supersedes_id: str | None = None,
        note: str = "",
    ) -> str:
        code = normalize_code(code)
        if not title.strip() or not scenario.strip():
            raise PalaceError("计划必须有标题和情景")
        if layers is not None and layers <= 0:
            raise PalaceError("计划层数必须大于 0")
        plan_id = f"PL-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            stock = cursor.execute("SELECT name FROM stocks WHERE code = ?", (code,)).fetchone()
            self._upsert_stock(cursor, code, str(stock["name"]) if stock else code)
            cursor.execute(
                """
                INSERT INTO plans(
                    id, occurred_on, code, title, scenario, entry_zone, stop_price, target_price, layers,
                    invalidation, rule_version, source, supersedes_id, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (plan_id, normalize_date(occurred_on), code, title.strip(), scenario.strip(), entry_zone.strip(), stop_price,
                 target_price, layers, invalidation.strip(), rule_version.strip() or "qianlong-v1", source.strip() or "manual",
                 supersedes_id, note.strip(), _now()),
            )
        return plan_id

    def record_review(
        self,
        *,
        entity_type: str,
        entity_id: str,
        outcome: str,
        reviewed_on: str | None = None,
        strategy_tag: str = "qianlong",
        return_pct: float | None = None,
        max_favorable_pct: float | None = None,
        max_adverse_pct: float | None = None,
        lesson: str = "",
        next_rule: str = "",
        source: str = "manual",
    ) -> str:
        entity_type = entity_type.lower()
        if entity_type not in {"plan", "candidate", "trade"}:
            raise PalaceError("复盘对象必须为 plan、candidate 或 trade")
        if not entity_id.strip() or not outcome.strip():
            raise PalaceError("复盘必须有对象 ID 与结果")
        review_id = f"RV-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO reviews(
                    id, reviewed_on, entity_type, entity_id, strategy_tag, outcome, return_pct,
                    max_favorable_pct, max_adverse_pct, lesson, next_rule, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (review_id, normalize_date(reviewed_on), entity_type, entity_id.strip(), strategy_tag.strip() or "qianlong",
                 outcome.strip(), return_pct, max_favorable_pct, max_adverse_pct, lesson.strip(), next_rule.strip(),
                 source.strip() or "manual", _now()),
            )
        return review_id

    def list_positions(self) -> list[Position]:
        rows = self.conn.execute("SELECT code, name, shares, cost, updated_on, note FROM holdings ORDER BY cost * shares DESC, code").fetchall()
        return [
            Position(str(row["code"]), str(row["name"]), int(row["shares"]), float(row["cost"]), str(row["updated_on"]), str(row["note"]))
            for row in rows
        ]

    def positions_payload(self) -> list[dict[str, Any]]:
        """返回前端消费的当前仓位投影，不混入未经记录的实时价格。"""
        return [
            {
                "code": position.code,
                "name": position.name,
                "shares": position.shares,
                "cost": position.cost,
                "cost_value": position.cost_value,
                "updated_on": position.updated_on,
                "note": position.note,
            }
            for position in self.list_positions()
        ]

    def candidates_payload(self, occurred_on: str | None = None) -> list[dict[str, Any]]:
        """读取候选池；未传日期时按最新候选日展示。同日同池同标的只返回最新一条。"""
        target_date = normalize_date(occurred_on) if occurred_on else None
        if target_date is None:
            latest = self.conn.execute("SELECT MAX(occurred_on) AS value FROM candidate_reviews").fetchone()["value"]
            target_date = str(latest) if latest else None
        if not target_date:
            return []
        rows = self.conn.execute(
            """
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, evidence_json, tier, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, evidence_json, tier, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE occurred_on = ?
            ) ranked
            WHERE rn = 1
            ORDER BY score DESC NULLS LAST, created_at ASC
            """,
            (target_date,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "pool_id": str(row["pool_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "score": float(row["score"]) if row["score"] is not None else None,
                "decision": str(row["decision"]),
                "timing": str(row["timing"]),
                "reason": str(row["reason"]),
                "rule_version": str(row["rule_version"]),
                "evidence": _loads(str(row["evidence_json"])),
                "tier": str(row["tier"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def plans_payload(self, status: str = "active") -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, occurred_on, code, title, status, scenario, entry_zone, stop_price,
                   target_price, layers, invalidation, rule_version, source, supersedes_id, note, created_at
            FROM plans WHERE status = ? ORDER BY occurred_on DESC, created_at DESC
            """,
            (status,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "code": str(row["code"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "scenario": str(row["scenario"]),
                "entry_zone": str(row["entry_zone"]),
                "stop_price": float(row["stop_price"]) if row["stop_price"] is not None else None,
                "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
                "layers": float(row["layers"]) if row["layers"] is not None else None,
                "invalidation": str(row["invalidation"]),
                "rule_version": str(row["rule_version"]),
                "source": str(row["source"]),
                "supersedes_id": str(row["supersedes_id"] or ""),
                "note": str(row["note"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def timeline_payload(self, code: str) -> list[dict[str, Any]]:
        """提供单票事件流，保留原始 ID 供复盘对象精确关联。"""
        code = normalize_code(code)
        exists = self.conn.execute("SELECT 1 FROM stocks WHERE code = ?", (code,)).fetchone()
        if exists is None:
            raise PalaceError(f"账本中不存在 {code}")
        position_events = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, action, shares, price, shares_before, shares_after,
                   cost_before, cost_after, realized_pnl, reason, source, correlation_id, metadata_json
            FROM position_events WHERE code = ?
            """,
            (code,),
        ).fetchall()
        candidates = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, pool_id, score, decision, timing, reason,
                   rule_version, evidence_json, source
            FROM candidate_reviews WHERE code = ?
            """,
            (code,),
        ).fetchall()
        plans = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, title, status, scenario, entry_zone, stop_price,
                   target_price, layers, invalidation, rule_version, note, source
            FROM plans WHERE code = ?
            """,
            (code,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "trade", "label": str(row["action"]), "detail": {
                    "shares": int(row["shares"]), "price": float(row["price"]), "shares_before": int(row["shares_before"]),
                    "shares_after": int(row["shares_after"]), "cost_before": float(row["cost_before"]),
                    "cost_after": float(row["cost_after"]), "realized_pnl": float(row["realized_pnl"]),
                    "reason": str(row["reason"]), "source": str(row["source"]),
                    "correlation_id": str(row["correlation_id"]), "metadata": _loads(str(row["metadata_json"])),
                },
            }
            for row in position_events
        )
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "candidate", "label": str(row["decision"]), "detail": {
                    "pool_id": str(row["pool_id"]), "score": float(row["score"]) if row["score"] is not None else None,
                    "timing": str(row["timing"]), "reason": str(row["reason"]), "rule_version": str(row["rule_version"]),
                    "evidence": _loads(str(row["evidence_json"])), "source": str(row["source"]),
                },
            }
            for row in candidates
        )
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "plan", "label": str(row["title"]), "detail": {
                    "status": str(row["status"]), "scenario": str(row["scenario"]), "entry_zone": str(row["entry_zone"]),
                    "stop_price": float(row["stop_price"]) if row["stop_price"] is not None else None,
                    "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
                    "layers": float(row["layers"]) if row["layers"] is not None else None,
                    "invalidation": str(row["invalidation"]), "rule_version": str(row["rule_version"]),
                    "note": str(row["note"]), "source": str(row["source"]),
                },
            }
            for row in plans
        )
        # 关联到本票事件的复盘记录
        entity_ids = [str(e["id"]) for e in events]
        review_rows: list[sqlite3.Row] = []
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            review_rows = self.conn.execute(
                f"""
                SELECT id, reviewed_on, created_at, entity_type, entity_id, strategy_tag, outcome,
                       return_pct, max_favorable_pct, max_adverse_pct, lesson, next_rule, source
                FROM reviews
                WHERE entity_id IN ({placeholders})
                """,
                entity_ids,
            ).fetchall()
        events.extend(
            {
                "id": str(row["id"]),
                "date": str(row["reviewed_on"]),
                "created_at": str(row["created_at"]),
                "type": "review",
                "label": str(row["outcome"]),
                "detail": {
                    "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "strategy_tag": str(row["strategy_tag"]),
                    "return_pct": float(row["return_pct"]) if row["return_pct"] is not None else None,
                    "max_favorable_pct": float(row["max_favorable_pct"]) if row["max_favorable_pct"] is not None else None,
                    "max_adverse_pct": float(row["max_adverse_pct"]) if row["max_adverse_pct"] is not None else None,
                    "lesson": str(row["lesson"]),
                    "next_rule": str(row["next_rule"]),
                    "source": str(row["source"]),
                },
            }
            for row in review_rows
        )
        # 新→旧，方便从交割单点进来先看最近历史
        return sorted(events, key=lambda event: (event["date"], event["created_at"], event["id"]), reverse=True)

    def dashboard_payload(self, as_of: str | None = None) -> dict[str, Any]:
        """面向工作台的结构化看板数据；展示数值均来自账本而非估算行情。"""
        as_of = normalize_date(as_of)
        snapshot = self._latest_snapshot()
        positions = self.positions_payload()
        total_cost = round(sum(float(position["cost_value"]) for position in positions), 2)
        total_assets = float(snapshot["total_assets"]) if snapshot else None
        reviews_count = int(self.conn.execute("SELECT COUNT(*) AS value FROM reviews").fetchone()["value"])
        historical_baseline = self.conn.execute(
            """
            SELECT 1 FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT' AND occurred_on = ? AND source = 'qianlong-skill-memory'
            LIMIT 1
            """,
            (as_of,),
        ).fetchone()
        detailed_day_events = self.conn.execute(
            """
            SELECT COUNT(*) AS value FROM position_events
            WHERE occurred_on = ? AND realized_pnl <> 0
            """,
            (as_of,),
        ).fetchone()["value"]
        detailed_day_imports = self.conn.execute(
            """
            SELECT COUNT(*) AS value FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT' AND occurred_on = ? AND source <> 'qianlong-skill-memory'
            """,
            (as_of,),
        ).fetchone()["value"]
        today_is_baseline_only = bool(historical_baseline) and not (detailed_day_events or detailed_day_imports)
        candidates = self.candidates_payload(as_of)
        return {
            "as_of": as_of,
            "account": {
                "realized_pnl": self.realized_pnl(),
                "today_realized_pnl": None if today_is_baseline_only else self.realized_pnl(
                    as_of, include_historical_baseline=False
                ),
                "today_realized_note": "旧账仅导入累计盈亏基线；当日明细待补录" if today_is_baseline_only else f"截至 {as_of}",
                "total_assets": total_assets,
                "snapshot_date": str(snapshot["occurred_on"]) if snapshot else None,
                "cash": float(snapshot["cash"]) if snapshot and snapshot["cash"] is not None else None,
                "cost_exposure": total_cost,
                "cost_exposure_pct": round(total_cost / total_assets * 100, 2) if total_assets else None,
            },
            "positions": positions,
            "candidates": candidates,
            "candidate_summary": self.candidate_day_summary(candidates),
            "plans": self.plans_payload(),
            "scorecard": self.scorecard(),
            "evolution": {
                "review_count": reviews_count,
                "gate": 5,
                "ready": reviews_count >= 5,
                "message": "样本达到门槛，可按 rule_version 进行前向验证。" if reviews_count >= 5 else "复盘样本不足 5 条，当前只记录假设，不修改规则。",
            },
        }

    def _latest_snapshot(self) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM account_snapshots ORDER BY occurred_on DESC, created_at DESC LIMIT 1"
        ).fetchone()

    def realized_pnl(self, occurred_on: str | None = None, *, include_historical_baseline: bool = True) -> float:
        """汇总已实现盈亏；历史累计基线不得伪装成某一天的成交明细。"""
        params: list[str] = []
        where = ""
        if occurred_on:
            where = " WHERE occurred_on = ?"
            params.append(normalize_date(occurred_on))
        position_value = self.conn.execute(
            f"SELECT COALESCE(SUM(realized_pnl), 0) AS value FROM position_events{where}", params
        ).fetchone()["value"]
        account_where = " WHERE kind = 'REALIZED_PNL_IMPORT'"
        account_params = list(params)
        if not include_historical_baseline:
            account_where += " AND source <> 'qianlong-skill-memory'"
        if occurred_on:
            account_where += " AND occurred_on = ?"
        account_value = self.conn.execute(
            f"SELECT COALESCE(SUM(amount), 0) AS value FROM account_events{account_where}", account_params
        ).fetchone()["value"]
        return round(float(position_value) + float(account_value), 2)

    def scorecard(self) -> dict[str, Any]:
        sells = self.conn.execute(
            "SELECT realized_pnl FROM position_events WHERE action = 'SELL' ORDER BY occurred_on, created_at"
        ).fetchall()
        values = [float(row["realized_pnl"]) for row in sells]
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value < 0]
        review_rows = self.conn.execute(
            "SELECT strategy_tag, return_pct FROM reviews WHERE return_pct IS NOT NULL"
        ).fetchall()
        groups: dict[str, list[float]] = {}
        for row in review_rows:
            groups.setdefault(str(row["strategy_tag"]), []).append(float(row["return_pct"]))
        return {
            "closed_trades": len(values),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(values) * 100, 2) if values else None,
            "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else None,
            "average_realized": round(sum(values) / len(values), 2) if values else None,
            "realized_pnl": self.realized_pnl(),
            "review_groups": {
                tag: {"count": len(returns), "average_return_pct": round(sum(returns) / len(returns), 2)}
                for tag, returns in groups.items()
            },
        }

    def candidates_by_strategy(
        self,
        rule_version: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按战法（rule_version）查历史选股记录。

        每天、每标的取最新一条（同池同标的可能重跑），按日期倒序。
        用于前端"选股历史"页：按战法+日期区间浏览，不依赖账本的精选口径。
        """
        params: list[Any] = [rule_version]
        clauses = ["rule_version = ?"]
        if start:
            clauses.append("occurred_on >= ?")
            params.append(start)
        if end:
            clauses.append("occurred_on <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        params.append(int(limit))
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, evidence_json, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, evidence_json, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY occurred_on, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE {where}
            ) ranked
            WHERE rn = 1
            ORDER BY occurred_on DESC, score DESC NULLS LAST
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "pool_id": str(row["pool_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "score": float(row["score"]) if row["score"] is not None else None,
                "decision": str(row["decision"]),
                "timing": str(row["timing"]),
                "reason": str(row["reason"]),
                "rule_version": str(row["rule_version"]),
                "evidence": _loads(str(row["evidence_json"])),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def winrate_trend(
        self,
        *,
        strategy_tags: list[str] | None = None,
        granularity: str = "month",
    ) -> list[dict[str, Any]]:
        """按时间粒度统计各战法的胜率趋势。

        数据源：reviews 表的 return_pct 字段（有复盘记录时才有值）。
        granularity: 'month'(YYYY-MM) 或 'week'(YYYY-Www)。
        返回 [{period, strategy_tag, total, wins, win_rate}]，按 period+tag 升序。
        """
        if granularity == "week":
            # 用本周周一日期作为 period key（YYYY-MM-DD），避免 strftime('%W') 的
            # W00 边界问题（年初第一个周一之前的天数会落到 W00）。
            period_expr = "date(reviewed_on, 'weekday 0', '-6 days')"
        else:
            period_expr = "strftime('%Y-%m', reviewed_on)"

        params: list[Any] = []
        where = "return_pct IS NOT NULL"
        if strategy_tags:
            placeholders = ",".join("?" * len(strategy_tags))
            where += f" AND strategy_tag IN ({placeholders})"
            params.extend(strategy_tags)

        rows = self.conn.execute(
            f"""
            SELECT {period_expr} AS period,
                   strategy_tag,
                   COUNT(*) AS total,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS wins
            FROM reviews
            WHERE {where}
            GROUP BY period, strategy_tag
            ORDER BY period ASC, strategy_tag ASC
            """,
            params,
        ).fetchall()
        return [
            {
                "period": str(row["period"]),
                "strategy_tag": str(row["strategy_tag"]),
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]) * 100, 1) if row["total"] else None,
            }
            for row in rows
        ]

    def strategy_winrates(self) -> list[dict[str, Any]]:
        """各战法综合胜率（全时段汇总）。用于首页滚动展示。"""
        rows = self.conn.execute(
            """
            SELECT strategy_tag,
                   COUNT(*) AS total,
                   SUM(CASE WHEN return_pct > 0 THEN 1 ELSE 0 END) AS wins,
                   AVG(return_pct) AS avg_return,
                   MAX(reviewed_on) AS last_reviewed
            FROM reviews
            WHERE return_pct IS NOT NULL
            GROUP BY strategy_tag
            ORDER BY total DESC
            """
        ).fetchall()
        return [
            {
                "strategy_tag": str(row["strategy_tag"]),
                "total": int(row["total"]),
                "wins": int(row["wins"]),
                "win_rate": round(int(row["wins"]) / int(row["total"]) * 100, 1) if row["total"] else None,
                "avg_return": round(float(row["avg_return"]), 2) if row["avg_return"] is not None else None,
                "last_reviewed": str(row["last_reviewed"]) if row["last_reviewed"] else "",
            }
            for row in rows
        ]

    @staticmethod
    def _is_selected_decision(decision: str) -> bool:
        """精选口径：重点/入选/高确定性等视为通过筛选，其余记为未精选。"""
        text = decision.strip().lower()
        selected_tokens = ("重点", "入选", "高确定性", "精选", "值得做", "买入", "做多", "关注", "首仓", "持有")
        rejected_tokens = ("落选", "排除", "放弃", "否决", "剔除", "过滤")
        if any(token in text for token in rejected_tokens):
            return False
        return any(token in text for token in selected_tokens)

    def candidate_day_summary(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """汇总当日候选：结构化条目，方便前端排版；正文只转述账本字段，不新增价位判断。"""
        selected = [item for item in candidates if self._is_selected_decision(str(item["decision"]))]
        filtered = [item for item in candidates if not self._is_selected_decision(str(item["decision"]))]

        def _card(item: dict[str, Any]) -> dict[str, Any]:
            score = item.get("score")
            return {
                "id": str(item.get("id") or ""),
                "code": str(item["code"]),
                "name": str(item["name"]),
                "score": float(score) if score is not None else None,
                "decision": str(item.get("decision") or ""),
                "timing": str(item.get("timing") or "").strip(),
                "reason": str(item.get("reason") or "").strip() or "（未写理由）",
            }

        picks = [_card(item) for item in selected]
        drops = [_card(item) for item in filtered]

        if not candidates:
            headline = "当日无候选"
            note = "账本无候选记录。"
        elif selected and not filtered:
            headline = f"全选 {len(selected)} 只"
            note = "本池均为精选。纪要只汇总账本原文，不生成新价位或买卖建议。"
        elif selected and filtered:
            headline = f"精选 {len(selected)} / 全量 {len(candidates)}"
            note = f"未选 {len(filtered)} 只。纪要只汇总账本原文，不生成新价位或买卖建议。"
        else:
            headline = f"全量 {len(candidates)} 只 · 无精选"
            note = "当日无精选标的。纪要只汇总账本原文，不生成新价位或买卖建议。"

        # 纯文本兜底：多行，给 CLI / Agent 用
        lines = [headline, note]
        if picks:
            lines.append("精选")
            for card in picks:
                score_text = f"{card['score']:.0f}" if card["score"] is not None else "—"
                timing = f" · {card['timing']}" if card["timing"] else ""
                lines.append(f"- {card['name']} {card['code']}  {score_text}  {card['decision']}{timing}")
                lines.append(f"  {card['reason']}")
        if drops:
            lines.append("未选")
            for card in drops:
                score_text = f"{card['score']:.0f}" if card["score"] is not None else "—"
                lines.append(f"- {card['name']} {card['code']}  {score_text}  {card['decision']}")
                lines.append(f"  {card['reason']}")

        return {
            "headline": headline,
            "note": note,
            "text": "\n".join(lines),
            "total": len(candidates),
            "selected_count": len(selected),
            "filtered_count": len(filtered),
            "all_selected": bool(selected) and not filtered,
            "picks": picks,
            "drops": drops,
        }

    def trades_payload(self, code: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """交割单视图：按时间倒序输出加减持与已实现盈亏。"""
        if limit <= 0 or limit > 1000:
            raise PalaceError("limit 必须在 1-1000 之间")
        clauses: list[str] = []
        params: list[Any] = []
        if code:
            clauses.append("code = ?")
            params.append(normalize_code(code))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, created_at, code, name, action, shares, price,
                   shares_before, shares_after, cost_before, cost_after, realized_pnl,
                   reason, source, correlation_id
            FROM position_events
            {where}
            ORDER BY occurred_on DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "created_at": str(row["created_at"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "action": str(row["action"]),
                "shares": int(row["shares"]),
                "price": float(row["price"]),
                "amount": round(int(row["shares"]) * float(row["price"]), 2),
                "shares_before": int(row["shares_before"]),
                "shares_after": int(row["shares_after"]),
                "cost_before": float(row["cost_before"]),
                "cost_after": float(row["cost_after"]),
                "realized_pnl": float(row["realized_pnl"]),
                "reason": str(row["reason"]),
                "source": str(row["source"]),
                "correlation_id": str(row["correlation_id"]),
            }
            for row in rows
        ]

    def reviews_payload(self, limit: int = 100) -> list[dict[str, Any]]:
        """复盘记忆列表：按复盘日期倒序。"""
        if limit <= 0 or limit > 500:
            raise PalaceError("limit 必须在 1-500 之间")
        rows = self.conn.execute(
            """
            SELECT id, reviewed_on, entity_type, entity_id, strategy_tag, outcome,
                   return_pct, max_favorable_pct, max_adverse_pct, lesson, next_rule,
                   source, created_at
            FROM reviews
            ORDER BY reviewed_on DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["reviewed_on"]),
                "entity_type": str(row["entity_type"]),
                "entity_id": str(row["entity_id"]),
                "strategy_tag": str(row["strategy_tag"]),
                "outcome": str(row["outcome"]),
                "return_pct": float(row["return_pct"]) if row["return_pct"] is not None else None,
                "max_favorable_pct": float(row["max_favorable_pct"]) if row["max_favorable_pct"] is not None else None,
                "max_adverse_pct": float(row["max_adverse_pct"]) if row["max_adverse_pct"] is not None else None,
                "lesson": str(row["lesson"]),
                "next_rule": str(row["next_rule"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def pool_dates_payload(self) -> list[dict[str, Any]]:
        """候选池按日汇总，便于复盘时跳转某日全量 vs 精选差异。"""
        rows = self.conn.execute(
            """
            SELECT occurred_on AS date, pool_id
            FROM candidate_reviews
            GROUP BY occurred_on, pool_id
            ORDER BY occurred_on DESC, pool_id ASC
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            day = str(row["date"])
            pool_id = str(row["pool_id"])
            candidates = self.candidates_payload(day)
            pool_candidates = [item for item in candidates if item["pool_id"] == pool_id]
            selected = [item for item in pool_candidates if self._is_selected_decision(str(item["decision"]))]
            scored = [item for item in pool_candidates if item["score"] is not None]
            avg_score = round(sum(float(item["score"]) for item in scored) / len(scored), 2) if scored else None
            result.append(
                {
                    "date": day,
                    "pool_id": pool_id,
                    "total": len(pool_candidates),
                    "selected": len(selected),
                    "filtered": max(len(pool_candidates) - len(selected), 0),
                    "scored": len(scored),
                    "avg_score": avg_score,
                }
            )
        return result

    def pool_day_payload(self, occurred_on: str | None = None, pool_id: str | None = None) -> dict[str, Any]:
        """某一日（可选指定 pool）候选全量，并拆出精选/未精选差异。"""
        candidates = self.candidates_payload(occurred_on)
        if not candidates:
            target = normalize_date(occurred_on) if occurred_on else date.today().isoformat()
            empty_summary = self.candidate_day_summary([])
            return {
                "date": target,
                "pool_id": pool_id or "",
                "total": 0,
                "selected_count": 0,
                "filtered_count": 0,
                "selected": [],
                "filtered": [],
                "all": [],
                "summary": empty_summary,
            }
        target_date = str(candidates[0]["date"])
        if pool_id:
            candidates = [item for item in candidates if str(item["pool_id"]) == pool_id]
        selected = [item for item in candidates if self._is_selected_decision(str(item["decision"]))]
        filtered = [item for item in candidates if not self._is_selected_decision(str(item["decision"]))]
        resolved_pool = pool_id or (str(candidates[0]["pool_id"]) if candidates else "")
        summary = self.candidate_day_summary(candidates)
        return {
            "date": target_date,
            "pool_id": resolved_pool,
            "total": len(candidates),
            "selected_count": len(selected),
            "filtered_count": len(filtered),
            "selected": selected,
            "filtered": filtered,
            "all": candidates,
            "summary": summary,
        }

    def analytics_payload(self) -> dict[str, Any]:
        """可视化：累计盈亏曲线、日盈亏、决策分布、复盘收益。"""
        trade_rows = self.conn.execute(
            """
            SELECT occurred_on, SUM(realized_pnl) AS day_pnl
            FROM position_events
            GROUP BY occurred_on
            ORDER BY occurred_on ASC
            """
        ).fetchall()
        import_rows = self.conn.execute(
            """
            SELECT occurred_on, SUM(amount) AS day_pnl
            FROM account_events
            WHERE kind = 'REALIZED_PNL_IMPORT'
            GROUP BY occurred_on
            ORDER BY occurred_on ASC
            """
        ).fetchall()
        day_map: dict[str, float] = {}
        for row in trade_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(row["day_pnl"] or 0)
        for row in import_rows:
            day_map[str(row["occurred_on"])] = day_map.get(str(row["occurred_on"]), 0.0) + float(row["day_pnl"] or 0)
        cumulative = 0.0
        equity_curve: list[dict[str, Any]] = []
        daily_pnl: list[dict[str, Any]] = []
        for day in sorted(day_map):
            pnl = round(day_map[day], 2)
            cumulative = round(cumulative + pnl, 2)
            daily_pnl.append({"date": day, "pnl": pnl})
            equity_curve.append({"date": day, "cumulative_pnl": cumulative})

        decision_rows = self.conn.execute(
            """
            SELECT decision, COUNT(*) AS count
            FROM (
                SELECT decision,
                       ROW_NUMBER() OVER (
                           PARTITION BY occurred_on, pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
            ) ranked
            WHERE rn = 1
            GROUP BY decision
            ORDER BY count DESC, decision ASC
            """
        ).fetchall()
        decisions = [{"decision": str(row["decision"]), "count": int(row["count"])} for row in decision_rows]

        review_rows = self.conn.execute(
            """
            SELECT reviewed_on, return_pct, strategy_tag
            FROM reviews
            WHERE return_pct IS NOT NULL
            ORDER BY reviewed_on ASC, created_at ASC
            """
        ).fetchall()
        review_returns = [
            {
                "date": str(row["reviewed_on"]),
                "return_pct": float(row["return_pct"]),
                "strategy_tag": str(row["strategy_tag"]),
            }
            for row in review_rows
        ]

        action_rows = self.conn.execute(
            """
            SELECT action, COUNT(*) AS count, COALESCE(SUM(realized_pnl), 0) AS realized
            FROM position_events
            GROUP BY action
            ORDER BY action
            """
        ).fetchall()
        actions = [
            {
                "action": str(row["action"]),
                "count": int(row["count"]),
                "realized_pnl": round(float(row["realized"]), 2),
            }
            for row in action_rows
        ]

        return {
            "equity_curve": equity_curve,
            "daily_pnl": daily_pnl,
            "decisions": decisions,
            "review_returns": review_returns,
            "actions": actions,
            "scorecard": self.scorecard(),
        }

    def dashboard_markdown(self, as_of: str | None = None) -> str:
        """生成只含事实、预案状态和数据质量提示的日常看板。"""
        as_of = normalize_date(as_of)
        positions = self.list_positions()
        snapshot = self._latest_snapshot()
        total_cost = round(sum(position.cost_value for position in positions), 2)
        total_assets = float(snapshot["total_assets"]) if snapshot else None
        active_plans = self.conn.execute(
            "SELECT id, code, title, entry_zone, stop_price, target_price, layers, invalidation FROM plans WHERE status = 'active' ORDER BY occurred_on DESC, created_at DESC"
        ).fetchall()
        candidates = self.conn.execute(
            """
            SELECT pool_id, COUNT(*) AS total,
                   SUM(CASE WHEN decision IN ('高确定性', '重点', '入选') THEN 1 ELSE 0 END) AS selected
            FROM candidate_reviews WHERE occurred_on = ? GROUP BY pool_id ORDER BY pool_id
            """,
            (as_of,),
        ).fetchall()
        scorecard = self.scorecard()
        coverage = self.conn.execute("SELECT COUNT(*) AS value FROM reviews").fetchone()["value"]

        lines = [
            "# 潜龙记忆宫殿｜日常看板",
            "",
            f"> 截至：{as_of} ｜账本：`{self.db_path}` ｜仅作研究记录与复盘，不构成投资建议。",
            "",
            "## 账户与仓位",
            "",
            f"- 已实现累计：**{self.realized_pnl():+.2f} 元**",
            f"- 当日已实现：**{self.realized_pnl(as_of):+.2f} 元**",
            f"- 最近总资产快照：**{total_assets:,.2f} 元**（{snapshot['occurred_on']}）" if snapshot else "- 最近总资产快照：未记录",
            f"- 持仓成本占用：**{total_cost:,.2f} 元**" + (f"（约 {total_cost / total_assets * 100:.1f}%）" if total_assets else ""),
            "",
            "| 代码 | 名称 | 股数 | 成本 | 成本金额 | 最后变更 | 备注 |",
            "|---|---:|---:|---:|---:|---|---|",
        ]
        if positions:
            lines.extend(
                f"| {position.code} | {position.name} | {position.shares} | {position.cost:.3f} | {position.cost_value:,.2f} | {position.updated_on} | {position.note or '-'} |"
                for position in positions
            )
        else:
            lines.append("| - | 当前无持仓 | - | - | - | - | - |")

        lines.extend(["", "## 候选池与预案", ""])
        if candidates:
            lines.extend(["| 候选池 | 总数 | 重点/入选 |", "|---|---:|---:|"])
            lines.extend(f"| {row['pool_id']} | {row['total']} | {row['selected']} |" for row in candidates)
        else:
            lines.append("- 当日尚未归档候选池。")
        if active_plans:
            lines.extend(["", "| 计划 ID | 标的 | 预案 | 入场区 | 止损 | 目标 | 层数 | 失效条件 |", "|---|---|---|---|---:|---:|---:|---|"])
            for plan in active_plans:
                stop = f"{float(plan['stop_price']):.3f}" if plan["stop_price"] is not None else "-"
                target = f"{float(plan['target_price']):.3f}" if plan["target_price"] is not None else "-"
                layers = f"{float(plan['layers']):.2f}" if plan["layers"] is not None else "-"
                lines.append(
                    f"| {plan['id']} | {plan['code']} | {plan['title']} | {plan['entry_zone'] or '-'} | {stop} | {target} | {layers} | {plan['invalidation'] or '-'} |"
                )
        else:
            lines.append("- 当前无 active 预案。")

        lines.extend([
            "",
            "## 量化复盘与进化门槛",
            "",
            f"- 已平仓事件：{scorecard['closed_trades']} 笔；胜率：{scorecard['win_rate'] if scorecard['win_rate'] is not None else '-'}%；盈亏比：{scorecard['profit_factor'] if scorecard['profit_factor'] is not None else '-'}。",
            f"- 已记录复盘：{coverage} 条。",
        ])
        if coverage < 5:
            lines.append("- 进化建议：样本不足 5 条，只记录假设与结果，暂不修改规则版本。")
        else:
            lines.append("- 进化建议：可按策略标签比较复盘收益、MFE/MAE 与失效原因，再以新 rule_version 做小样本前向验证。")
        if scorecard["review_groups"]:
            lines.extend(["", "| 策略标签 | 已复盘样本 | 平均收益率 |", "|---|---:|---:|"])
            lines.extend(
                f"| {tag} | {item['count']} | {item['average_return_pct']:+.2f}% |"
                for tag, item in sorted(scorecard["review_groups"].items())
            )
        return "\n".join(lines) + "\n"

    def timeline_markdown(self, code: str) -> str:
        code = normalize_code(code)
        stock = self.conn.execute("SELECT name FROM stocks WHERE code = ?", (code,)).fetchone()
        if stock is None:
            raise PalaceError(f"账本中不存在 {code}")
        rows = self.conn.execute(
            """
            SELECT occurred_on AS event_date, created_at, '仓位事件' AS category, id,
                   action || ' ' || shares || '股 @ ' || printf('%.3f', price) ||
                   '｜余仓 ' || shares_after || '｜余票成本 ' || printf('%.3f', cost_after) ||
                   '｜已实现 ' || printf('%+.2f', realized_pnl) ||
                   CASE WHEN reason <> '' THEN '｜' || reason ELSE '' END AS detail
            FROM position_events WHERE code = ?
            UNION ALL
            SELECT occurred_on, created_at, '候选裁决', id,
                   pool_id || '｜' || decision || CASE WHEN score IS NOT NULL THEN '｜评分 ' || printf('%.1f', score) ELSE '' END ||
                   CASE WHEN timing <> '' THEN '｜' || timing ELSE '' END || '｜' || reason
            FROM candidate_reviews WHERE code = ?
            UNION ALL
            SELECT occurred_on, created_at, '作战预案', id,
                   title || '｜' || scenario || CASE WHEN invalidation <> '' THEN '｜失效：' || invalidation ELSE '' END
            FROM plans WHERE code = ?
            ORDER BY event_date, created_at
            """,
            (code, code, code),
        ).fetchall()
        lines = [f"# {stock['name']}（{code}）追溯时间线", "", "| 日期 | 类型 | ID | 事实/预案 |", "|---|---|---|---|"]
        lines.extend(f"| {row['event_date']} | {row['category']} | {row['id']} | {row['detail']} |" for row in rows)
        if not rows:
            lines.append("| - | - | - | 尚无记录 |")
        return "\n".join(lines) + "\n"

    def import_qianlong_state(self, state_path: Path | str, source: str = "qianlong-skill-memory") -> dict[str, Any]:
        """从潜龙技能的 ``state.json`` 导入一个可审计的起始快照。

        导入只允许在空仓位账本执行，防止把同一份记忆重复计入交易历史；历史已实现盈亏
        作为 ``REALIZED_PNL_IMPORT`` 基线，不会冒充项目内发生的卖出事件。
        """
        path = Path(state_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PalaceError(f"无法读取潜龙 state.json：{path}") from exc
        if not isinstance(payload, dict):
            raise PalaceError("潜龙 state.json 必须是 JSON 对象")
        if self.conn.execute("SELECT COUNT(*) AS value FROM position_events").fetchone()["value"]:
            raise PalaceError("账本已有仓位事件；为避免重复导入，请使用新的数据库文件")

        imported_on = normalize_date(str(payload.get("updatedAt") or ""))
        imported: list[str] = []
        for item in payload.get("holdings") or []:
            if not isinstance(item, dict):
                continue
            shares = int(item.get("shares") or 0)
            cost = float(item.get("cost") or 0)
            if shares <= 0 or cost < 0:
                continue
            code = normalize_code(str(item.get("code") or ""))
            result = self.record_trade(
                action="OPENING",
                code=code,
                name=str(item.get("name") or code),
                shares=shares,
                price=cost,
                occurred_on=imported_on,
                reason=str(item.get("note") or "潜龙技能记忆导入"),
                source=source,
                metadata={"imported_from": str(path), "legacy_layers": item.get("layers"), "buy_date": item.get("buyDate")},
            )
            imported.append(result["id"])

        realized = float(payload.get("realizedPnlCumulative") or 0)
        if realized:
            self.record_account_event(
                kind="REALIZED_PNL_IMPORT",
                amount=realized,
                occurred_on=imported_on,
                note="从潜龙技能记忆导入的累计已实现盈亏基线",
                source=source,
                metadata={"imported_from": str(path)},
            )
        assets = payload.get("totalAssets")
        if assets is not None:
            self.record_snapshot(
                total_assets=float(assets),
                occurred_on=imported_on,
                note=str(payload.get("totalAssetsNote") or "从潜龙技能记忆导入"),
                source=source,
            )
        self._set_meta("qianlong_state_import", _dumps({"path": str(path), "date": imported_on, "events": imported}))
        self.conn.commit()
        return {"date": imported_on, "position_events": imported, "realized_pnl_baseline": realized, "total_assets": assets}

    def record_ai_judgment(
        self,
        *,
        occurred_on: str | None = None,
        strategy_tag: str,
        decision: str,
        top_codes: list[str],
        reason: str = "",
        provider: str = "",
        model: str = "",
        token_used: int = 0,
        source: str = "ai",
    ) -> str:
        """记录 AI 的选/弃仓决定，独立于量化选股池。
        事后可算 AI 否决的那些天量化 top3 真实涨了多少（AI alpha 核算）。
        """
        jid = f"AJ-{uuid4().hex[:12].upper()}"
        date_value = normalize_date(occurred_on)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO ai_judgments(id, occurred_on, strategy_tag, decision, top_codes,"
                " reason, provider, model, token_used, source, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    jid,
                    date_value,
                    strategy_tag,
                    decision,
                    json.dumps(top_codes, ensure_ascii=False),
                    reason[:2000],
                    provider[:64],
                    model[:120],
                    int(token_used),
                    source,
                ),
            )
        return jid

    def ai_judgment_payload(self, strategy_tag: str, limit: int = 100) -> list[dict[str, Any]]:
        """返回指定战法的 AI 判定记录，按日期倒序。"""
        rows = self.conn.execute(
            "SELECT * FROM ai_judgments WHERE strategy_tag = ?"
            " ORDER BY occurred_on DESC, created_at DESC LIMIT ?",
            (strategy_tag, limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            raw = d.get("top_codes") or "[]"
            try:
                d["top_codes"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d["top_codes"] = []
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # 持仓周期跟踪
    # ------------------------------------------------------------------

    def open_tracking(
        self,
        *,
        strategy_tag: str,
        pool_id: str,
        code: str,
        name: str,
        tier: str = "core",
        signal_date: str,
        entry_date: str,
        hold_days: int = 3,
        exit_by_date: str,
        entry_price: float | None = None,
    ) -> str:
        """开启一条持仓跟踪记录。"""
        code = normalize_code(code)
        tracking_id = f"PT-{uuid4().hex[:12].upper()}"
        now = _now()
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO position_tracking(
                    id, strategy_tag, pool_id, code, name, tier,
                    signal_date, entry_date, hold_days, exit_by_date,
                    entry_price, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    tracking_id,
                    strategy_tag.strip(),
                    pool_id.strip(),
                    code,
                    name.strip() or code,
                    tier.strip() or "core",
                    normalize_date(signal_date),
                    normalize_date(entry_date),
                    int(hold_days),
                    normalize_date(exit_by_date),
                    entry_price,
                    now,
                    now,
                ),
            )
        return tracking_id

    def close_tracking(
        self,
        tracking_id: str,
        *,
        exit_price: float | None = None,
        actual_return: float | None = None,
        reason: str = "expired",
    ) -> None:
        """关闭一条跟踪记录（到期、止损、止盈）。"""
        closed_status = "expired" if reason == "expired" else "closed"
        with self._transaction() as cursor:
            cursor.execute(
                """
                UPDATE position_tracking
                SET status = ?, exit_price = ?, actual_return = ?,
                    closed_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (closed_status, exit_price, actual_return, reason.strip(), _now(), tracking_id),
            )

    def list_active_tracking(self, strategy_tag: str | None = None) -> list[dict]:
        """列出所有活跃跟踪（用于每日更新价格）。"""
        if strategy_tag:
            rows = self.conn.execute(
                "SELECT * FROM position_tracking WHERE status = 'active' AND strategy_tag = ?"
                " ORDER BY signal_date DESC",
                (strategy_tag,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM position_tracking WHERE status = 'active'"
                " ORDER BY signal_date DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def tracking_summary(self, strategy_tag: str, limit: int = 100) -> list[dict]:
        """已关闭的跟踪汇总，按 signal_date 降序。"""
        rows = self.conn.execute(
            "SELECT * FROM position_tracking"
            " WHERE strategy_tag = ? AND status != 'active'"
            " ORDER BY signal_date DESC LIMIT ?",
            (strategy_tag, limit),
        ).fetchall()
        return [dict(row) for row in rows]
