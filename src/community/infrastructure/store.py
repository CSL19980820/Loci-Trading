"""社区库：策略广场、排行榜、跟单订阅、互动与动态流。

物理隔离于 ``palace.db`` / ``market.db`` / ``ops.db``；路径来自
``src.shared.paths.community_db()``（跨租户全局唯一——广场是公共空间，
不能跟着租户切换分裂成几份互相看不见的榜单）。

实现拆分（每个文件都 <= 600 行，学 ``ops`` 的 mixin 组合）：

- ``schema`` — DDL、迁移与「上架即冻结」触发器
- ``store_helpers``     — ID / JSON / sha256 / slug / 分页
- ``store_publish`` — published_strategies + published_versions
- ``store_discovery``      — 广场检索（排序白名单 + 筛选 + 分页）
- ``store_social``         — 收藏 / 克隆留痕 / 评论 / 关注 / 动态流
- ``store_subscriptions``  — 跟单订阅 + 当日信号广播
- ``store_metrics``        — 绩效切片 + 榜单快照
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from src.community.domain.models import now_iso
from src.community.infrastructure.schema import (
    SCHEMA_VERSION,
    _SCHEMA_READY,
    apply_schema,
)
from src.community.infrastructure.store_discovery import CommunityDiscoveryMixin
from src.community.infrastructure.store_metrics import CommunityMetricsMixin
from src.community.infrastructure.store_publish import CommunityPublishMixin
from src.community.infrastructure.store_social import CommunitySocialMixin
from src.community.infrastructure.store_subscriptions import CommunitySubscriptionMixin

__all__ = ["CommunityStore", "SCHEMA_VERSION", "default_db"]


def default_db() -> Path:
    """默认库路径。**每次调用现取**，不在导入时固化。

    测试与首次向导会改 ``LOCI_DATA_DIR`` / ``LOCI_COMMUNITY_DB``；导入时求值会让
    整个进程钉死在最先导入时的那个目录上（ops 的 ``DEFAULT_DB`` 就吃过这个亏）。
    """
    from src.shared.paths import community_db

    return community_db()


class CommunityStore(
    CommunityPublishMixin,
    CommunityDiscoveryMixin,
    CommunitySocialMixin,
    CommunitySubscriptionMixin,
    CommunityMetricsMixin,
):
    """社区库门面。每个请求 / 任务持有独立连接，用完 ``close()``。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path or default_db())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            key = str(self.db_path.resolve())
            if key not in _SCHEMA_READY:
                self.init_schema()
                _SCHEMA_READY.add(key)
        except Exception:
            self.conn.close()
            raise

    def init_schema(self) -> None:
        apply_schema(self.conn)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at) VALUES('schema_version', ?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (str(SCHEMA_VERSION), self._now()),
            )

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> CommunityStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _now(self) -> str:
        """本库统一时钟（真身在 ``domain.models.now_iso``）。"""
        return now_iso()

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Cursor]:
        """一个写事务。``immediate=True`` 用于「先读后写」的自增场景（版本号、计数）。"""
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def stats(self) -> dict[str, int]:
        """库体检：各表行数。运维页与测试都用它确认「东西真的写进去了」。"""
        tables = (
            "published_strategies",
            "published_versions",
            "strategy_metrics",
            "strategy_stars",
            "strategy_clones",
            "strategy_comments",
            "subscriptions",
            "signal_broadcasts",
            "follows",
            "activity_feed",
            "leaderboard_snapshots",
        )
        out: dict[str, int] = dict()
        for table in tables:
            row = self.conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            out[table] = int(row["n"]) if row else 0
        return out
