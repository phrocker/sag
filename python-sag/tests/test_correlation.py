from sag.parser import SAGMessageParser
from sag.correlation import CorrelationEngine
from sag.model import Header, Message


def test_create_response_header():
    engine = CorrelationEngine("agent1")
    header = engine.create_response_header("agent1", "agent2")

    assert header is not None
    assert header.source == "agent1"
    assert header.destination == "agent2"
    assert header.message_id.startswith("agent1-")


def test_auto_correlation():
    engine = CorrelationEngine("agent1")

    text = "H v 1 id=msg1 src=agent2 dst=agent1 ts=1234567890\nDO query()"
    incoming = SAGMessageParser.parse(text)
    engine.record_incoming(incoming)

    response_header = engine.create_response_header("agent1", "agent2")
    assert response_header.correlation == "msg1"


def test_create_header_in_response_to():
    engine = CorrelationEngine("agent1")

    text = "H v 1 id=msg1 src=agent2 dst=agent1 ts=1234567890\nDO query()"
    incoming = SAGMessageParser.parse(text)

    response_header = engine.create_header_in_response_to("agent1", "agent2", incoming)
    assert response_header.correlation == "msg1"


def test_generate_unique_message_ids():
    engine = CorrelationEngine("agent1")

    id1 = engine.generate_message_id()
    id2 = engine.generate_message_id()
    id3 = engine.generate_message_id()

    assert id1 != id2
    assert id2 != id3
    assert id1 != id3
    assert id1.startswith("agent1-")
    assert id2.startswith("agent1-")
    assert id3.startswith("agent1-")


def test_trace_thread():
    msg1 = SAGMessageParser.parse("H v 1 id=msg1 src=agent1 dst=agent2 ts=1000\nDO start()")
    msg2 = SAGMessageParser.parse("H v 1 id=msg2 src=agent2 dst=agent3 ts=2000 corr=msg1\nDO process()")
    msg3 = SAGMessageParser.parse("H v 1 id=msg3 src=agent3 dst=agent1 ts=3000 corr=msg2\nDO finish()")

    all_messages = [msg1, msg2, msg3]

    thread = CorrelationEngine.trace_thread(all_messages, "msg3")

    assert len(thread) == 3
    assert thread[0].header.message_id == "msg1"
    assert thread[1].header.message_id == "msg2"
    assert thread[2].header.message_id == "msg3"


def test_find_responses():
    msg1 = SAGMessageParser.parse("H v 1 id=msg1 src=agent1 dst=agent2 ts=1000\nDO start()")
    msg2 = SAGMessageParser.parse("H v 1 id=msg2 src=agent2 dst=agent3 ts=2000 corr=msg1\nDO process()")
    msg3 = SAGMessageParser.parse("H v 1 id=msg3 src=agent3 dst=agent1 ts=3000 corr=msg1\nDO finish()")

    all_messages = [msg1, msg2, msg3]
    responses = CorrelationEngine.find_responses(all_messages, "msg1")

    assert len(responses) == 2
    response_ids = [r.header.message_id for r in responses]
    assert "msg2" in response_ids
    assert "msg3" in response_ids


def test_build_conversation_tree():
    msg1 = SAGMessageParser.parse("H v 1 id=msg1 src=agent1 dst=agent2 ts=1000\nDO start()")
    msg2 = SAGMessageParser.parse("H v 1 id=msg2 src=agent2 dst=agent3 ts=2000 corr=msg1\nDO process()")
    msg3 = SAGMessageParser.parse("H v 1 id=msg3 src=agent3 dst=agent1 ts=3000 corr=msg1\nDO finish()")
    msg4 = SAGMessageParser.parse("H v 1 id=msg4 src=agent1 dst=agent2 ts=4000 corr=msg2\nDO acknowledge()")

    all_messages = [msg1, msg2, msg3, msg4]
    tree = CorrelationEngine.build_conversation_tree(all_messages)

    assert "msg1" in tree
    assert len(tree["msg1"]) == 2
    assert "msg2" in tree["msg1"]
    assert "msg3" in tree["msg1"]

    assert "msg2" in tree
    assert len(tree["msg2"]) == 1
    assert "msg4" in tree["msg2"]


def test_clear():
    engine = CorrelationEngine("agent1")

    header1 = engine.create_response_header("agent1", "agent2")
    assert header1.correlation is None

    msg = Message(
        header=Header(version=1, message_id="msg1", source="agent2", destination="agent1", timestamp=1000),
        statements=[],
    )
    engine.record_incoming(msg)

    header2 = engine.create_response_header("agent1", "agent2")
    assert header2.correlation == "msg1"

    engine.clear()
    header3 = engine.create_response_header("agent1", "agent2")
    assert header3.correlation is None
