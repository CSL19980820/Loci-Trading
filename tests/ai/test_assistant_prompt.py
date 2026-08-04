from src.ai.domain.assistant import assistant_system_prompt


def test_owner_full_prompt_allows_registered_writes_without_per_action_confirmation() -> None:
    prompt = assistant_system_prompt()

    assert "owner_full" in prompt
    assert "不要求逐笔确认" in prompt
    assert "密钥读取、券商下单或自动交易" in prompt
