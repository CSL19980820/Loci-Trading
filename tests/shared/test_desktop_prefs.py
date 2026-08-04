from __future__ import annotations

from pathlib import Path

from src.shared.desktop_prefs import (
    DEFAULT_MINIMIZE_TO_TRAY,
    load_desktop_prefs,
    minimize_to_tray_enabled,
    save_desktop_prefs,
)


def test_default_minimize_to_tray_when_missing(tmp_path: Path) -> None:
    assert load_desktop_prefs(tmp_path)["minimize_to_tray"] is DEFAULT_MINIMIZE_TO_TRAY
    assert minimize_to_tray_enabled(tmp_path) is True


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    saved = save_desktop_prefs({"minimize_to_tray": False}, root=tmp_path)
    assert saved["minimize_to_tray"] is False
    assert load_desktop_prefs(tmp_path)["minimize_to_tray"] is False
    assert minimize_to_tray_enabled(tmp_path) is False

    save_desktop_prefs({"minimize_to_tray": True}, root=tmp_path)
    assert minimize_to_tray_enabled(tmp_path) is True


def test_peek_fields_persist_with_minimize(tmp_path: Path) -> None:
    save_desktop_prefs(
        {"minimize_to_tray": True, "peek_edge": "top", "peek_collapsed": False, "peek_y": 88},
        root=tmp_path,
    )
    prefs = load_desktop_prefs(tmp_path)
    assert prefs["peek_edge"] == "top"
    assert prefs["peek_collapsed"] is False
    assert prefs["peek_y"] == 88


def test_corrupt_file_falls_back_to_default(tmp_path: Path) -> None:
    path = tmp_path / "desktop.json"
    path.write_text("{not-json", encoding="utf-8")
    assert minimize_to_tray_enabled(tmp_path) is True
