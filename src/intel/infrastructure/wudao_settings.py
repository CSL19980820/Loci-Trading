"""悟道 MCP 常驻配置（loci.config.json → wudao_mcp）。

与 Cursor/Codex 一致：server 凭据在 data/mcp.json，配额与日 K 优先策略在本节。
"""
from __future__ import annotations

from typing import Any

from src.shared.paths import load_config, save_config

DEFAULT_QUOTA = {
    "daily_total": 5000,
    "daily_structured": 3000,
    "daily_skill": 2000,
    "per_minute": 50,
}


def wudao_config() -> dict[str, Any]:
    raw = load_config().get("wudao_mcp")
    return dict(raw) if isinstance(raw, dict) else {}


def wudao_quota_config() -> dict[str, int]:
    cfg = wudao_config()
    raw = cfg.get("quota") if isinstance(cfg.get("quota"), dict) else {}
    merged = {**DEFAULT_QUOTA, **{k: int(v) for k, v in raw.items() if k in DEFAULT_QUOTA}}
    daily = merged["daily_total"]
    if merged["daily_structured"] + merged["daily_skill"] > daily:
        merged["daily_skill"] = max(0, daily - merged["daily_structured"])
    return merged


def wudao_hist_daily_primary() -> bool:
    return bool(wudao_config().get("hist_daily_primary", False))


def save_wudao_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = wudao_config()
    merged = {**current, **updates}
    if "quota" in updates and isinstance(updates["quota"], dict):
        merged["quota"] = {
            **DEFAULT_QUOTA,
            **(current.get("quota") if isinstance(current.get("quota"), dict) else {}),
            **updates["quota"],
        }
    save_config({"wudao_mcp": merged})
    return merged


def public_wudao_settings() -> dict[str, Any]:
    cfg = wudao_config()
    quota = wudao_quota_config()
    return {
        "hist_daily_primary": bool(cfg.get("hist_daily_primary", False)),
        "note": str(cfg.get("note") or ""),
        "quota": quota,
    }
