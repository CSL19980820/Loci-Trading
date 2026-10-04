"""精确清理已退役创业板跳空修复候选；默认只读预览，不初始化或迁移账本。

用法：
  python scripts/retire_chinext_gap_repair_data.py --palace-db /explicit/path/palace.db
  python scripts/retire_chinext_gap_repair_data.py --palace-db /explicit/path/palace.db --apply

执行前以 SQLite backup 创建同目录 backups/ 全库一致性备份。候选以显式 slug
为准；仅在 slug 列缺失或值为 NULL / 空字符串时按精确旧展示名称回退匹配。
复盘只清理 entity_type=candidate 且关联匹配候选 ID 的行。
独立旧标签复盘和预案仅报告数量，供用户另行审阅；股票及其它战法记录保留。
回退时停止该账本的写入，再将报告中的完整备份恢复至原路径；不要只复制运行中
的数据库主文件或遗留旧 WAL。脚本不自动恢复，以免覆盖备份之后的正常新记录。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

RETIRED_SLUG = "chinext-gap-repair-v1"
EXACT_RULE_LABELS = (RETIRED_SLUG, "创业板跳空修复", "创业板跳空修复（15:30）")
TABLES = ("candidate_reviews", "reviews", "plans")


def _connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    mode = "rw" if writable else "ro"
    connection = sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=10,
                                 isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _candidate_filter(columns: set[str]) -> tuple[str, tuple[str, ...]]:
    clauses = []
    parameters = []
    if "strategy_slug" in columns:
        clauses.append("c.strategy_slug = ?")
        parameters.append(RETIRED_SLUG)
    if "rule_version" in columns:
        rule_clause = "c.rule_version IN (?, ?, ?)"
        if "strategy_slug" in columns:
            rule_clause = f"(COALESCE(c.strategy_slug, '') = '' AND {rule_clause})"
        clauses.append(rule_clause)
        parameters.extend(EXACT_RULE_LABELS)
    return ("(" + " OR ".join(clauses) + ")" if clauses else "0"), tuple(parameters)


def _snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    schema = {}
    warnings = []
    for table in TABLES:
        # 表名来自上方固定清单；PRAGMA 参数不是用户输入，也不推测不存在的列。
        schema[table] = [row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')]
        if not schema[table]:
            warnings.append(f"{table} 不存在，跳过该表")
    candidate_columns = set(schema["candidate_reviews"])
    where, parameters = _candidate_filter(candidate_columns)
    matched_candidates = 0
    can_apply = True
    if candidate_columns:
        if not {"strategy_slug", "rule_version"} & candidate_columns:
            warnings.append("candidate_reviews 缺少 strategy_slug / rule_version，无法精确判定")
            can_apply = False
        if "id" not in candidate_columns:
            warnings.append("candidate_reviews 缺少 id，无法核验关联复盘")
            can_apply = False
        matched_candidates = connection.execute(
            f"SELECT COUNT(*) FROM candidate_reviews AS c WHERE {where}", parameters,
        ).fetchone()[0]
    review_columns = set(schema["reviews"])
    can_link_reviews = bool(candidate_columns) and "id" in candidate_columns and {
        "entity_type", "entity_id",
    } <= review_columns
    linked_where = (
        "r.entity_type = ? AND EXISTS (SELECT 1 FROM candidate_reviews AS c "
        f"WHERE c.id = r.entity_id AND {where})"
    ) if can_link_reviews else "0"
    linked_parameters = ("candidate", *parameters) if can_link_reviews else ()
    linked_reviews = 0
    if can_link_reviews:
        linked_reviews = connection.execute(
            f"SELECT COUNT(*) FROM reviews AS r WHERE {linked_where}", linked_parameters,
        ).fetchone()[0]
    elif review_columns and matched_candidates:
        warnings.append("reviews 缺少 entity_type / entity_id，无法安全清理关联复盘")
        can_apply = False
    independent_reviews = 0
    if "strategy_tag" in review_columns:
        independent_reviews = connection.execute(
            "SELECT COUNT(*) FROM reviews AS r WHERE r.strategy_tag IN (?, ?, ?) "
            f"AND NOT ({linked_where})", (*EXACT_RULE_LABELS, *linked_parameters),
        ).fetchone()[0]
    elif review_columns:
        warnings.append("reviews 缺少 strategy_tag，无法统计独立旧标签复盘")
    tagged_plans = 0
    if "rule_version" in schema["plans"]:
        tagged_plans = connection.execute(
            "SELECT COUNT(*) FROM plans WHERE rule_version IN (?, ?, ?)", EXACT_RULE_LABELS,
        ).fetchone()[0]
    elif schema["plans"]:
        warnings.append("plans 缺少 rule_version，无法统计旧标签预案")
    return {
        "schema": schema,
        "match_labels": {
            "strategy_slug": RETIRED_SLUG, "rule_version": list(EXACT_RULE_LABELS),
            "rule_version_fallback": "strategy_slug 列不存在或值为 NULL / 空字符串",
        },
        "matched": {"candidate_reviews": matched_candidates, "linked_candidate_reviews": linked_reviews},
        "retained_for_review": {"plans": tagged_plans, "independent_reviews": independent_reviews},
        "can_apply": can_apply,
        "warnings": warnings,
    }


def _backup_locked_database(path: Path, expected: dict[str, Any]) -> Path:
    """调用方持有 BEGIN IMMEDIATE；另一只读连接备份，避免同连接写事务 backup 卡住。"""
    directory = path.parent / "backups"
    directory.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = directory / f"{path.stem}.before-retire-{RETIRED_SLUG}.{timestamp}.{uuid4().hex[:8]}.db"
    partial_path = backup_path.with_suffix(".db.partial")
    with partial_path.open("xb"):
        pass
    try:
        with closing(_connect(path, writable=False)) as source, closing(sqlite3.connect(partial_path)) as destination:
            source.backup(destination, pages=256)
            result = destination.execute("PRAGMA quick_check").fetchall()
            if result != [("ok",)]:
                raise RuntimeError(f"备份 quick_check 未通过: {result}")
            destination.row_factory = sqlite3.Row
            backup_snapshot = _snapshot(destination)
            if backup_snapshot["schema"] != expected["schema"] or backup_snapshot["matched"] != expected["matched"]:
                raise RuntimeError("备份结构或匹配数量与锁定的目标库不一致")
        partial_path.rename(backup_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return backup_path


def retire_data(palace_db: str | Path, *, apply: bool = False) -> dict[str, Any]:
    path = Path(palace_db).expanduser().resolve()
    report: dict[str, Any] = {
        "palace_db": str(path), "strategy_slug": RETIRED_SLUG,
        "mode": "apply" if apply else "dry-run", "status": "ok", "backup_path": None,
        "deleted": {"candidate_reviews": 0, "linked_candidate_reviews": 0},
    }
    if not path.is_file():
        return {**report, "status": "error", "error": "显式指定的 palace.db 不存在；未创建或修改数据库"}
    connection = None
    try:
        connection = _connect(path, writable=apply)
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        report.update(_snapshot(connection))
        if not apply:
            connection.rollback()
            return report
        if not report["can_apply"]:
            raise RuntimeError("结构核验未通过；未创建备份或删除数据，请查看 warnings")
        if not report["matched"]["candidate_reviews"]:
            connection.rollback()
            return report
        report["backup_path"] = str(_backup_locked_database(path, report))
        where, parameters = _candidate_filter(set(report["schema"]["candidate_reviews"]))
        linked_deleted = 0
        if report["schema"]["reviews"]:
            linked_deleted = connection.execute(
                "DELETE FROM reviews WHERE entity_type = ? AND entity_id IN "
                f"(SELECT c.id FROM candidate_reviews AS c WHERE {where})",
                ("candidate", *parameters),
            ).rowcount
        candidate_deleted = connection.execute(
            f"DELETE FROM candidate_reviews WHERE id IN (SELECT c.id FROM candidate_reviews AS c WHERE {where})",
            parameters,
        ).rowcount
        if (candidate_deleted, linked_deleted) != (
            report["matched"]["candidate_reviews"], report["matched"]["linked_candidate_reviews"],
        ):
            raise RuntimeError("删除数量与锁定事务中的预览不一致，已回滚")
        connection.commit()
        report["deleted"] = {"candidate_reviews": candidate_deleted, "linked_candidate_reviews": linked_deleted}
    except Exception as error:
        if connection is not None:
            connection.rollback()
        report.update(status="error", error=str(error))
    finally:
        if connection is not None:
            connection.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="精确退役创业板跳空修复候选；默认只读预览")
    parser.add_argument("--palace-db", type=Path, required=True, help="必须显式指定目标 palace.db")
    parser.add_argument("--apply", action="store_true", help="一致性备份后删除精确匹配的候选和关联候选复盘")
    args = parser.parse_args(argv)
    report = retire_data(args.palace_db, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
