"""进程级日志引导:容器绕过 CLI 直起 uvicorn,根 logger 没人配就丢掉全部 INFO。"""
from __future__ import annotations

import logging

from src.app.logging_setup import (
    DEFAULT_LOG_LEVEL,
    LOG_LEVEL_ENV,
    configure_logging,
)


def _reset_root() -> list:
    """摘掉根 logger 现有处理器并交还,便于测试后原样装回。"""
    root = logging.getLogger()
    saved = list(root.handlers)
    for handler in saved:
        root.removeHandler(handler)
    return saved


def _restore_root(saved: list) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved:
        root.addHandler(handler)


def test_configures_root_when_nobody_did(monkeypatch) -> None:
    """裸进程(生产 uvicorn 就是这种)必须被配上,否则 INFO 全丢。

    修复前现象:线上整段启动日志只有 11 行,「调度器已启动,装载 N 个任务」
    这类关键证据一条都没有——只有 ``logger.warning`` 能经 Python 的 lastResort
    漏出来,于是日志里只剩故障、没有上下文。
    """
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    saved = _reset_root()
    try:
        assert configure_logging() is True
        root = logging.getLogger()
        assert root.handlers, "根 logger 必须被装上处理器"
        assert root.level == logging.INFO
    finally:
        _restore_root(saved)


def test_does_not_hijack_an_existing_configuration(monkeypatch) -> None:
    """已有配置就不许动手。

    ``create_app`` 在测试里会被反复调用,CLI 入口(``cli/ops.py`` /
    ``cli/market.py``)也各有自己的 basicConfig。抢过来会把它们的级别与格式
    一起改掉。
    """
    monkeypatch.delenv(LOG_LEVEL_ENV, raising=False)
    saved = _reset_root()
    try:
        root = logging.getLogger()
        sentinel = logging.NullHandler()
        root.addHandler(sentinel)
        root.setLevel(logging.CRITICAL)
        assert configure_logging() is False
        assert root.handlers == [sentinel]
        assert root.level == logging.CRITICAL
    finally:
        _restore_root(saved)


def test_level_comes_from_the_environment(monkeypatch) -> None:
    """级别可由环境变量覆盖,排障时不用改代码重新部署。"""
    monkeypatch.setenv(LOG_LEVEL_ENV, "debug")
    saved = _reset_root()
    try:
        assert configure_logging() is True
        assert logging.getLogger().level == logging.DEBUG
    finally:
        _restore_root(saved)


def test_level_name_is_case_insensitive(monkeypatch) -> None:
    """``warning`` / ``WARNING`` 等价:实现先 ``.upper()`` 再取常量。

    写这条是因为一次自纠:原先以为 ``getattr(logging, "warning")`` 会取到**函数**
    而需要 ``isinstance`` 兜底,实测并非如此——先 upper 之后拿到的是常量 30。
    把真实行为钉下来,免得后人照着一个不存在的隐患去改实现。
    """
    monkeypatch.setenv(LOG_LEVEL_ENV, "warning")
    saved = _reset_root()
    try:
        assert configure_logging() is True
        assert logging.getLogger().level == logging.WARNING
    finally:
        _restore_root(saved)


def test_bogus_level_falls_back_instead_of_crashing(monkeypatch) -> None:
    """日志配置炸掉服务本末倒置:级别名写不出来就回落 INFO,不抛。

    ``BASICCONFIG`` 这类能命中 ``logging`` 模块里**非级别**属性的名字也要挡住,
    所以实现除了 ``getattr`` 还判 ``isinstance(level, int)``。
    """
    for bogus in ("NOPE", "", "  ", "BASICCONFIG"):
        monkeypatch.setenv(LOG_LEVEL_ENV, bogus)
        saved = _reset_root()
        try:
            assert configure_logging() is True
            assert logging.getLogger().level == logging.INFO, bogus
        finally:
            _restore_root(saved)


def test_default_level_constant_is_info() -> None:
    """默认档写死在常量里,改动会被这条挡一下——生产靠它复盘启动过程。"""
    assert DEFAULT_LOG_LEVEL == "INFO"
