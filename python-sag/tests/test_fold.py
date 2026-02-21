from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.model import FoldStatement, RecallStatement
from sag.fold import FoldEngine


def test_parse_fold_statement():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nFOLD fold123 "Summary of conversation"'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], FoldStatement)
    fold = message.statements[0]
    assert fold.fold_id == "fold123"
    assert fold.summary == "Summary of conversation"
    assert fold.state is None


def test_parse_fold_statement_with_state():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nFOLD fold123 "Summary" STATE {"key": "value", "count": 42}'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    fold = message.statements[0]
    assert isinstance(fold, FoldStatement)
    assert fold.fold_id == "fold123"
    assert fold.summary == "Summary"
    assert fold.state is not None
    assert fold.state["key"] == "value"
    assert fold.state["count"] == 42


def test_parse_recall_statement():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nRECALL fold123"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], RecallStatement)
    recall = message.statements[0]
    assert recall.fold_id == "fold123"


def test_fold_round_trip_minify():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nFOLD fold123 "Summary of conversation"'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert 'FOLD fold123 "Summary of conversation"' in minified

    reparsed = SAGMessageParser.parse(minified)
    assert reparsed is not None
    assert len(reparsed.statements) == 1
    assert isinstance(reparsed.statements[0], FoldStatement)


def test_recall_round_trip_minify():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nRECALL fold123"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "RECALL fold123" in minified

    reparsed = SAGMessageParser.parse(minified)
    assert reparsed is not None
    assert len(reparsed.statements) == 1
    assert isinstance(reparsed.statements[0], RecallStatement)


def test_mixed_statements_with_fold():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO start(); FOLD fold1 "Previous work done"; Q status'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 3
    from sag.model import ActionStatement, QueryStatement
    assert isinstance(message.statements[0], ActionStatement)
    assert isinstance(message.statements[1], FoldStatement)
    assert isinstance(message.statements[2], QueryStatement)


def test_fold_engine_fold_unfold():
    engine = FoldEngine()

    msg1 = SAGMessageParser.parse("H v 1 id=msg1 src=a dst=b ts=1000\nDO start()")
    msg2 = SAGMessageParser.parse("H v 1 id=msg2 src=b dst=a ts=2000\nDO process()")

    fold_stmt = engine.fold([msg1, msg2], "Completed startup and processing")

    assert fold_stmt.fold_id is not None
    assert fold_stmt.summary == "Completed startup and processing"

    # Unfold
    original = engine.unfold(fold_stmt.fold_id)
    assert original is not None
    assert len(original) == 2
    assert original[0].header.message_id == "msg1"
    assert original[1].header.message_id == "msg2"


def test_fold_engine_unfold_unknown():
    engine = FoldEngine()
    result = engine.unfold("nonexistent")
    assert result is None


def test_fold_engine_has_fold():
    engine = FoldEngine()
    msg = SAGMessageParser.parse("H v 1 id=msg1 src=a dst=b ts=1000\nDO start()")

    fold_stmt = engine.fold([msg], "Test fold")

    assert engine.has_fold(fold_stmt.fold_id) is True
    assert engine.has_fold("nonexistent") is False


def test_fold_engine_detect_pressure():
    engine = FoldEngine()

    messages = []
    for i in range(20):
        msg = SAGMessageParser.parse(f"H v 1 id=msg{i} src=a dst=b ts={1000 + i}\nDO action{i}()")
        messages.append(msg)

    # With a small budget, should detect pressure
    assert engine.detect_pressure(messages, budget=50, threshold=0.5) is True

    # With a huge budget, should not detect pressure
    assert engine.detect_pressure(messages, budget=100000, threshold=0.7) is False


def test_fold_engine_with_state():
    engine = FoldEngine()
    msg = SAGMessageParser.parse("H v 1 id=msg1 src=a dst=b ts=1000\nDO start()")

    fold_stmt = engine.fold([msg], "With state", state={"key": "value", "count": 42})

    assert fold_stmt.state is not None
    assert fold_stmt.state["key"] == "value"
    assert fold_stmt.state["count"] == 42
