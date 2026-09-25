import pytest

from src.ai.infrastructure.assistant_store_util import redact


@pytest.mark.parametrize(('source', 'expected'), [
    ('**众泰汽车 [000980](https://example.test/q/000980)** 收 2.24）',
     '**众泰汽车 [000980]([URL])** 收 2.24）'),
    ('[资料](https://example.test/path_(nested)?token=private&next=(other))继续正文',
     '[资料]([URL])继续正文'),
    ('[一](https://one.test/?secret=private)**[二](https://two.test/?key=other)**',
     '[一]([URL])**[二]([URL])**'),
    ('[来源](https://example.test/path "说明")', '[来源]([URL] "说明")'),
    ('[来源](<https://example.test/path?token=private>)', '[来源](<[URL]>)'),
    ('(https://example.test/path_(a)?secret=private)', '([URL]'),
    ('**https://example.test/?token=private**', '**[URL]**'),
    ('https://example.test/path_(a)?token=private', '[URL]'),
    ('[已经脱敏]([URL])', '[已经脱敏]([URL])'),
])
def test_url_redaction_preserves_markdown_without_exposing_destination(source, expected):
    result = redact(source)
    assert result == expected
    assert 'example.test' not in result and 'private' not in result


def test_existing_secret_and_image_contracts_remain():
    assert redact({'authorization': 'Bearer private', 'password': 'secret'}) == {
        'authorization': '[REDACTED]', 'password': '[REDACTED]'}
    assert redact('Bearer abc_123 and sk-private') == '[REDACTED] and [REDACTED]'
    assert redact('data:image/png;base64,fixture') == 'data:image/png;base64,fixture'
    assert len(redact('x' * 9000)) == 8000


def test_nested_query_parentheses_and_escaped_parenthesis_do_not_leak():
    source = r'[来源](https://example.test/a_(b_(c))?key=secret\)tail&password=private)**'
    result = redact(source)
    assert result == '[来源]([URL])**'
    assert 'secret' not in result and 'private' not in result and 'tail' not in result


def test_non_markdown_parentheses_do_not_expose_url_query_tail():
    result = redact('value=(https://example.test/?token=secret)TAIL)')
    assert result == 'value=([URL]'
    assert 'secret' not in result and 'TAIL' not in result


def test_persisted_message_and_event_keep_valid_markdown(tmp_path):
    from src.ai.infrastructure.assistant_store import AssistantStore
    path = tmp_path / 'ops.db'
    content = '**众泰汽车 [000980](https://example.test/q/000980?token=private)** 收 2.24）'
    expected = '**众泰汽车 [000980]([URL])** 收 2.24）'
    with AssistantStore(path) as store:
        session = store.create_session(title='isolated Markdown fixture')
        run = store.create_run(session)
        message = store.append_message(session, role='assistant', content=content)
        event = store.append_event(run, 'token', {'text': content, 'api_key': 'private'})
        assert message['content'] == expected
        assert event['payload']['text'] == expected
        assert event['payload']['api_key'] == '[REDACTED]'
    with AssistantStore(path) as store:
        assert store.list_messages(session)[0]['content'] == expected
