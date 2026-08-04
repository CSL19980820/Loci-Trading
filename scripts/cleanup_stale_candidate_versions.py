"""清理已归档战法版本留下的重复精选（palace.db）。

现行托管选股：qianlong-close-v3 / qianlong-tail-v1 / sanyuan-tail-v1 / rsi30-dip / lugw-haidi。
历史 job 或手工跑写入的归档 slug（qianlong-close、lugw-sanwai* 等）会在「近选跟踪」
同日同票刷出多行。本脚本只删归档 slug 与空 slug 技能残留，不动现行战法行。

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
        "lugw-sanwai",
        "lugw-sanwai-v2",
        "lugw-chouma",
        # lugw-haidi 仍在活动目录，勿删
    }
)

EMPTY_SLUG_SOURCES: frozenset[str] = frozenset(
    {
        "qianlong-skill",
        "skill-sync",
    }
)


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
    parser = argparse.ArgumentParser(description="清理归档战法重复精选")
    parser.add_argument("--db", type=Path, default=None, help="palace.db 路径")
    parser.add_argument("--apply", action="store_true", help="真正删除；默认只预览")
    args = parser.parse_args(argv)
    db = args.db or default_db()
    if not db.is_file():
        raise SystemExit(f"找不到 palace.db: {db}")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = preview(con)
    print(f"db={db}")
    print(f"will_delete={len(rows)} archived/empty-slug 精选")
    for row in rows[:40]:
        print(dict(row))
    if len(rows) > 40:
        print(f"... and {len(rows) - 40} more")

    if not args.apply:
        print("dry-run only; pass --apply to delete")
        return 0

    deleted = apply_delete(con)
    con.commit()
    print(f"deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
