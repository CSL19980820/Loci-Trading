"""boot_splash 与 SPA index.html 同构契约。"""

from __future__ import annotations

from pathlib import Path

from src.shared.boot_splash import (
    BOOT_SPLASH_REV,
    handoff_to_spa,
    render_splash_html,
    spa_boot_splash_markup,
)


ROOT = Path(__file__).resolve().parents[2]


def test_render_splash_has_zero_percent_axis_and_fullpage_map() -> None:
    html = render_splash_html("启动中", phase="enter")
    assert BOOT_SPLASH_REV in html
    assert ">0%</text>" in html
    assert "loci-boot-map" in html
    assert 'preserveAspectRatio="none"' in html
    assert "晨光落印" in html
    assert "#c41e3a" in html
    assert "#4A86E8" in html


def test_error_and_exit_phases() -> None:
    err = render_splash_html("启动失败：x", phase="error")
    assert "phase-error" in err
    assert "中断" in err
    assert "启动失败：x" in err
    assert "loci-boot-close" in err
    assert 'class="loci-boot-map"' not in err
    ex = render_splash_html("正在关闭", phase="exit")
    assert "phase-exit" in ex
    assert "落笔" in ex
    assert "账本封存" in ex
    assert "loci-boot-close-rail" in ex
    assert 'class="loci-boot-map"' not in ex
    # 退出不得再跑分时回撤动画
    assert "PHASE === \"exit\" ? 18" not in ex
    enter = render_splash_html("启动中", phase="enter")
    assert "开账进行中" in enter
    assert "var pct = 0" in enter
    assert "var FINISH_MS = 1000" in enter
    assert 'class="loci-boot-map"' in enter


def test_enter_climbs_then_finishes_to_100() -> None:
    enter = render_splash_html("启动中", phase="enter")
    assert "IDLE_CEILING" in enter
    assert "finishFrom + (100 - finishFrom)" in enter
    assert "PHASE === \"exit\" ? 18" not in enter
    assert "pct + 2.5" not in enter


def test_enter_does_not_animate_progress_down() -> None:
    enter = render_splash_html("启动中", phase="enter")
    assert "target = PHASE === \"exit\"" not in enter
    assert "pct - " not in enter


def test_spa_index_shares_boot_splash_rev_and_engine() -> None:
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css, body, js = spa_boot_splash_markup()
    assert f'data-rev="{BOOT_SPLASH_REV}"' in index
    assert "loci-boot-map" in index
    assert ">0%</text>" in js
    assert css in index
    assert body.strip() in index
    assert "__lociBootSplash" in index
    assert "top:10vh" in css


def test_spa_engine_starts_during_parse_before_module_mounts() -> None:
    _, _, js = spa_boot_splash_markup()
    assert 'document.addEventListener("DOMContentLoaded", start)' not in js
    assert "\n  start();\n" in js


def test_spa_skips_second_splash_after_native_handoff() -> None:
    _, _, js = spa_boot_splash_markup()
    assert 'get("_boot_splash") === "done"' in js
    assert "root.remove();" in js


def test_desktop_handoff_completes_splash_before_loading_spa() -> None:
    class FakeWindow:
        native = None

        def __init__(self) -> None:
            self.events: list[tuple[str, str]] = []

        def evaluate_js(self, script: str, callback=None) -> None:
            from threading import Timer

            self.events.append(("evaluate", script))

            def finish() -> None:
                self.events.append(("resolved", "completed"))
                callback("completed")

            Timer(0.01, finish).start()

        def load_url(self, target: str) -> None:
            self.events.append(("load", target))

    window = FakeWindow()
    target, completed = handoff_to_spa(
        window,
        "http://127.0.0.1:8765/?_boot=1",
        timeout=0.05,
    )

    assert completed is True
    assert [kind for kind, _ in window.events] == ["evaluate", "resolved", "load"]
    assert "__lociBootSplash" in window.events[0][1]
    assert target.endswith("&_boot_splash=done")
    assert window.events[2] == ("load", target)


def test_desktop_handoff_keeps_spa_splash_when_native_api_is_missing() -> None:
    class FakeWindow:
        native = None

        def __init__(self) -> None:
            self.loaded = ""

        def evaluate_js(self, script: str, callback=None) -> None:
            callback("missing")

        def load_url(self, target: str) -> None:
            self.loaded = target

    window = FakeWindow()
    original = "http://127.0.0.1:8765/?_boot=1"
    target, completed = handoff_to_spa(window, original, timeout=0.05)

    assert completed is False
    assert target == original
    assert window.loaded == original


def test_desktop_handoff_evaluates_js_off_the_winforms_ui_dispatcher(monkeypatch) -> None:
    from src.shared import webview_ui

    dispatches: list[str] = []

    def fake_ui_dispatch(window, action, *, wait: bool = True) -> None:
        dispatches.append("ui")
        action()

    monkeypatch.setattr(webview_ui, "run_on_ui_thread", fake_ui_dispatch)

    class FakeWindow:
        native = object()

        def evaluate_js(self, script: str, callback=None) -> None:
            callback("completed")

        def load_url(self, target: str) -> None:
            dispatches.append("load")

    handoff_to_spa(
        FakeWindow(),
        "http://127.0.0.1:8765/?_boot=1",
        timeout=0.05,
    )

    assert dispatches == ["ui", "load"]
