from __future__ import annotations

from pathlib import Path

from src.shared import paths


def _clear_data_env(monkeypatch) -> None:
    monkeypatch.delenv("LOCI_DATA_DIR", raising=False)
    monkeypatch.delenv("PALACE_DATA_DIR", raising=False)


def test_relative_config_data_dir_is_anchored_to_install_root(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "Loci"
    monkeypatch.setattr(paths, "writable_root", lambda: install)
    monkeypatch.setattr(paths, "load_config", lambda: {"data_dir": "data"})
    _clear_data_env(monkeypatch)

    assert paths.data_dir() == (install / "data").resolve()


def test_stale_absolute_config_falls_back_to_packaged_data(
    tmp_path: Path, monkeypatch
) -> None:
    install = tmp_path / "Loci"
    packaged_data = install / "data"
    (packaged_data / "market.db").parent.mkdir(parents=True)
    (packaged_data / "market.db").write_bytes(b"complete")
    old_data = tmp_path / "old-machine" / "data"
    old_data.mkdir(parents=True)

    monkeypatch.setattr(paths, "writable_root", lambda: install)
    monkeypatch.setattr(paths, "MARKET_POPULATED_BYTES", 1)
    monkeypatch.setattr(paths, "load_config", lambda: {"data_dir": str(old_data)})
    _clear_data_env(monkeypatch)

    assert paths.data_dir() == packaged_data.resolve()


def test_existing_configured_data_still_wins_over_packaged_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    install = tmp_path / "Loci"
    packaged_data = install / "data"
    configured_data = tmp_path / "external-data"
    (packaged_data / "market.db").parent.mkdir(parents=True)
    (configured_data / "market.db").parent.mkdir(parents=True)
    (packaged_data / "market.db").write_bytes(b"packaged")
    (configured_data / "market.db").write_bytes(b"configured")

    monkeypatch.setattr(paths, "writable_root", lambda: install)
    monkeypatch.setattr(paths, "MARKET_POPULATED_BYTES", 1)
    monkeypatch.setattr(paths, "load_config", lambda: {"data_dir": str(configured_data)})
    _clear_data_env(monkeypatch)

    assert paths.data_dir() == configured_data.resolve()


def test_apply_data_dir_stores_install_relative_path(tmp_path: Path, monkeypatch) -> None:
    install = tmp_path / "Loci"
    saved: dict[str, object] = {}
    monkeypatch.setattr(paths, "writable_root", lambda: install)
    monkeypatch.setattr(paths, "save_config", lambda updates: saved.update(updates) or updates)

    resolved = paths.apply_data_dir(install / "data", mark_setup_done=False)

    assert resolved == (install / "data").resolve()
    assert saved["data_dir"] == "data"
