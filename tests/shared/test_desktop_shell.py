from __future__ import annotations

from src.shared.desktop_shell import (
    CloseAction,
    MinimizeAction,
    decide_main_close,
    decide_minimize,
    decide_peek_close,
)


def test_minimize_hides_only_when_tray_is_ready_and_preference_allows() -> None:
    assert (
        decide_minimize(
            quitting=False,
            tray_requested=True,
            tray_started=True,
            has_tray_icon=True,
            minimize_to_tray=True,
        )
        is MinimizeAction.HIDE_TO_TRAY
    )
    assert (
        decide_minimize(
            quitting=False,
            tray_requested=True,
            tray_started=True,
            has_tray_icon=True,
            minimize_to_tray=False,
        )
        is MinimizeAction.KEEP_IN_TASKBAR
    )
    assert (
        decide_minimize(
            quitting=False,
            tray_requested=True,
            tray_started=False,
            has_tray_icon=False,
            minimize_to_tray=True,
        )
        is MinimizeAction.KEEP_IN_TASKBAR
    )


def test_minimize_pref_read_failure_keeps_existing_tray_default() -> None:
    assert (
        decide_minimize(
            quitting=False,
            tray_requested=True,
            tray_started=True,
            has_tray_icon=True,
            minimize_to_tray=None,
        )
        is MinimizeAction.HIDE_TO_TRAY
    )
    assert (
        decide_minimize(
            quitting=True,
            tray_requested=True,
            tray_started=True,
            has_tray_icon=True,
            minimize_to_tray=True,
        )
        is MinimizeAction.IGNORE
    )


def test_peek_close_hides_to_tray_until_process_is_quitting() -> None:
    assert decide_peek_close(quitting=False) is CloseAction.HIDE_TO_TRAY
    assert decide_peek_close(quitting=True) is CloseAction.ALLOW_CLOSE


def test_main_close_keeps_bootstrap_confirmation_and_shutdown_transition() -> None:
    assert (
        decide_main_close(
            quitting=False,
            bootstrap_running=True,
            quit_confirmed=False,
        )
        is CloseAction.CANCEL
    )
    assert (
        decide_main_close(
            quitting=False,
            bootstrap_running=True,
            quit_confirmed=True,
        )
        is CloseAction.REQUEST_QUIT
    )
    assert (
        decide_main_close(
            quitting=True,
            bootstrap_running=False,
            quit_confirmed=True,
        )
        is CloseAction.ALLOW_CLOSE
    )
