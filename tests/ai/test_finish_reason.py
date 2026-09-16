"""上游长度截断不得在流式适配器和Agent结果间丢失。"""
import json
from unittest.mock import patch

import httpx2
import pytest

from src.ai import ProviderConfig
from src.ai.application.agent import run_agent
from src.ai.infrastructure.connection_retry import ConnectionRetryClient


@pytest.mark.parametrize('protocol,reason', [('openai_compatible', 'length'), ('anthropic', 'max_tokens')])
@pytest.mark.parametrize('streaming', [True, False])
def test_upstream_finish_reason_survives_transport_and_agent(protocol, reason, streaming):
    def handle(request):
        if protocol == 'openai_compatible':
            data = {'choices': [{'message': {'content': '{"summary":"截断'}, 'finish_reason': reason}],
                    'usage': {'prompt_tokens': 7, 'completion_tokens': 8192}}
            if streaming:
                data['choices'][0]['delta'] = data['choices'][0].pop('message')
                return httpx2.Response(200, text='data: ' + json.dumps(data) + '\n\ndata: [DONE]\n\n')
        else:
            data = {'content': [{'type': 'text', 'text': '{"summary":"截断'}], 'stop_reason': reason,
                    'usage': {'input_tokens': 7, 'output_tokens': 8192}}
            if streaming:
                events = [{'type': 'message_start', 'message': {'usage': {'input_tokens': 7}}},
                          {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '{"summary":"截断'}},
                          {'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 8192}},
                          {'type': 'message_stop'}]
                return httpx2.Response(200, text=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))
        return httpx2.Response(200, json=data)
    provider = ProviderConfig('test', protocol, 'https://example.invalid', 'test', 'model')
    with patch('src.ai.infrastructure.client.ConnectionRetryClient',
               side_effect=lambda **kw: ConnectionRetryClient(transport=httpx2.MockTransport(handle), **kw)):
        result = run_agent(provider, system='test', user_prompt='report', stream=streaming)
    assert result.finish_reason == reason
    assert result.to_dict()['finish_reason'] == reason
    assert result.output_tokens == 8192 and result.input_tokens == 7
    assert result.text == '{"summary":"截断'
