"""精确退役尾盘微右侧数据；默认只读，不初始化或迁移数据库。

必须显式指定租户 data 根，或同时指定 palace.db / ops.db。--apply 在两库
BEGIN IMMEDIATE 锁定后创建并核验 SQLite backup，再按精确归属删除。
停止相关 worker 后执行，防止旧任务重新写入；运行中的目标回执会阻止 apply。
恢复时停写并同时恢复报告中的两库备份，处理旧 WAL；WAL 多库提交不保证断电
原子性，因此必须保留成对备份。research_runs 仅报告，不删除任何外部文件。
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

RETIRED_SLUG = "tail-micro-right-v1"
EXACT_RULE_LABELS = (RETIRED_SLUG, "尾盘微右侧", "尾盘微右侧（15:30）")
MANAGED_NAME = "screen:" + RETIRED_SLUG
TABLES = {
    "main": ("candidate_reviews", "reviews", "plans", "ai_judgments"),
    "ops": ("jobs", "job_runs", "strategy_docs", "strategy_versions", "strategy_backtests", "meta", "research_jobs"),
}


def _canonical_strategy_slug(value: Any) -> str:
    """与运行时退役门禁一致；只移除一个已知前缀，不做包含匹配。"""
    key = str(value or "").strip().lower()
    for prefix in ("screen:", "skill:"):
        if key.startswith(prefix):
            return key[len(prefix):].strip()
    return key


def _connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"),
                           uri=True, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.create_function("canonical_strategy_slug", 1, _canonical_strategy_slug, deterministic=True)
    return conn


def _strategy_filter(columns: set[str], alias: str) -> tuple[str, tuple[str, ...]]:
    parts, params = [], []
    if "strategy_slug" in columns:
        parts.append(f"{alias}.strategy_slug = ?")
        params.append(RETIRED_SLUG)
    if "rule_version" in columns:
        rule = f"{alias}.rule_version IN (?, ?, ?)"
        if "strategy_slug" in columns:
            rule = f"(COALESCE({alias}.strategy_slug, '') = '' AND {rule})"
        parts.append(rule)
        params.extend(EXACT_RULE_LABELS)
    return "(" + " OR ".join(parts) + ")" if parts else "0", tuple(params)


def _json_strategy(column: str, *, request: bool = False) -> str:
    paths = ("$.request.strategy", "$.request.strategy_slug") if request else ("$.strategy", "$.strategy_slug")
    values = ", ".join(f"NULLIF(canonical_strategy_slug(json_extract({column}, '{path}')), '')" for path in paths)
    return f"CASE WHEN json_valid({column}) THEN COALESCE({values}, '') ELSE '' END"


def _snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    schema = {db: {table: {str(row["name"]) for row in conn.execute(f'PRAGMA {db}.table_info("{table}")')}
                   for table in tables} for db, tables in TABLES.items()}
    warnings, plans, can_apply = [], [], True

    def require(db, table, columns):
        nonlocal can_apply
        if not schema[db][table]:
            warnings.append(f"{db}.{table} 不存在，跳过")
            return False
        if not set(columns) <= schema[db][table]:
            warnings.append(f"{db}.{table} 缺少精确归属字段 {sorted(set(columns) - schema[db][table])}")
            can_apply = False
            return False
        return True

    def add(db, table, where, params=(), label=None):
        plans.append((db, table, where, tuple(params), label or table))

    candidate_where, candidate_params = _strategy_filter(schema["main"]["candidate_reviews"], "c")
    candidate_ok = require("main", "candidate_reviews", ("id",))
    if candidate_ok and candidate_where == "0":
        warnings.append("candidate_reviews 缺少 strategy_slug / rule_version，无法精确判定")
        can_apply = False
    plan_ok = require("main", "plans", ("id", "rule_version"))
    # 预案仅删除明确 slug；旧展示名称只报告，避免误删人工引用的旧标签。
    plan_where, plan_params = "p.rule_version = ?", (RETIRED_SLUG,)
    if "strategy_slug" in schema["main"]["plans"]:
        plan_where = "(p.strategy_slug = ? OR (COALESCE(p.strategy_slug, '') = '' AND p.rule_version = ?))"
        plan_params = (RETIRED_SLUG, RETIRED_SLUG)
    if require("main", "reviews", ("entity_type", "entity_id", "strategy_tag")):
        linked, linked_params, protection = [], [], []
        if candidate_ok:
            linked.append("r.entity_type = 'candidate' AND EXISTS (SELECT 1 FROM main.candidate_reviews c "
                          f"WHERE c.id = r.entity_id AND {candidate_where})")
            linked_params.extend(candidate_params)
            protection.append("NOT (r.entity_type = 'candidate' AND EXISTS (SELECT 1 FROM main.candidate_reviews c "
                              f"WHERE c.id = r.entity_id AND NOT {candidate_where}))")
        if plan_ok:
            linked.append("r.entity_type = 'plan' AND EXISTS (SELECT 1 FROM main.plans p "
                          f"WHERE p.id = r.entity_id AND {plan_where})")
            linked_params.extend(plan_params)
            protection.append("NOT (r.entity_type = 'plan' AND EXISTS (SELECT 1 FROM main.plans p "
                              f"WHERE p.id = r.entity_id AND NOT {plan_where}))")
        standalone = "r.strategy_tag = ?" + (" AND " + " AND ".join(protection) if protection else "")
        protection_params = (*(candidate_params if candidate_ok else ()), *(plan_params if plan_ok else ()))
        add("main", "reviews", "(" + " OR ".join([*("(" + item + ")" for item in linked),
                                                     "(" + standalone + ")"]) + ")",
            (*linked_params, RETIRED_SLUG, *protection_params))
    if candidate_ok:
        add("main", "candidate_reviews", candidate_where, candidate_params)
    if plan_ok:
        add("main", "plans", plan_where, plan_params)
    if require("main", "ai_judgments", ("strategy_tag",)):
        add("main", "ai_judgments", "x.strategy_tag = ?", (RETIRED_SLUG,))

    job_ids = []
    jobs_ok = require("ops", "jobs", ("id", "name", "kind", "config_json"))
    if jobs_ok:
        for row in conn.execute("SELECT id, name, kind, config_json FROM ops.jobs WHERE kind='screen'"):
            try:
                config = json.loads(str(row["config_json"] or "{}"))
            except json.JSONDecodeError:
                if row["name"] == MANAGED_NAME:
                    warnings.append(f"托管任务 {row['id']} 的 config_json 无效，须先核验")
                    can_apply = False
                continue
            strategy = (_canonical_strategy_slug(config.get("strategy"))
                        or _canonical_strategy_slug(config.get("strategy_slug"))) if isinstance(config, dict) else ""
            if strategy == RETIRED_SLUG or (not strategy and row["name"] == MANAGED_NAME):
                job_ids.append(str(row["id"]))
    id_where = "j.id IN (" + ",".join("?" for _ in job_ids) + ")" if job_ids else "0"
    run_where, run_params = "0", ()
    if require("ops", "job_runs", ("job_id", "job_name", "kind", "result_json", "status")):
        value = _json_strategy("r.result_json")
        fallback = "(r.kind = 'screen' AND r.job_name = ?"
        fallback_params = (MANAGED_NAME,)
        if jobs_ok:
            owner = _json_strategy("j.config_json")
            fallback += (" AND NOT EXISTS (SELECT 1 FROM ops.jobs j WHERE j.id=r.job_id AND j.kind='screen' "
                         f"AND {owner} <> '' AND {owner} <> ?)")
            fallback_params += (RETIRED_SLUG,)
        fallback += ")"
        if job_ids:
            fallback = "(" + fallback + " OR r.job_id IN (" + ",".join("?" for _ in job_ids) + "))"
            fallback_params += tuple(job_ids)
        run_where = f"({value} = ? OR ({value} = '' AND {fallback}))"
        run_params = (RETIRED_SLUG, *fallback_params)
        add("ops", "job_runs", run_where, run_params)
    if jobs_ok:
        add("ops", "jobs", id_where, job_ids)
    for table in ("strategy_docs", "strategy_versions", "strategy_backtests"):
        if require("ops", table, ("slug",)):
            add("ops", table, "x.slug = ?", (RETIRED_SLUG,))
    if require("ops", "meta", ("key",)):
        add("ops", "meta", "x.key = ?", ("screen_job_opt_out:" + RETIRED_SLUG,))
    if require("ops", "research_jobs", ("namespace", "id", "payload")):
        add("ops", "research_jobs", _json_strategy("x.payload", request=True) + " = ?", (RETIRED_SLUG,))
    aliases = {"candidate_reviews": "c", "reviews": "r", "plans": "p", "jobs": "j", "job_runs": "r"}
    matched = {label: int(conn.execute(f"SELECT COUNT(*) FROM {db}.{table} {aliases.get(table, 'x')} WHERE {where}",
                                      params).fetchone()[0]) for db, table, where, params, label in plans}
    active_runs = int(conn.execute("SELECT COUNT(*) FROM ops.job_runs r WHERE " + run_where
                                  + " AND r.status IN ('running','queued')", run_params).fetchone()[0]) if run_where != "0" else 0
    if active_runs:
        warnings.append(f"目标策略仍有 {active_runs} 条 running/queued 回执；先停止相关执行者再 apply")
        can_apply = False
    tagged_plans = int(conn.execute("SELECT COUNT(*) FROM main.plans WHERE rule_version IN (?,?)",
                                   EXACT_RULE_LABELS[1:]).fetchone()[0]) if plan_ok else 0
    review_plan = next((plan for plan in plans if plan[1] == "reviews"), None)
    tagged_reviews = int(conn.execute(
        "SELECT COUNT(*) FROM main.reviews r WHERE r.strategy_tag IN (?,?) AND NOT (" + review_plan[2] + ")",
        (*EXACT_RULE_LABELS[1:], *review_plan[3]),
    ).fetchone()[0]) if review_plan else 0
    return {"schema": {db: {table: sorted(cols) for table, cols in tables.items()} for db, tables in schema.items()},
            "matched": matched, "job_ids": job_ids, "active_target_runs": active_runs,
            "retained_for_review": {"legacy_label_plans": tagged_plans, "independent_label_reviews": tagged_reviews},
            "can_apply": can_apply, "warnings": warnings, "_delete_plans": plans}


def _signature(conn: sqlite3.Connection, db: str) -> dict[str, Any]:
    names = [str(row[0]) for row in conn.execute(f"SELECT name FROM {db}.sqlite_schema WHERE type='table' ORDER BY name")]
    return {name: {"schema": [tuple(row) for row in conn.execute(f'PRAGMA {db}.table_info("{name.replace(chr(34), chr(34)*2)}")')],
                   "rows": int(conn.execute(f'SELECT COUNT(*) FROM {db}."{name.replace(chr(34), chr(34)*2)}"').fetchone()[0])}
            for name in names}


def _backup_locked_database(path: Path, expected: dict[str, Any]) -> Path:
    directory = path.parent / "backups"
    directory.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{path.stem}.before-retire-{RETIRED_SLUG}.{stamp}.{uuid4().hex[:8]}.db"
    partial = target.with_suffix(".db.partial")
    with partial.open("xb"):
        pass
    try:
        partial.chmod(0o600)
        with closing(_connect(path, writable=False)) as source, closing(sqlite3.connect(partial)) as destination:
            source.backup(destination, pages=256)
            if destination.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("一致性备份 quick_check 未通过")
            if _signature(destination, "main") != expected:
                raise RuntimeError("一致性备份结构/全表数量与锁定数据库不一致")
        partial.rename(target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return target


def _external_references(root: Path | None) -> dict[str, Any]:
    report = {"root": str(root) if root else None, "exists": bool(root and root.is_dir()),
              "matched_manifests": [], "named_directories": [], "legacy_research_job_ids": [],
              "unreadable_manifests": [], "action": "report_only_no_file_deletion"}
    if not report["exists"]:
        return report
    report["named_directories"] = [str(path) for path in root.iterdir() if path.is_dir()
                                   and ("tail_micro_right" in path.name or RETIRED_SLUG in path.name)]
    for name in ("run_card.json", "card.json", "run.json"):
        for path in root.glob("*/" + name):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report["unreadable_manifests"].append(str(path))
                continue
            if isinstance(payload, dict) and (_canonical_strategy_slug(payload.get("strategy_slug")) == RETIRED_SLUG
                                              or _canonical_strategy_slug(payload.get("strategy")) == RETIRED_SLUG):
                report["matched_manifests"].append(str(path))
    legacy_jobs = root / "backtest_jobs.json"
    if legacy_jobs.is_file():
        try:
            payload = json.loads(legacy_jobs.read_text(encoding="utf-8"))
            jobs = payload.get("jobs", {}) if isinstance(payload, dict) else {}
            if isinstance(jobs, dict):
                for job_id, job in jobs.items():
                    request = job.get("request", {}) if isinstance(job, dict) else {}
                    if isinstance(request, dict) and (_canonical_strategy_slug(request.get("strategy"))
                                                     or _canonical_strategy_slug(request.get("strategy_slug"))) == RETIRED_SLUG:
                        report["legacy_research_job_ids"].append(str(job_id))
        except (OSError, json.JSONDecodeError):
            report["unreadable_manifests"].append(str(legacy_jobs))
    return report


def retire_data(
    *, data_root: str | Path | None = None, palace_db: str | Path | None = None,
    ops_db: str | Path | None = None, research_root: str | Path | None = None, apply: bool = False,
) -> dict[str, Any]:
    if data_root is not None:
        if palace_db is not None or ops_db is not None:
            raise ValueError("data_root 与显式数据库路径不能混用")
        root = Path(data_root).expanduser().resolve()
        palace_db, ops_db = root / "palace.db", root / "ops.db"
    elif palace_db is None or ops_db is None:
        raise ValueError("必须显式指定租户 data_root 或同时指定 palace_db / ops_db")
    palace, ops = Path(palace_db).expanduser().resolve(), Path(ops_db).expanduser().resolve()
    external = Path(research_root).expanduser().resolve() if research_root else (
        palace.parent / "research_runs" if palace.parent == ops.parent else None)
    report = {"strategy_slug": RETIRED_SLUG, "palace_db": str(palace), "ops_db": str(ops),
              "mode": "apply" if apply else "dry-run", "status": "ok", "backups": {}, "deleted": {},
              "external_research_runs": _external_references(external)}
    if palace == ops or not palace.is_file() or not ops.is_file():
        return {**report, "status": "error", "error": "必须指定两个不同且已存在的数据库；未创建或修改数据库"}
    conn = None
    try:
        conn = _connect(palace, writable=apply)
        conn.execute("ATTACH DATABASE ? AS ops", (ops.as_uri() + ("?mode=rw" if apply else "?mode=ro"),))
        if not apply:
            conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        snapshot = _snapshot(conn)
        delete_plans = snapshot.pop("_delete_plans")
        report.update(snapshot)
        report["deleted"] = dict.fromkeys(snapshot["matched"], 0)
        if not apply:
            conn.rollback()
            return report
        if not snapshot["can_apply"]:
            raise RuntimeError("结构/运行状态核验未通过；未删除数据，请查看 warnings")
        if not any(snapshot["matched"].values()):
            conn.rollback()
            return report
        for alias, path in (("main", palace), ("ops", ops)):
            report["backups"][alias] = str(_backup_locked_database(path, _signature(conn, alias)))
        aliases = {"candidate_reviews": "c", "reviews": "r", "plans": "p", "jobs": "j", "job_runs": "r"}
        deleted = {}
        for alias, table, where, params, label in delete_plans:
            deleted[label] = conn.execute(f"DELETE FROM {alias}.{table} AS {aliases.get(table, 'x')} WHERE {where}",
                                          params).rowcount
        if deleted != report["matched"]:
            raise RuntimeError("实际删除数量与锁定预览不一致，已回滚")
        remaining = _snapshot(conn)
        if any(remaining["matched"].values()):
            raise RuntimeError("退役记录回读仍有残留，已回滚")
        conn.commit()
        report["deleted"] = deleted
    except Exception as error:
        if conn is not None:
            conn.rollback()
        report.update(status="error", error=str(error))
    finally:
        if conn is not None:
            conn.close()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="精确退役尾盘微右侧；默认只读预览")
    parser.add_argument("--data-root", type=Path, help="显式租户数据目录（包含 palace.db / ops.db）")
    parser.add_argument("--palace-db", type=Path)
    parser.add_argument("--ops-db", type=Path)
    parser.add_argument("--research-root", type=Path, help="仅报告研究文件，不删除")
    parser.add_argument("--apply", action="store_true", help="停写执行者后，一致性备份并清理精确归属记录")
    args = parser.parse_args(argv)
    if (args.data_root and (args.palace_db or args.ops_db)) or (not args.data_root and not (args.palace_db and args.ops_db)):
        parser.error("必须指定 --data-root，或同时指定 --palace-db / --ops-db；两种形式不能混用")
    report = retire_data(data_root=args.data_root, palace_db=args.palace_db, ops_db=args.ops_db,
                         research_root=args.research_root, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
