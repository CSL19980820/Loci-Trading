"""租户私有目录的占用统计与 run 产物清理。

两件事放在一起，因为它们看的是同一批路径（``shared.tenancy.tenant_paths``）：

- ``tenant_storage_usage`` —— 该租户实际占了多少磁盘，**分项**返回。
  分项是必须的：只报一个总数，用户看到「你超了 2 GB」也不知道该删什么，
  运维看到也判断不出是对话历史涨了还是 run 产物涨了。
- ``prune_skill_runs`` / ``prune_research_runs`` —— 落在磁盘上的 run 产物，
  它们不在任何数据库里，只能按文件 mtime 截断。

**统计口径刻意只数五项**（``palace.db`` + ``ops.db`` + ``skills/`` +
``skill_runs/`` + ``research_runs/``），不是 ``du -s`` 整个目录。原因：主租户
的私有目录**就是 ``data/`` 本身**，里面还躺着全局共享的 ``market.db`` /
``market_hot.db``（GB 级）与 ``identity.db`` / ``community.db``。把它们算进
「这个用户占了多少」，主租户会永远显示超配额，而那些库根本不归他。

数据库文件按 ``x.db`` + ``x.db-wal`` + ``x.db-shm`` 三件套统计：WAL 在大批量
删除后可以涨到比主库还大，只数主库会让「清理前后体积」这组数字自相矛盾。
"""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from src.shared.paths import data_dir
from src.shared.tenancy import tenant_paths

#: 数据库文件的 WAL / SHM 边车后缀。
_DB_SIDECARS = ("", "-wal", "-shm")

#: 单次最多删多少个 run 产物。防御性上限：真有几十万个文件时，与其在凌晨
#: 把 IO 占满，不如分几晚删完，并让 payload 里的 ``truncated`` 说明还没删完。
DEFAULT_MAX_DELETE = 5000


def _db_bytes(path: Path) -> int:
    total = 0
    for suffix in _DB_SIDECARS:
        candidate = Path(str(path) + suffix)
        try:
            total += candidate.stat().st_size
        except OSError:
            continue
    return total


def _dir_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            # 扫描期间被别的进程删掉 / 权限不足：跳过一项，不要让整次统计失败。
            continue
    return total


def tenant_storage_usage(tenant_id: str | None = None) -> dict[str, Any]:
    """该租户私有目录的实际占用，分项 + 合计。

    返回 ``{"tenant_id", "root", "items": {...}, "bytes", "mb"}``。
    ``items`` 的键与 ``store_platform.DEFAULT_QUOTAS['storage_mb']`` 的注释
    一字对应，改这里就要同步改那边的口径说明。
    """
    paths = tenant_paths(data_dir(), tenant_id)
    items = {
        "palace_db": _db_bytes(paths.palace_db),
        "ops_db": _db_bytes(paths.ops_db),
        "skills": _dir_bytes(paths.skill_root),
        "skill_runs": _dir_bytes(paths.skill_runs_dir),
        "research_runs": _dir_bytes(paths.research_runs_dir),
    }
    total = sum(items.values())
    return {
        "tenant_id": paths.tenant_id,
        "root": str(paths.root),
        "items": items,
        "bytes": total,
        "mb": round(total / (1024 * 1024), 3),
    }


def _cutoff_epoch(keep_days: int, *, now: float | None = None) -> float:
    return (now if now is not None else time.time()) - max(0, int(keep_days)) * 86400.0


def _unlink(path: Path) -> int:
    """删一个文件，返回释放的字节数。删不掉就当没删（磁盘问题不该炸整轮）。"""
    try:
        size = path.stat().st_size
        path.unlink()
        return size
    except OSError:
        return 0


def prune_skill_runs(
    root: Path,
    *,
    keep_days: int,
    max_delete: int = DEFAULT_MAX_DELETE,
    now: float | None = None,
) -> dict[str, Any]:
    """按 mtime 清 ``skill_runs/SR-*.json`` 及其 ``.events.jsonl``。

    两个文件成对删：只删 json 会留下永远没人读的事件流（run 索引没了，
    ``list_events`` 根本不会去找它），只删事件流又会让详情页翻不出过程。
    """
    if int(keep_days) <= 0:
        return {"deleted": 0, "bytes": 0, "skipped": "未启用"}
    if not root.is_dir():
        return {"deleted": 0, "bytes": 0, "skipped": "目录不存在"}
    cutoff = _cutoff_epoch(keep_days, now=now)
    deleted = 0
    freed = 0
    truncated = False
    for state in sorted(root.glob("SR-*.json")):
        if deleted >= max_delete:
            truncated = True
            break
        events = root / f"{state.stem}.events.jsonl"
        try:
            newest = state.stat().st_mtime
            if events.is_file():
                newest = max(newest, events.stat().st_mtime)
        except OSError:
            continue
        if newest >= cutoff:
            continue
        freed += _unlink(state)
        if events.is_file():
            freed += _unlink(events)
        deleted += 1
    out: dict[str, Any] = {"deleted": deleted, "bytes": freed, "keep_days": int(keep_days)}
    if truncated:
        out["truncated"] = True
    return out


def prune_research_runs(
    root: Path,
    *,
    keep_days: int,
    max_delete: int = DEFAULT_MAX_DELETE,
    now: float | None = None,
) -> dict[str, Any]:
    """按 mtime 清 ``research_runs/RR-*/`` 整个目录。

    **只认 ``RR-*`` 目录**。同一层还躺着 ``hypotheses.json`` /
    ``backtest_jobs.json`` / ``point_in_time_facts.json`` /
    ``membership_snapshots.json`` / ``factor_jobs.json``——那些是长期状态存档，
    不是某次 run 的产物，按 mtime 删会把研究域的假设库和时点事实一起抹掉。
    """
    if int(keep_days) <= 0:
        return {"deleted": 0, "bytes": 0, "skipped": "未启用"}
    if not root.is_dir():
        return {"deleted": 0, "bytes": 0, "skipped": "目录不存在"}
    cutoff = _cutoff_epoch(keep_days, now=now)
    deleted = 0
    freed = 0
    truncated = False
    import shutil

    for run_dir in sorted(root.glob("RR-*")):
        if not run_dir.is_dir():
            continue
        if deleted >= max_delete:
            truncated = True
            break
        newest = 0.0
        size = 0
        try:
            newest = run_dir.stat().st_mtime
            for item in run_dir.rglob("*"):
                if not item.is_file():
                    continue
                stat = item.stat()
                newest = max(newest, stat.st_mtime)
                size += stat.st_size
        except OSError:
            continue
        if newest >= cutoff:
            continue
        shutil.rmtree(run_dir, ignore_errors=True)
        if run_dir.exists():
            continue
        freed += size
        deleted += 1
    out: dict[str, Any] = {"deleted": deleted, "bytes": freed, "keep_days": int(keep_days)}
    if truncated:
        out["truncated"] = True
    return out


__all__ = [
    "DEFAULT_MAX_DELETE",
    "prune_research_runs",
    "prune_skill_runs",
    "tenant_storage_usage",
]
