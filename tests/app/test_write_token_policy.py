"""生产 Bearer 最小长度与轮换提示。"""
from __future__ import annotations

import logging

import pytest

from src.app.write_token_policy import (
    WRITE_TOKEN_MIN_LENGTH_PRODUCTION,
    apply_write_token_policy,
)


def test_production_short_token_rejected() -> None:
    with pytest.raises(RuntimeError, match="≥32"):
        apply_write_token_policy(
            write_token="too-short",
            is_production=True,
            require_write_auth=True,
            issued_at_raw="",
        )


def test_production_long_token_ok() -> None:
    token = "a" * WRITE_TOKEN_MIN_LENGTH_PRODUCTION
    msgs = apply_write_token_policy(
        write_token=token,
        is_production=True,
        require_write_auth=True,
        issued_at_raw="",
        log=logging.getLogger("test_write_token"),
    )
    assert any("长期静态" in m for m in msgs)


def test_local_short_token_allowed() -> None:
    msgs = apply_write_token_policy(
        write_token="local-ok",
        is_production=False,
        require_write_auth=False,
        issued_at_raw="",
    )
    assert msgs == []
