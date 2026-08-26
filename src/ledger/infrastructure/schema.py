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
    _normalize_decision,
    _normalize_reason_text,
    _normalize_rule_version,
    _normalize_timing,
    _now,
    normalize_code,
)


def _is_missing_object(exc: sqlite3.OperationalError) -> bool:
    """极旧库还没建这张表/列，跳过即可。

    其余 OperationalError（磁盘、锁、损坏）必须上抛：一次性数据迁移吞掉失败后
    ``init_schema`` 照样把 schema_version 盖成最新，那条迁移就再也不会重跑了。
    """
    message = str(exc).lower()
    return "no such table" in message or "no such column" in message


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
        current = self._schema_is_current()
        if current and resolved in _SCHEMA_READY:
            # 本进程已经补过 DDL。组合根按请求 new 一个 Store，在这里重跑建表/加列
            # 只是白付几次 ALTER 异常构造，外加一次写事务提交——后者还会和同步
            # 任务抢写锁。版本号一致 + 本进程已处理过，直接返回。
            return
        if current:
            # 当前版本只补结构迁移；候选事实的归一/回填属于一次性数据迁移，
            # 不能在普通打开账本时再次改写历史。
            self._run_migrations()
            self.conn.commit()
            _SCHEMA_READY.add(resolved)
            return

        had_candidate_table = bool(
            self.conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'candidate_reviews'
                """
            ).fetchone()
        )
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
                rule_version TEXT NOT NULL DEFAULT '潜龙',
                strategy_slug TEXT NOT NULL DEFAULT '',
                strategy_revision TEXT NOT NULL DEFAULT '',
                effective_params_json TEXT NOT NULL DEFAULT '{}',
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
                rule_version TEXT NOT NULL DEFAULT '潜龙',
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
                strategy_tag TEXT NOT NULL DEFAULT '潜龙',
                outcome TEXT NOT NULL,
                return_pct REAL,
                max_favorable_pct REAL,
                max_adverse_pct REAL,
                lesson TEXT NOT NULL DEFAULT '',
                next_rule TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL
            );
            -- 索引按真实查询建：9 处 reviews 查询没有一处约束 entity_type，
            -- 旧的 (entity_type, entity_id, reviewed_on) 前导列吃不上，只剩写入开销。
            CREATE INDEX IF NOT EXISTS idx_reviews_entity_id ON reviews(entity_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_tag ON reviews(strategy_tag, reviewed_on DESC);

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
            """
        )
        self._dedupe_candidate_reviews()
        self._run_migrations()
        if had_candidate_table:
            # 仅在旧库升级时执行一次历史数据迁移；当前版本重开不再触碰事实字段。
            self._normalize_candidate_vocab()
            self._retag_stale_screen_candidates()
        self._set_meta("schema_version", str(SCHEMA_VERSION))
        self.conn.commit()
        _SCHEMA_READY.add(str(self.db_path.resolve()))

    #: v10 下线的持仓/成交/账户七张表。已有库在 _run_migrations 里 DROP 掉。
    #: 顺序无所谓：没有任何一张被其它保留表外键引用（引用方向都是 -> stocks）。
    RETIRED_TABLES = (
        "position_events",
        "position_tracking",
        "account_events",
        "account_snapshots",
        "daily_pnl_ledger",
        "holdings",
        "ledger_write_receipts",
    )

    def _run_migrations(self) -> None:
        """增量迁移：对已有库补加新列、补建新表，并清掉已下线的表。

        CREATE TABLE IF NOT EXISTS 对已存在的表什么都不做，
        所以新增的列必须用 ALTER TABLE ADD COLUMN 单独迁移。
        SQLite 的 ALTER TABLE 在列已存在时会报错，用 try/except 跳过。

        注意：本方法只在 schema_version 与 SCHEMA_VERSION 不一致、或本进程首次打开
        该库时才跑得到。所以**加 DDL 和删 DDL 都必须同步 bump SCHEMA_VERSION**
        （见 store_types.SCHEMA_VERSION），否则已有库压根进不来这段。
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
            # v7: 公式战法运行可复现字段
            "ALTER TABLE candidate_reviews ADD COLUMN strategy_slug TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE candidate_reviews ADD COLUMN strategy_revision TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE candidate_reviews ADD COLUMN effective_params_json TEXT NOT NULL DEFAULT '{}'",
            "CREATE INDEX IF NOT EXISTS idx_candidates_strategy_slug ON candidate_reviews(strategy_slug, occurred_on DESC)",
            # reviews 索引换成匹配实际查询的两条；旧的前导列 entity_type 无人约束。
            # 索引是派生物，DROP 后由下面两条立即重建，不涉及账本事实。
            "CREATE INDEX IF NOT EXISTS idx_reviews_entity_id ON reviews(entity_id)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_tag ON reviews(strategy_tag, reviewed_on DESC)",
            "DROP INDEX IF EXISTS idx_reviews_entity",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError as exc:
                message = str(exc).lower()
                if "duplicate column name" in message or "already exists" in message:
                    continue
                raise
        self._drop_retired_tables()

    def _drop_retired_tables(self) -> None:
        """v10：持仓/成交/账户下线，把这七张表从已有库里删掉。幂等。

        用 DROP 而不是「建了不读」：留着的话旧代码路径还会往里写（position_tracking
        就是这么变成只写孤儿的），备份体积和 review 指纹扫描也都还要为它买单。
        索引随表一起消失，不必单独 DROP INDEX。

        表名是本模块的字面量常量，不来自外部输入，f-string 拼进 DDL 没有注入面；
        SQLite 的 DROP TABLE 也不接受参数占位符。
        """
        for table in self.RETIRED_TABLES:
            self.conn.execute(f"DROP TABLE IF EXISTS {table}")

    def _retag_stale_screen_candidates(self) -> None:
        """把「隔日写入却标成真选」的 API 选股行改标为回填。幂等。

        仅触碰 ``api:screen*``（不含已含 backfill 的源）；手工 ``manual`` /
        Job ``job:screen`` 不动。首页/复盘靠 source 排除回填即可一致。
        """
        try:
            self.conn.execute(
                """
                UPDATE candidate_reviews
                SET source = 'api:screen_backfill'
                WHERE IFNULL(source, '') NOT LIKE '%backfill%'
                  AND IFNULL(source, '') LIKE 'api:screen%'
                  AND substr(
                        REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10
                      ) <> occurred_on
                """
            )
        except sqlite3.OperationalError as exc:
            if not _is_missing_object(exc):
                raise

    def _normalize_candidate_vocab(self) -> None:
        """裁决/战法/时点/理由中文化归一。幂等。"""
        try:
            rows = self.conn.execute(
                "SELECT id, decision, timing, reason, rule_version FROM candidate_reviews"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if not _is_missing_object(exc):
                raise
            return
        for row in rows:
            new_decision = _normalize_decision(str(row["decision"]))
            new_timing = _normalize_timing(str(row["timing"]))
            new_reason = _normalize_reason_text(str(row["reason"]))
            new_rule = _normalize_rule_version(str(row["rule_version"]))
            if (
                new_decision == str(row["decision"])
                and new_timing == str(row["timing"])
                and new_reason == str(row["reason"])
                and new_rule == str(row["rule_version"])
            ):
                continue
            if new_decision not in ("精选", "落选", "观察"):
                new_decision = "观察"
            self.conn.execute(
                """
                UPDATE candidate_reviews
                SET decision = ?, timing = ?, reason = ?, rule_version = ?
                WHERE id = ?
                """,
                (new_decision, new_timing, new_reason, new_rule, str(row["id"])),
            )
        try:
            plan_rows = self.conn.execute("SELECT id, rule_version FROM plans").fetchall()
        except sqlite3.OperationalError as exc:
            if not _is_missing_object(exc):
                raise
            plan_rows = []
        for row in plan_rows:
            new_rule = _normalize_rule_version(str(row["rule_version"]))
            if new_rule != str(row["rule_version"]):
                self.conn.execute(
                    "UPDATE plans SET rule_version = ? WHERE id = ?",
                    (new_rule, str(row["id"])),
                )
        try:
            review_rows = self.conn.execute(
                "SELECT id, strategy_tag FROM reviews"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if not _is_missing_object(exc):
                raise
            review_rows = []
        for row in review_rows:
            new_tag = _normalize_rule_version(str(row["strategy_tag"]))
            if new_tag != str(row["strategy_tag"]):
                self.conn.execute(
                    "UPDATE reviews SET strategy_tag = ? WHERE id = ?",
                    (new_tag, str(row["id"])),
                )

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
