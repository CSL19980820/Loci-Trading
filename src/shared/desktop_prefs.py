"""桌面壳偏好（可重建；不进业务库）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.shared.paths import data_dir

DEFAULT_MINIMIZE_TO_TRAY = True


def desktop_prefs_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "desktop.json"


_PEEK_EDGES = frozenset({"left", "right", "top", "bottom"})


def default_desktop_prefs() -> dict[str, Any]:
    return {
        "minimize_to_tray": DEFAULT_MINIMIZE_TO_TRAY,
        "peek_edge": "right",
        "peek_collapsed": True,
        "peek_y": None,
    }


def load_desktop_prefs(root: Path | None = None) -> dict[str, Any]:
    prefs = default_desktop_prefs()
    path = desktop_prefs_path(root)
    if not path.is_file():
        return prefs
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return prefs
    if not isinstance(raw, dict):
        return prefs
    if "minimize_to_tray" in raw:
        prefs["minimize_to_tray"] = bool(raw["minimize_to_tray"])
    edge = raw.get("peek_edge")
    if edge in _PEEK_EDGES:
        prefs["peek_edge"] = edge
    if "peek_collapsed" in raw:
        prefs["peek_collapsed"] = bool(raw["peek_collapsed"])
    if "peek_y" in raw:
        y = raw["peek_y"]
        prefs["peek_y"] = int(y) if isinstance(y, (int, float)) else None
    return prefs


def save_desktop_prefs(
    updates: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    prefs = load_desktop_prefs(root)
    if "minimize_to_tray" in updates:
        prefs["minimize_to_tray"] = bool(updates["minimize_to_tray"])
    if "peek_edge" in updates and updates["peek_edge"] in _PEEK_EDGES:
        prefs["peek_edge"] = updates["peek_edge"]
    if "peek_collapsed" in updates:
        prefs["peek_collapsed"] = bool(updates["peek_collapsed"])
    if "peek_y" in updates:
        y = updates["peek_y"]
        prefs["peek_y"] = int(y) if isinstance(y, (int, float)) else None
    path = desktop_prefs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(prefs, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return prefs


def minimize_to_tray_enabled(root: Path | None = None) -> bool:
    return bool(load_desktop_prefs(root).get("minimize_to_tray", DEFAULT_MINIMIZE_TO_TRAY))
