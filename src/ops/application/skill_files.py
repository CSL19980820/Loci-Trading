"""技能目录换盘的文件系统原语。"""
from __future__ import annotations

from pathlib import Path
import shutil
import uuid


def atomic_replace_directory(source: Path, destination: Path) -> None:
    """用同盘 staging 替换目录，失败时恢复旧版本。"""
    backup: Path | None = None
    try:
        if destination.exists():
            backup = destination.parent / (
                f".skill-backup-{destination.name}-{uuid.uuid4().hex}"
            )
            destination.rename(backup)
        shutil.move(str(source), str(destination))
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup is not None and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    if backup is not None and backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
