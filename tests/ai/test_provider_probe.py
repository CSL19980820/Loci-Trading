"""手动测试必须发送兼容的输出预算，并拿到正文才算成功。"""
from unittest.mock import MagicMock

import pytest

from src.ai.infrastructure import client


@pytest.mark.parametrize("protocol", ["openai_compatible", "anthropic"])
@pytest.mark.parametrize("empty", [False, True])
def test_probe_uses_generation_budget_and_requires_visible_reply(monkeypatch, protocol, empty):
    seen = []
    http = MagicMock()

    def post(url, *, headers, json):
        seen.append(json)
        assert json["max_tokens"] > 2
        text = "" if empty else "OK"
        payload = ({"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2}}
                   if protocol == "openai_compatible" else
                   {"content": [{"type": "text", "text": text}],
                    "usage": {"input_tokens": 4, "output_tokens": 2}})
        response = MagicMock(status_code=200)
        response.json.return_value = payload
        return response

    http.__enter__.return_value.post.side_effect = post
    factory = MagicMock(return_value=http)
    monkeypatch.setattr(client, "ConnectionRetryClient", factory)
    config = client.ProviderConfig("probe", protocol, "https://example.invalid/v1",
                                   "test-key", "test-model", "http://127.0.0.1:7890", timeout=90)
    if empty:
        with pytest.raises(client.LLMError, match="正文"):
            client.validate(config)
    else:
        reply = client.validate(config)
        assert reply.text == "OK" and reply.total_tokens == 6
    assert len(seen) == 1
    assert factory.call_args.kwargs == {"timeout": 90, "proxy": config.proxy_url}
