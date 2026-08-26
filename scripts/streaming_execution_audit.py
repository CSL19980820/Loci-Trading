"""Execution-capacity audits shared by read-only streaming factor experiments."""
from __future__ import annotations

from typing import Any


def execution_overlap_audit(
    by_date: dict[str, list[Any]], *, capacity: int, hold_days: int
) -> dict[str, int]:
    """Audit fixed capital slots without treating a delayed close exit as free at next open."""
    occupied_until = [-1] * capacity
    selected = 0
    untradable = 0
    delayed_exits = 0
    slot_conflicts = 0
    executed = 0
    for _, rows in sorted(by_date.items()):
        for item in rows:
            selected += 1
            if (
                item.net_return_pct is None
                or item.signal_index is None
                or item.entry_index is None
                or item.exit_index is None
            ):
                untradable += 1
                continue
            if item.exit_index > item.signal_index + hold_days:
                delayed_exits += 1
            free_slot = next(
                (index for index, exit_index in enumerate(occupied_until) if exit_index < item.entry_index),
                None,
            )
            if free_slot is None:
                slot_conflicts += 1
                continue
            occupied_until[free_slot] = item.exit_index
            executed += 1
    return {
        "selected_ranked_slots": selected,
        "untradable_ranked_slots": untradable,
        "delayed_exit_positions": delayed_exits,
        "slot_conflicts_from_delayed_exits": slot_conflicts,
        "executed_without_slot_conflict": executed,
    }
