"""社区库（``data/community.db``）的 DDL 与迁移。

归属：**跨租户全局唯一**（路径来自 ``src.shared.paths.community_db()``）。广场是
公共空间，不能跟着租户切换而分裂成几份互相看不见的榜单。

可重建性：**不可重建**。发布物、评论、订阅、克隆记录都是用户产生的一次性事实，
删一行 = 抹掉一个人的作品或一段讨论，备份优先级与 ``palace.db`` 同级。
只有 ``strategy_metrics`` 与 ``leaderboard_snapshots`` 是可重算的派生数据
（``rebuild_leaderboard`` 能整表重建），清空它们只丢历史榜单的「当天视角」。

迁移风格与 ``ops.db`` / ``identity.db`` 对齐：``_SCHEMA`` 建初始表，``_MIGRATIONS``
平铺追加、每条自身幂等、每次连接无条件重跑。加表只准往 ``_MIGRATIONS`` 尾部追加。

**上架即冻结**（本库唯一的强约束）：``published_versions`` 上挂了 BEFORE UPDATE /
BEFORE DELETE 触发器，任何改写既有版本的语句都会 ABORT。理由见
``domain/models.py::PublishedVersion``——别人克隆走的那一份必须永远可对账，
改内容要发新版，下架用 ``published_strategies.status``。
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
                key       TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT NOT NULL
);

-- 广场上的发布物。owner_name 是发布时的昵称快照（作者改名不回填历史卡片）。
-- stars/clones/views/comments_count 是**计数缓存**：真相在明细表，
-- store 的 recount_* 可以随时重算回来。
CREATE TABLE IF NOT EXISTS published_strategies (
                publish_id       TEXT PRIMARY KEY,
                owner_user_id    TEXT NOT NULL,
                owner_name       TEXT NOT NULL DEFAULT '',
                slug          TEXT NOT NULL,
                title            TEXT NOT NULL,
                summary          TEXT NOT NULL DEFAULT '',
                kind             TEXT NOT NULL DEFAULT 'screen',
                entry_timing     TEXT NOT NULL,
                visibility       TEXT NOT NULL DEFAULT 'public'
                                CHECK (visibility IN ('public', 'unlisted', 'private')),
                status           TEXT NOT NULL DEFAULT 'listed'
                                CHECK (status IN ('listed', 'delisted')),
                current_version  INTEGER NOT NULL DEFAULT 1,
                tags_json        TEXT NOT NULL DEFAULT '[]',
                stars      INTEGER NOT NULL DEFAULT 0,
                clones           INTEGER NOT NULL DEFAULT 0,
                views  INTEGER NOT NULL DEFAULT 0,
                comments_count   INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                published_at     TEXT NOT NULL DEFAULT '',
                delisted_at      TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pub_owner_slug
                ON published_strategies(owner_user_id, slug);
CREATE INDEX IF NOT EXISTS idx_pub_square
                ON published_strategies(status, visibility, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_pub_owner
                ON published_strategies(owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pub_kind
                ON published_strategies(kind, status, visibility);

-- 冻结的版本快照。content_sha256 让克隆方可以核对「我拿到的确实是这一版」。
CREATE TABLE IF NOT EXISTS published_versions (
                id        TEXT PRIMARY KEY,
                publish_id      TEXT NOT NULL,
                version      INTEGER NOT NULL,
                source_text     TEXT NOT NULL DEFAULT '',
                params_json     TEXT NOT NULL DEFAULT '{}',
                manifest_json   TEXT NOT NULL DEFAULT '{}',
                release_notes   TEXT NOT NULL DEFAULT '',
                content_sha256  TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ver_publish_version
                ON published_versions(publish_id, version);
CREATE INDEX IF NOT EXISTS idx_ver_publish_created
                ON published_versions(publish_id, created_at DESC);

-- 上架即冻结：改写既有版本一律 ABORT，改内容请发新版。
CREATE TRIGGER IF NOT EXISTS trg_published_versions_frozen_update
BEFORE UPDATE ON published_versions
BEGIN
                SELECT RAISE(ABORT, 'published version is frozen: publish a new version instead');
END;

CREATE TRIGGER IF NOT EXISTS trg_published_versions_frozen_delete
BEFORE DELETE ON published_versions
BEGIN
                SELECT RAISE(ABORT, 'published version is frozen: delist instead of deleting');
END;

-- 绩效切片（派生、可重算）。score = sharpe_1y * min(1, live_days/365)，
-- 口径唯一实现在 domain/scoring.py::compute_score。
CREATE TABLE IF NOT EXISTS strategy_metrics (
                publish_id     TEXT NOT NULL,
                as_of_date     TEXT NOT NULL,
                sharpe_1y      REAL NOT NULL DEFAULT 0,
                annual_return  REAL NOT NULL DEFAULT 0,
                max_drawdown   REAL NOT NULL DEFAULT 0,
                win_rate       REAL NOT NULL DEFAULT 0,
                profit_factor  REAL NOT NULL DEFAULT 0,
                trades         INTEGER NOT NULL DEFAULT 0,
                live_days  INTEGER NOT NULL DEFAULT 0,
                oos_return     REAL NOT NULL DEFAULT 0,
                score     REAL NOT NULL DEFAULT 0,
                metrics_json   TEXT NOT NULL DEFAULT '{}',
                updated_at     TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (publish_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_metrics_date_score
                ON strategy_metrics(as_of_date, score DESC);

CREATE TABLE IF NOT EXISTS strategy_stars (
                publish_id  TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (publish_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_stars_user ON strategy_stars(user_id, created_at DESC);

-- 克隆留痕。社区**只发 bundle**，不代写对方的租户库，所以这里记的是
-- 「谁在什么时候拿走了哪一版」，不是「对方库里现在有什么」。
CREATE TABLE IF NOT EXISTS strategy_clones (
                id          TEXT PRIMARY KEY,
                publish_id  TEXT NOT NULL,
                version   INTEGER NOT NULL DEFAULT 1,
                user_id   TEXT NOT NULL,
                cloned_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clones_publish ON strategy_clones(publish_id, cloned_at DESC);
CREATE INDEX IF NOT EXISTS idx_clones_user ON strategy_clones(user_id, cloned_at DESC);

-- 评论。deleted_at 非空 = 软删（留占位行保住楼层与父子关系）。
CREATE TABLE IF NOT EXISTS strategy_comments (
                id          TEXT PRIMARY KEY,
                publish_id  TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                user_name   TEXT NOT NULL DEFAULT '',
                body        TEXT NOT NULL DEFAULT '',
                parent_id   TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                deleted_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_comments_publish ON strategy_comments(publish_id, created_at);
CREATE INDEX IF NOT EXISTS idx_comments_user ON strategy_comments(user_id, created_at DESC);

-- 跟单订阅。mode 的 CHECK 是**合规红线的物理兜底**：只推信号，不自动下单。
-- 谁想加 'auto_trade' 都得先改这行 DDL，改之前请先读 domain/models.py::Subscription。
CREATE TABLE IF NOT EXISTS subscriptions (
                publish_id       TEXT NOT NULL,
                user_id          TEXT NOT NULL,
                mode    TEXT NOT NULL DEFAULT 'signal_only'
                                CHECK (mode IN ('signal_only')),
                notify_channels  TEXT NOT NULL DEFAULT '[]',
                created_at       TEXT NOT NULL,
                paused_at        TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (publish_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id, created_at DESC);

-- 作者当日信号快照，订阅者来拉这个。一天一条，重发覆盖同一行。
CREATE TABLE IF NOT EXISTS signal_broadcasts (
                id           TEXT PRIMARY KEY,
                publish_id   TEXT NOT NULL,
                trade_date   TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at   TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_broadcast_publish_date
                ON signal_broadcasts(publish_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_broadcast_date ON signal_broadcasts(trade_date DESC);

CREATE TABLE IF NOT EXISTS follows (
                follower_id  TEXT NOT NULL,
                followee_id  TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                PRIMARY KEY (follower_id, followee_id)
);

CREATE INDEX IF NOT EXISTS idx_follows_followee ON follows(followee_id, created_at DESC);

-- 动态流。object_title 是写入时的标题快照，不回填。
CREATE TABLE IF NOT EXISTS activity_feed (
                id            TEXT PRIMARY KEY,
                actor_id      TEXT NOT NULL,
                actor_name    TEXT NOT NULL DEFAULT '',
                verb          TEXT NOT NULL,
                object_type   TEXT NOT NULL DEFAULT '',
                object_id     TEXT NOT NULL DEFAULT '',
                object_title  TEXT NOT NULL DEFAULT '',
                created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feed_created ON activity_feed(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_actor ON activity_feed(actor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_object ON activity_feed(object_type, object_id, created_at DESC);

-- 榜单快照（可重建）。存下来是为了「当天榜首是谁」可回看，
-- rebuild_leaderboard 会整段删掉同 (board, as_of_date) 再写。
CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
                board         TEXT NOT NULL,
                as_of_date    TEXT NOT NULL,
                rank       INTEGER NOT NULL,
                publish_id    TEXT NOT NULL,
                score         REAL NOT NULL DEFAULT 0,
                -- 本榜的排序键值（副榜是 sharpe / annual_return，主榜与 score 相同）。
                -- 落库是为了「当天为什么这么排」能直接回看，不必让前端从 metrics 里反推。
                sort_value    REAL NOT NULL DEFAULT 0,
                metrics_json  TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (board, as_of_date, rank)
);

CREATE INDEX IF NOT EXISTS idx_board_publish
                ON leaderboard_snapshots(publish_id, as_of_date DESC);
"""

#: 后续演进只准往这个列表尾部追加，且每条必须可重复执行。
#: （``apply_schema`` 吞掉 ``OperationalError``，所以 ADD COLUMN 重跑时报的
#: "duplicate column name" 是预期路径，不是错误——迁移因此天然幂等。）
_MIGRATIONS: list[str] = [
    # 老库的榜单快照没有排序键值，副榜（sharpe / return / rookie）的名次解释不了。
    "ALTER TABLE leaderboard_snapshots ADD COLUMN sort_value REAL NOT NULL DEFAULT 0",
]

#: 进程内「这个库文件已建表」的缓存，避免每次开连接都跑一遍 DDL。
_SCHEMA_READY: set[str] = set()


def apply_schema(conn: sqlite3.Connection) -> None:
    """建表 + 跑迁移。两段都幂等，可对已有库重复调用。"""
    conn.executescript(_SCHEMA)
    for statement in _MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            # 幂等迁移在已应用时会报 duplicate column 之类；这是预期路径。
            continue
    conn.commit()
