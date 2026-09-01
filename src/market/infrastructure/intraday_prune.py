"""盘中留存带的过期删除。

删目录这件事必须比它看起来更偏执：一个拼错的根路径 + 一个 ``rmtree`` 就能清掉用户
的账本。所以这里有**三道闸门**，任何一道不过就整批拒绝而不是「跳过这一条继续」：

1. **根必须是 ``<data_dir>/intraday``**，且解析后仍在 ``data_dir`` 之内（挡 ``..``
   与符号链接逃逸）。
2. **只删名字严格匹配 ``YYYY-MM-DD`` 的目录**，且该名字能被 ``date.fromisoformat``
   解析。任何别的东西（``.dek``、``logs``、``..``）一律不碰。
3. **单次删除数量上限**。正常一天只该淘汰一天；一次要删几十个说明保留天数被误配或
   路径指错了，此时停下来报错比删干净更有用。

保留窗口按**自然日**算而不是交易日：留存带里本来就只有交易日目录，用自然日不需要
交易日历，少一个依赖也少一处「日历没同步导致删错」的失败模式。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from src.market.infrastructure.intraday_archive import (
    DAY_DIR_PATTERN,
    intraday_root,
    list_days,
)

#: 默认保留 60 个自然日（ADR-014 的 30–60 天上沿）。
DEFAULT_RETENTION_DAYS = 60

#: 单次删除上限。超过即拒绝，逼调用方先看清楚。
MAX_DELETE_PER_RUN = 30


class IntradayPruneError(RuntimeError):
    """过期删除的安全闸门未通过。"""


@dataclass
class PruneReport:
    retention_days: int
    cutoff: str
    deleted: list[str] = field(default_factory=list)
    kept: int = 0
    freed_bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": "loci-intraday-prune-v1",
            "retention_days": int(self.retention_days),
            "cutoff": self.cutoff,
            "deleted": list(self.deleted),
            "deleted_count": len(self.deleted),
            "kept": int(self.kept),
            "freed_mb": round(self.freed_bytes / 1e6, 2),
        }


def _dir_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _guard_root(data_dir: Path, root: Path) -> None:
    """闸门 1：根必须就是 ``<data_dir>/intraday``，且在 data_dir 之内。"""
    expected = intraday_root(data_dir).resolve()
    actual = root.resolve()
    if actual != expected:
        raise IntradayPruneError(f"留存带根路径不对：{actual} != {expected}")
    try:
        actual.relative_to(Path(data_dir).resolve())
    except ValueError as exc:
        raise IntradayPruneError(f"留存带根逃出了数据目录：{actual}") from exc


def _expired_days(days: list[str], cutoff: date) -> list[str]:
    """闸门 2：只认严格 YYYY-MM-DD 且可解析的目录名。"""
    out = []
    for name in days:
        if not DAY_DIR_PATTERN.match(name):
            continue
        try:
            parsed = date.fromisoformat(name)
        except ValueError:
            continue
        if parsed < cutoff:
            out.append(name)
    return sorted(out)


def prune_intraday(
    data_dir: Path | str,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    today: date | None = None,
    max_delete: int = MAX_DELETE_PER_RUN,
    dry_run: bool = False,
) -> PruneReport:
    """删掉早于 ``today - retention_days`` 的整个交易日目录。

    ``dry_run=True`` 只报要删什么，不动盘——第一次配保留天数时应该先跑它。
    """
    if int(retention_days) < 1:
        raise IntradayPruneError(f"保留天数必须 ≥1：{retention_days}")
    base = Path(data_dir)
    root = intraday_root(base)
    anchor = today or date.today()
    cutoff = anchor - timedelta(days=int(retention_days))
    report = PruneReport(retention_days=int(retention_days), cutoff=cutoff.isoformat())
    if not root.exists():
        return report
    _guard_root(base, root)
    days = list_days(base)
    expired = _expired_days(days, cutoff)
    report.kept = len(days) - len(expired)
    if len(expired) > int(max_delete):
        raise IntradayPruneError(
            f"本次要删 {len(expired)} 天，超过单次上限 {max_delete}。"
            "这通常意味着保留天数配错了或路径指错了；确认无误后用更大的 max_delete 重跑。"
        )
    for name in expired:
        target = root / name
        size = _dir_bytes(target)
        if not dry_run:
            shutil.rmtree(target)
        report.deleted.append(name)
        report.freed_bytes += size
    return report


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "MAX_DELETE_PER_RUN",
    "IntradayPruneError",
    "PruneReport",
    "prune_intraday",
]
