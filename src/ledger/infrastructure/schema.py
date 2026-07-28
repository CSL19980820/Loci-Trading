"""账本 SQLite schema、迁移与股票登记。"""
from __future__ import annotations

import json
import sqlite3
from typing import Sequence

from src.ledger.infrastructure.store_types import (
    SCHEMA_VERSION,
    PalaceError,
    _SCHEMA_READY,
    _dumps,
    _now,
    normalize_code,
)


class SchemaMixin:
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
            # 即使版本一致也要跑迁移：ADD COLUMN 是幂等的，
            # 但如果有人加了新列忘记 bump SCHEMA_VERSION，不跑迁移就会爆。
            # 代价：每次首次连接多跑几条 ALTER TABLE，全部 try/except 跳过，微秒级。
            self._run_migrations()
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

            -- 券商市值法当日盈亏（≠ 已实现盈亏）：今日市值+卖出 − 昨日市值−买入。
            CREATE TABLE IF NOT EXISTS daily_pnl_ledger (
                occurred_on TEXT PRIMARY KEY,
                broker_pnl REAL NOT NULL,
                market_pnl REAL,
                gap REAL,
                source TEXT NOT NULL DEFAULT 'market',
                note TEXT NOT NULL DEFAULT '',
                legs_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_daily_pnl_date
                ON daily_pnl_ledger(occurred_on DESC);
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
            # v5: 券商市值法当日盈亏账本
            """CREATE TABLE IF NOT EXISTS daily_pnl_ledger (
                occurred_on TEXT PRIMARY KEY,
                broker_pnl REAL NOT NULL,
                market_pnl REAL,
                gap REAL,
                source TEXT NOT NULL DEFAULT 'market',
                note TEXT NOT NULL DEFAULT '',
                legs_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
            "CREATE INDEX IF NOT EXISTS idx_daily_pnl_date ON daily_pnl_ledger(occurred_on DESC)",
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
