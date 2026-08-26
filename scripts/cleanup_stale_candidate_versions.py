"""清理已归档战法版本留下的重复精选（palace.db）。

现行托管选股：qianlong-close-v3 / sanyuan-tail-v1 / yangshi-tail-v1。
两类清理，都不动现行战法行：

1. **归档对照版**（rsi30-dip、qianlong-tail-v1、qianlong-close、lugw-sanwai* 等）：
   战法还在 `application/backup/`，只删它们刷出来的**重复精选**，观察/落选留痕保留。
2. **已删除战法**（`DELETED_1450_SLUGS`：14:50 三源 / 杨氏 / 潜伏）：战法代码与定时任务
   已整体从仓库移除，`candidate_reviews` 与 `position_tracking` 里**不分 decision 全清**——
   留着任何一行都会继续出现在选股历史 / 近选跟踪，而且再也无法重跑复现。

用法：
  .\\.venv\\Scripts\\python.exe scripts/cleanup_stale_candidate_versions.py
  .\\.venv\\Scripts\\python.exe scripts/cleanup_stale_candidate_versions.py --apply
  .\\.venv\\Scripts\\python.exe scripts/cleanup_stale_candidate_versions.py --db PATH --apply
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

# 已从活动目录/托管任务撤下的对照版（见 application/backup/*-legacy.py）
ARCHIVED_STRATEGY_SLUGS: frozenset[str] = frozenset(
    {
        "qianlong-close",
        "qianlong-close-v2",
        "qianlong-tail-v1",
        "qianfu-close",
        "rsi30-dip",
        "lugw-sanwai",
        "lugw-sanwai-v2",
        "lugw-chouma",
        "lugw-haidi",
    }
)

EMPTY_SLUG_SOURCES: frozenset[str] = frozenset(
    {
        "qianlong-skill",
        "skill-sync",
    }
)


#: 14:50 两档（三源 / 杨氏）与早已删除的潜伏 14:50 档：连战法代码带定时任务一起从仓库移除。
#: 它们不是「归档对照版」（那些只删重复精选），而是已不存在的战法：
#: 留着任何一行都会在选股历史 / 近选跟踪里继续出现，且再也无法重跑复现。
DELETED_1450_SLUGS: frozenset[str] = frozenset(
    {
        "sanyuan-tail-1450",
        "yangshi-tail-1450",
        "qianfu-1450",
    }
)


def _slug_filter(column: str, slugs: list[str]) -> tuple[str, list[str]]:
    """只认 slug 列；只有 slug 空的早期行才回落到 ``{slug}@日期`` 的 pool_id。

    不能光按 pool_id 前缀删：同一批次里可能混着别的战法的行，
    那些行有自己的 slug，不属于本次要清的战法。
    """
    placeholders = ",".join("?" * len(slugs))
    likes = " OR ".join(["pool_id LIKE ?"] * len(slugs))
    clause = (
        f"({column} IN ({placeholders})"
        f" OR (IFNULL({column}, '') = '' AND ({likes})))"
    )
    return clause, [*slugs, *(f"{slug}@%" for slug in slugs)]


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    """palace 表结构会随功能下线变（如持仓跟踪）；表没了不算错，当作没残留。"""
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


#: (表, slug 列, 预览列, 排序)。表可能随功能下线消失，逐张探存在性。
_PURGE_TARGETS: tuple[tuple[str, str, str, str], ...] = (
    (
        "candidate_reviews",
        "strategy_slug",
        "id, occurred_on, code, name, strategy_slug, decision, pool_id",
        "occurred_on DESC, code",
    ),
    (
        "position_tracking",
        "strategy_tag",
        "id, signal_date, code, name, strategy_tag, status, pool_id",
        "signal_date DESC, code",
    ),
)


def preview_deleted_strategies(con: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    """列出已删除战法在 palace 里残留的全部行（不分精选 / 观察 / 落选）。"""
    slugs = sorted(DELETED_1450_SLUGS)
    out: dict[str, list[sqlite3.Row]] = {}
    for table, column, columns, order in _PURGE_TARGETS:
        if not _table_exists(con, table):
            continue
        where, args = _slug_filter(column, slugs)
        out[table] = list(
            con.execute(
                f"SELECT {columns} FROM {table} WHERE {where} ORDER BY {order}",
                args,
            )
        )
    return out


def delete_deleted_strategies(con: sqlite3.Connection) -> dict[str, int]:
    """战法已不存在，它的候选与跟踪行也不能再出现在界面上。"""
    slugs = sorted(DELETED_1450_SLUGS)
    deleted: dict[str, int] = {}
    for table, column, _columns, _order in _PURGE_TARGETS:
        if not _table_exists(con, table):
            continue
        where, args = _slug_filter(column, slugs)
        cur = con.execute(f"DELETE FROM {table} WHERE {where}", args)
        deleted[table] = int(cur.rowcount)
    return deleted

def default_db() -> Path:
    portable = Path(r"E:\entertainment_software\Loci\data\palace.db")
    if portable.is_file():
        return portable
    from src.shared.paths import palace_db

    return Path(palace_db())


def preview(con: sqlite3.Connection) -> list[sqlite3.Row]:
    placeholders = ",".join("?" * len(ARCHIVED_STRATEGY_SLUGS))
    source_ph = ",".join("?" * len(EMPTY_SLUG_SOURCES))
    return list(
        con.execute(
            f"""
            SELECT id, occurred_on, code, name, strategy_slug, pool_id, source, decision
            FROM candidate_reviews
            WHERE decision = '精选'
              AND (
                strategy_slug IN ({placeholders})
                OR (
                  IFNULL(strategy_slug, '') = ''
                  AND IFNULL(source, '') IN ({source_ph})
                )
              )
            ORDER BY occurred_on DESC, code, strategy_slug
            """,
            (*sorted(ARCHIVED_STRATEGY_SLUGS), *sorted(EMPTY_SLUG_SOURCES)),
        )
    )


def apply_delete(con: sqlite3.Connection) -> int:
    placeholders = ",".join("?" * len(ARCHIVED_STRATEGY_SLUGS))
    source_ph = ",".join("?" * len(EMPTY_SLUG_SOURCES))
    cur = con.execute(
        f"""
        DELETE FROM candidate_reviews
        WHERE decision = '精选'
          AND (
            strategy_slug IN ({placeholders})
            OR (
              IFNULL(strategy_slug, '') = ''
              AND IFNULL(source, '') IN ({source_ph})
            )
          )
        """,
        (*sorted(ARCHIVED_STRATEGY_SLUGS), *sorted(EMPTY_SLUG_SOURCES)),
    )
    return int(cur.rowcount)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清理归档战法重复精选 + 清除已删除战法（14:50 两档）残留")
    parser.add_argument("--db", type=Path, default=None, help="palace.db 路径")
    parser.add_argument("--apply", action="store_true", help="真正删除；默认只预览")
    parser.add_argument(
        "--scope",
        choices=("all", "archived", "deleted"),
        default="all",
        help="archived=只删归档对照版重复精选；deleted=只清已删除战法（默认两者都做）",
    )
    args = parser.parse_args(argv)
    db = args.db or default_db()
    if not db.is_file():
        raise SystemExit(f"找不到 palace.db: {db}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    print(f"db={db} scope={args.scope}")
    do_archived = args.scope in ("all", "archived")
    do_deleted = args.scope in ("all", "deleted")
    if do_archived:
        rows = preview(con)
        print(f"will_delete={len(rows)} archived/empty-slug 精选")
        for row in rows[:40]:
            print(dict(row))
        if len(rows) > 40:
            print(f"... and {len(rows) - 40} more")
    if do_deleted:
        doomed = preview_deleted_strategies(con)
        for table, table_rows in doomed.items():
            print(f"will_purge {table}={len(table_rows)} (已删除战法，不分 decision)")
            for row in table_rows[:40]:
                print(dict(row))

    if not args.apply:
        print("dry-run only; pass --apply to delete")
        return 0

    if do_archived:
        print(f"deleted={apply_delete(con)}")
    if do_deleted:
        print(f"purged_deleted_strategies={delete_deleted_strategies(con)}")
    con.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
