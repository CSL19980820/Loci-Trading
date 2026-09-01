"""战法目录的跨租户隔离。

这组用例盯的不是 SQL，而是**进程级 dict**：``catalog._SHARDS`` 一旦退回单层
map，A 保存战法就会把 B 的目录整个换掉（``replace_screen_engines`` 是
clear+update 全量替换），而且 B 的 ``get(A_slug)`` 会拿到 A 的引擎——引擎的
``install_path`` 指着 A 的租户目录，等于 B 直接跑 A 的代码。
"""
from __future__ import annotations

import pytest

from src.ops import save_screen_package
from src.shared.tenancy import tenant_scope
from src.strategy.application.catalog import (
    MAX_TENANT_SHARDS,
    all_strategies,
    get,
    screen_catalog_stats,
)
from src.strategy.application.screen_skills import refresh_screen_strategy_catalog
from src.strategy.domain.base import StrategyError

BUILTIN_SLUGS = ("qianlong-close-v3", "sanyuan-tail-v1", "yangshi-tail-v1")


def screen_files(slug: str, *, name: str) -> dict[str, str]:
    return {
        "SKILL.md": (
            "---\n"
            f"slug: {slug}\n"
            f"name: {name}\n"
            "version: 0.1.0\n"
            "description: 租户隔离用例\n"
            "capability: screen\n"
            "enabled: true\n"
            "---\n\n"
            "放量均线战法。\n"
        ),
        "screen.yaml": (
            "schema_version: 1\n"
            "entry_timing: next_open\n"
            "min_bars: 10\n"
            "params:\n"
            "  N: { type: int, default: 3, min: 2, max: 10, label: 周期 }\n"
            "signal: PICK\n"
            "factors: [BASE]\n"
        ),
        "formula.tdx": "BASE:=MA(CLOSE,N);\nPICK: CLOSE>BASE;\n",
    }


def install(slug: str, *, name: str) -> None:
    """在**当前租户**的 skill_root() 里装一个战法并刷新目录。"""
    save_screen_package(slug, screen_files(slug, name=name))
    refresh_screen_strategy_catalog()


def slugs() -> list[str]:
    return [engine.slug for engine in all_strategies()]


def test_screen_skill_of_one_tenant_is_invisible_to_another() -> None:
    with tenant_scope("u_a"):
        install("a-only-screen", name="A 的私有战法")
        assert "a-only-screen" in slugs()

    with tenant_scope("u_b"):
        visible = slugs()
        assert "a-only-screen" not in visible, f"B 看到了 A 的战法：{visible}"
        with pytest.raises(StrategyError):
            get("a-only-screen")


def test_saving_one_tenant_catalog_does_not_wipe_another() -> None:
    """``replace_screen_engines`` 是全量替换：分片没做对，B 的战法会当场消失。"""
    with tenant_scope("u_b"):
        install("b-only-screen", name="B 的私有战法")
        assert "b-only-screen" in slugs()

    with tenant_scope("u_a"):
        install("a-only-screen", name="A 的私有战法")
        assert "a-only-screen" in slugs()
        assert "b-only-screen" not in slugs()

    with tenant_scope("u_b"):
        after = slugs()
        assert "b-only-screen" in after, f"A 保存战法后 B 的战法消失了：{after}"
        assert "a-only-screen" not in after
        assert get("b-only-screen").slug == "b-only-screen"


def test_builtin_strategies_are_present_in_every_tenant() -> None:
    with tenant_scope("u_a"):
        install("a-only-screen", name="A 的私有战法")

    for tenant in (None, "u_a", "u_b", "u_c"):
        with tenant_scope(tenant):
            visible = slugs()
            for builtin in BUILTIN_SLUGS:
                assert builtin in visible, f"{tenant} 少了内置战法 {builtin}"
                assert get(builtin).slug == builtin


def test_new_tenant_lazily_loads_its_own_skill_root() -> None:
    """进程启动只刷过主租户；别的租户首次访问要能自己把目录读起来。

    这里绕开 refresh，直接落盘 —— 再在新的租户上下文里读目录。
    """
    with tenant_scope("u_lazy"):
        save_screen_package("lazy-screen", screen_files("lazy-screen", name="惰性战法"))

    with tenant_scope("u_lazy"):
        assert "lazy-screen" in slugs()
        assert get("lazy-screen").slug == "lazy-screen"

    with tenant_scope("u_other"):
        assert "lazy-screen" not in slugs()


def test_shard_table_is_bounded() -> None:
    """50+ 租户不能把已编译引擎全留在内存里（服务器只有 1.1G）。"""
    for index in range(MAX_TENANT_SHARDS + 8):
        with tenant_scope(f"u_bulk_{index}"):
            slugs()
    stats = screen_catalog_stats()
    assert stats["tenants"] <= MAX_TENANT_SHARDS, stats
