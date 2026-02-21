from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier


def test_minify_simple_action():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy()"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert minified is not None
    assert minified.startswith("H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n")
    assert "DO deploy()" in minified


def test_minify_action_with_arguments():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1", 42)'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert 'DO deploy("app1",42)' in minified


def test_minify_action_with_named_args():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy(app="app1", version=2)'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert 'DO deploy(app="app1",version=2)' in minified


def test_minify_action_with_policy():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy() P:security PRIO=HIGH BECAUSE "security update"'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "P:security" in minified
    assert "PRIO=HIGH" in minified
    assert 'BECAUSE "security update"' in minified


def test_minify_multiple_statements():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO start(); A ready = true; Q status"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "DO start();" in minified
    assert "A ready = true;" in minified
    assert "Q status" in minified


def test_minify_with_correlation():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890 corr=parent123\nDO test()"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "corr=parent123" in minified


def test_minify_error():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nERR TIMEOUT "Connection timed out"'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert 'ERR TIMEOUT "Connection timed out"' in minified


def test_token_counting():
    message = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy()"
    tokens = MessageMinifier.count_tokens(message)

    assert tokens > 0
    assert 13 <= tokens <= 17


def test_compare_with_json():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1")'
    message = SAGMessageParser.parse(text)
    comparison = MessageMinifier.compare_with_json(message)

    assert comparison is not None
    assert comparison.sag_length > 0
    assert comparison.json_length > 0
    assert comparison.sag_tokens > 0
    assert comparison.json_tokens > 0
    assert comparison.sag_length < comparison.json_length
    assert comparison.tokens_saved > 0
    assert comparison.percent_saved > 0


def test_minify_and_reparse():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1", version=2)'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    reparsed = SAGMessageParser.parse(minified)

    assert reparsed is not None
    assert reparsed.header.message_id == message.header.message_id
    assert len(reparsed.statements) == len(message.statements)
