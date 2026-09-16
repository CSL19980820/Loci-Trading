from src.review.application.workshop import enabled_workshop_catalog, workshop_winrates


def test_only_enabled_existing_workshop_methods_are_visible():
    catalog = [{"slug": "new", "name": "趋势精选"}, {"slug": "old", "name": "退役战法"}]
    jobs = [
        {"kind": "screen", "enabled": True, "config": {"strategy": "new"}},
        {"kind": "skill_watch", "enabled": True, "config": {"skill": "new"}},
        {"kind": "screen", "enabled": False, "config": {"strategy": "old"}},
        {"kind": "skill", "enabled": True, "config": {"skill": "deleted"}},
        {"kind": "backtest", "enabled": True, "config": {"strategy": "old"}},
    ]
    active = enabled_workshop_catalog(catalog, jobs)
    assert active == [{"slug": "new", "name": "趋势精选"}]
    result = workshop_winrates([{"strategy_tag": "old", "total": 12}], active)
    assert result[0]["strategy_name"] == "趋势精选"
    assert result[0]["win_rate"] is None
    assert len(result) == 1


def test_pause_or_rename_is_visible_without_statistics_cache_invalidation():
    job = {"kind": "screen", "enabled": True, "config": {"strategy": "a"}}
    catalog = [{"slug": "a", "name": "新的显示名称"}]
    rows = [{"strategy_tag": "a", "total": 5, "wins": 3, "win_rate": 60}]
    assert workshop_winrates(rows, enabled_workshop_catalog(catalog, [job]))[0]["strategy_name"] == "新的显示名称"
    job["enabled"] = False
    assert enabled_workshop_catalog(catalog, [job]) == []
