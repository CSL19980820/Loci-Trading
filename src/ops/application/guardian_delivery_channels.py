"""Resolve stable guardian targets without persisting notification credentials."""
from __future__ import annotations

import json
from typing import Any

from src.ops.application.notify_dispatch import _EXTRA_CHANNELS, _resolve_channels
from src.ops.application.notify_registry import configured_channels


def default_targets(store: Any) -> dict[str, dict[str, str]]:
    targets = {}
    for channel in _resolve_channels(store, channel_ids=None):
        target = {"kind": "legacy", "id": str(channel.get("id")),
                  "type": str(channel.get("type") or "")}
        key = json.dumps([target["kind"], target["id"], target["type"]])
        if key in targets:
            raise ValueError("Duplicate notification channel ID")
        targets[key] = target
    for name in configured_channels(store):
        if name in _EXTRA_CHANNELS:
            targets[json.dumps(["registry", name])] = {
                "kind": "registry", "id": name, "type": name}
    return targets


class _RegistryTargetStore:
    """Read-only settings view: dispatch_text still owns silence and rate gates."""

    def __init__(self, store: Any, name: str) -> None:
        self.store = store
        self.name = name

    def get_setting(self, key: str, default: Any = None) -> Any:
        if key == "notify_channels":
            # An empty list would make dispatch_text fall back to legacy wecom.
            return [{"id": "guardian-registry-only", "enabled": False}]
        if key == "wecom_webhook" or (key.startswith("notify:") and key != "notify:" + self.name):
            return {}
        return self.store.get_setting(key, default)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)


def send_target(store: Any, send: Any, target: dict[str, str], *,
                title: str, body: str) -> dict[str, Any]:
    if target["kind"] == "legacy":
        candidates = _resolve_channels(store, channel_ids=[target["id"]])
        available = [c for c in candidates if str(c.get("type") or "") == target["type"]]
        if len(available) != 1 or len(candidates) != 1:
            return {"success": False, "sent": [], "skipped": "channel_unavailable"}
        receipt = send(store, title=title, body=body, channel_ids=[target["id"]])
    else:
        if target["id"] not in configured_channels(store):
            return {"success": False, "sent": [], "skipped": "channel_unavailable"}
        receipt = send(_RegistryTargetStore(store, target["id"]), title=title, body=body)
    receipt = dict(receipt)
    receipt["success"] = bool(receipt.get("success") and not receipt.get("skipped")
                              and target["type"] in (receipt.get("sent") or []))
    return receipt
