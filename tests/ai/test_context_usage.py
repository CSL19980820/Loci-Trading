from src.ai.application.context_usage import estimate_tokens


def test_estimate_tokens_treats_cjk_denser_than_ascii() -> None:
    assert estimate_tokens("持仓盈亏") == 4
    assert estimate_tokens("abcd") == 1
