import pytest
from sag.parser import SAGMessageParser
from sag.exceptions import SAGParseException
from sag.model import (
    ActionStatement,
    AssertStatement,
    ControlStatement,
    ErrorStatement,
    EventStatement,
    QueryStatement,
)


def test_parse_simple_action():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy()"
    message = SAGMessageParser.parse(text)

    assert message is not None
    assert message.header is not None
    assert message.header.version == 1
    assert message.header.message_id == "msg1"
    assert message.header.source == "svc1"
    assert message.header.destination == "svc2"
    assert message.header.timestamp == 1234567890

    assert len(message.statements) == 1
    stmt = message.statements[0]
    assert isinstance(stmt, ActionStatement)
    assert stmt.verb == "deploy"


def test_parse_action_with_arguments():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy("app1", 42)'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    action = message.statements[0]
    assert isinstance(action, ActionStatement)
    assert action.verb == "deploy"
    assert len(action.args) == 2
    assert action.args[0] == "app1"
    assert action.args[1] == 42


def test_parse_action_with_named_arguments():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy(app="app1", version=2)'
    message = SAGMessageParser.parse(text)

    action = message.statements[0]
    assert isinstance(action, ActionStatement)
    assert action.verb == "deploy"
    assert len(action.named_args) == 2
    assert action.named_args["app"] == "app1"
    assert action.named_args["version"] == 2


def test_parse_action_with_policy():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO deploy() P:security PRIO=HIGH BECAUSE "security update"'
    message = SAGMessageParser.parse(text)

    action = message.statements[0]
    assert isinstance(action, ActionStatement)
    assert action.verb == "deploy"
    assert action.policy == "security"
    assert action.priority == "HIGH"
    assert action.reason == "security update"


def test_parse_query_statement():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nQ status.health"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], QueryStatement)
    query = message.statements[0]
    assert query.expression == "status.health"


def test_parse_query_with_constraint():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nQ status WHERE healthy==true"
    message = SAGMessageParser.parse(text)

    query = message.statements[0]
    assert isinstance(query, QueryStatement)
    assert query.expression is not None
    assert query.constraint is not None


def test_parse_assert_statement():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nA status.ready = true"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], AssertStatement)
    assert_stmt = message.statements[0]
    assert assert_stmt.path == "status.ready"
    assert assert_stmt.value is True


def test_parse_control_statement():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nIF ready==true THEN DO start() ELSE DO wait()"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], ControlStatement)
    ctrl = message.statements[0]
    assert ctrl.condition is not None
    assert ctrl.then_statement is not None
    assert ctrl.else_statement is not None
    assert isinstance(ctrl.then_statement, ActionStatement)
    assert isinstance(ctrl.else_statement, ActionStatement)


def test_parse_event_statement():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nEVT userLogin("user123")'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], EventStatement)
    event = message.statements[0]
    assert event.event_name == "userLogin"
    assert len(event.args) == 1
    assert event.args[0] == "user123"


def test_parse_error_statement():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nERR TIMEOUT "Connection timed out"'
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    assert isinstance(message.statements[0], ErrorStatement)
    error = message.statements[0]
    assert error.error_code == "TIMEOUT"
    assert error.message == "Connection timed out"


def test_parse_multiple_statements():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO start(); A ready = true; Q status"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 3
    assert isinstance(message.statements[0], ActionStatement)
    assert isinstance(message.statements[1], AssertStatement)
    assert isinstance(message.statements[2], QueryStatement)


def test_parse_header_with_correlation():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890 corr=parent123\nDO test()"
    message = SAGMessageParser.parse(text)

    assert message.header.correlation == "parent123"


def test_parse_header_with_ttl():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890 ttl=30\nDO test()"
    message = SAGMessageParser.parse(text)

    assert message.header.ttl == 30


def test_parse_header_with_correlation_and_ttl():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890 corr=parent123 ttl=30\nDO test()"
    message = SAGMessageParser.parse(text)

    assert message.header.correlation == "parent123"
    assert message.header.ttl == 30


def test_parse_values_in_action():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nDO test(42, 3.14, true, false, null, "string")'
    message = SAGMessageParser.parse(text)

    action = message.statements[0]
    assert isinstance(action, ActionStatement)
    assert len(action.args) == 6
    assert action.args[0] == 42
    assert action.args[1] == 3.14
    assert action.args[2] is True
    assert action.args[3] is False
    assert action.args[4] is None
    assert action.args[5] == "string"


def test_invalid_syntax():
    text = "H v 1 invalid syntax\nDO test()"
    with pytest.raises(SAGParseException):
        SAGMessageParser.parse(text)
