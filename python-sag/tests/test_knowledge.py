from sag.parser import SAGMessageParser
from sag.minifier import MessageMinifier
from sag.model import (
    ActionStatement,
    FoldStatement,
    KnowledgeStatement,
    SubscribeStatement,
    UnsubscribeStatement,
)
from sag.knowledge import KnowledgeEngine, topic_matches
from sag.fold import FoldEngine


# --- Topic matching ---


def test_topic_exact_match():
    assert topic_matches("system.cpu", "system.cpu") is True
    assert topic_matches("system.cpu", "system.mem") is False


def test_topic_single_level_wildcard():
    assert topic_matches("system.*", "system.cpu") is True
    assert topic_matches("system.*", "system.mem") is True
    assert topic_matches("system.*", "system.disk.usage") is False
    assert topic_matches("system.*", "other.cpu") is False


def test_topic_multi_level_wildcard():
    assert topic_matches("system.**", "system.cpu") is True
    assert topic_matches("system.**", "system.disk.usage") is True
    assert topic_matches("system.**", "system.disk.io.read") is True
    assert topic_matches("system.**", "other.cpu") is False


def test_topic_wildcard_prefix_only():
    assert topic_matches("system.**", "system") is True
    assert topic_matches("system.*", "system") is False


def test_topic_bare_double_star():
    assert topic_matches("**", "system.cpu") is True
    assert topic_matches("**", "app.errors") is True
    assert topic_matches("**", "anything") is True
    assert topic_matches("**", "deeply.nested.topic.here") is True


# --- Grammar parse: SUB ---


def test_parse_sub_wildcard():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.*"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    stmt = message.statements[0]
    assert isinstance(stmt, SubscribeStatement)
    assert stmt.topic == "system.*"
    assert stmt.filter_expr is None


def test_parse_sub_multi_level_wildcard():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.**"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, SubscribeStatement)
    assert stmt.topic == "system.**"


def test_parse_sub_exact_topic():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.cpu"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, SubscribeStatement)
    assert stmt.topic == "system.cpu"
    assert stmt.filter_expr is None


def test_parse_sub_with_filter():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.** WHERE cpu>80"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, SubscribeStatement)
    assert stmt.topic == "system.**"
    assert stmt.filter_expr is not None
    assert "cpu" in stmt.filter_expr
    assert "80" in stmt.filter_expr


# --- Grammar parse: UNSUB ---


def test_parse_unsub():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nUNSUB system.*"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    stmt = message.statements[0]
    assert isinstance(stmt, UnsubscribeStatement)
    assert stmt.topic == "system.*"


# --- Grammar parse: KNOW ---


def test_parse_know_int():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW system.cpu = 85 v 3"
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 1
    stmt = message.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.topic == "system.cpu"
    assert stmt.value == 85
    assert stmt.version == 3


def test_parse_know_float():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW system.cpu = 85.2 v 3"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.value == 85.2
    assert stmt.version == 3


def test_parse_know_string():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW deployment.status = "healthy" v 1'
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.topic == "deployment.status"
    assert stmt.value == "healthy"
    assert stmt.version == 1


def test_parse_know_bool():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW system.healthy = true v 5"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.value is True
    assert stmt.version == 5


def test_parse_know_with_wildcard_topic():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW system.* = 42 v 1"
    message = SAGMessageParser.parse(text)

    stmt = message.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.topic == "system.*"


# --- Round-trip minify ---


def test_sub_round_trip():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.*"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "SUB system.*" in minified

    reparsed = SAGMessageParser.parse(minified)
    assert len(reparsed.statements) == 1
    assert isinstance(reparsed.statements[0], SubscribeStatement)
    assert reparsed.statements[0].topic == "system.*"


def test_sub_with_filter_round_trip():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nSUB system.** WHERE cpu>80"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "SUB system.**" in minified
    assert "WHERE" in minified

    reparsed = SAGMessageParser.parse(minified)
    stmt = reparsed.statements[0]
    assert isinstance(stmt, SubscribeStatement)
    assert stmt.topic == "system.**"
    assert stmt.filter_expr is not None


def test_unsub_round_trip():
    text = "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nUNSUB system.*"
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "UNSUB system.*" in minified

    reparsed = SAGMessageParser.parse(minified)
    assert isinstance(reparsed.statements[0], UnsubscribeStatement)
    assert reparsed.statements[0].topic == "system.*"


def test_know_round_trip():
    text = 'H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\nKNOW deployment.status = "healthy" v 1'
    message = SAGMessageParser.parse(text)
    minified = MessageMinifier.to_minified_string(message)

    assert "KNOW deployment.status" in minified
    assert "v 1" in minified

    reparsed = SAGMessageParser.parse(minified)
    stmt = reparsed.statements[0]
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.topic == "deployment.status"
    assert stmt.value == "healthy"
    assert stmt.version == 1


def test_mixed_statements_with_knowledge():
    text = (
        "H v 1 id=msg1 src=svc1 dst=svc2 ts=1234567890\n"
        'DO start(); SUB system.*; KNOW system.cpu = 85 v 3'
    )
    message = SAGMessageParser.parse(text)

    assert len(message.statements) == 3
    assert isinstance(message.statements[0], ActionStatement)
    assert isinstance(message.statements[1], SubscribeStatement)
    assert isinstance(message.statements[2], KnowledgeStatement)


# --- KnowledgeEngine: basic lifecycle ---


def test_engine_assert_and_get():
    engine = KnowledgeEngine("agent-a")

    stmt = engine.assert_fact("system.cpu", 85)
    assert isinstance(stmt, KnowledgeStatement)
    assert stmt.topic == "system.cpu"
    assert stmt.value == 85
    assert stmt.version == 1

    result = engine.get_fact("system.cpu")
    assert result == (85, 1)

    assert engine.get_fact("nonexistent") is None


def test_engine_version_increments():
    engine = KnowledgeEngine("agent-a")

    engine.assert_fact("a", 1)
    engine.assert_fact("b", 2)
    engine.assert_fact("c", 3)

    assert engine.get_local_version() == 3
    assert engine.get_fact("a")[1] == 1
    assert engine.get_fact("c")[1] == 3


def test_engine_overwrite_fact():
    engine = KnowledgeEngine("agent-a")

    engine.assert_fact("system.cpu", 50)
    engine.assert_fact("system.cpu", 85)

    result = engine.get_fact("system.cpu")
    assert result == (85, 2)


def test_engine_query_facts():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("system.cpu", 85)
    engine.assert_fact("system.mem", 70)
    engine.assert_fact("app.errors", 3)

    results = engine.query_facts("system.*")
    assert len(results) == 2
    assert "system.cpu" in results
    assert "system.mem" in results
    assert "app.errors" not in results


# --- KnowledgeEngine: subscriptions ---


def test_engine_subscribe_unsubscribe():
    engine = KnowledgeEngine("agent-a")

    sub_stmt = engine.subscribe("system.*")
    assert isinstance(sub_stmt, SubscribeStatement)
    assert "system.*" in engine.get_subscriptions()

    assert engine.is_interested("system.cpu") is True
    assert engine.is_interested("app.errors") is False

    unsub_stmt = engine.unsubscribe("system.*")
    assert isinstance(unsub_stmt, UnsubscribeStatement)
    assert "system.*" not in engine.get_subscriptions()
    assert engine.is_interested("system.cpu") is False


# --- KnowledgeEngine: propagation ---


def test_engine_compute_delta():
    engine = KnowledgeEngine("agent-a")

    engine.add_subscriber("agent-b", "system.*")

    engine.assert_fact("system.cpu", 85)
    engine.assert_fact("system.mem", 70)
    engine.assert_fact("app.errors", 3)

    delta = engine.compute_delta("agent-b")
    topics = {s.topic for s in delta}
    assert topics == {"system.cpu", "system.mem"}
    assert len(delta) == 2


def test_engine_delta_respects_version_vector():
    engine = KnowledgeEngine("agent-a")
    engine.add_subscriber("agent-b", "system.*")

    engine.assert_fact("system.cpu", 50)
    engine.assert_fact("system.mem", 60)

    engine.acknowledge_sync("agent-b", 2)

    engine.assert_fact("system.cpu", 85)

    delta = engine.compute_delta("agent-b")
    assert len(delta) == 1
    assert delta[0].topic == "system.cpu"
    assert delta[0].value == 85


def test_engine_apply_incoming():
    engine = KnowledgeEngine("agent-b")

    incoming = [
        KnowledgeStatement(topic="system.cpu", value=85, version=3),
        KnowledgeStatement(topic="system.mem", value=70, version=2),
    ]

    applied = engine.apply_incoming(incoming, "agent-a")
    assert len(applied) == 2
    assert engine.get_fact("system.cpu") == (85, 3)
    assert engine.get_fact("system.mem") == (70, 2)


def test_engine_apply_incoming_ignores_stale():
    engine = KnowledgeEngine("agent-b")

    engine.apply_incoming(
        [KnowledgeStatement(topic="system.cpu", value=85, version=3)], "agent-a"
    )

    applied = engine.apply_incoming(
        [KnowledgeStatement(topic="system.cpu", value=50, version=1)], "agent-a"
    )
    assert len(applied) == 0
    assert engine.get_fact("system.cpu") == (85, 3)


def test_engine_subscriber_management():
    engine = KnowledgeEngine("agent-a")

    engine.add_subscriber("agent-b", "system.*")
    engine.add_subscriber("agent-b", "app.*")
    engine.add_subscriber("agent-c", "system.**")

    subs = engine.get_subscribers()
    assert subs["agent-b"] == {"system.*", "app.*"}
    assert subs["agent-c"] == {"system.**"}

    engine.remove_subscriber("agent-b", "system.*")
    subs = engine.get_subscribers()
    assert subs["agent-b"] == {"app.*"}

    engine.remove_subscriber("agent-b", "app.*")
    assert "agent-b" not in engine.get_subscribers()


# --- KnowledgeEngine: auto-fold ---


def test_engine_knowledge_pressure():
    engine = KnowledgeEngine("agent-a", knowledge_budget=10)

    for i in range(5):
        engine.assert_fact(f"topic.{i}", i)

    assert engine.get_knowledge_pressure() == 0.5

    for i in range(5, 10):
        engine.assert_fact(f"topic.{i}", i)

    assert engine.get_knowledge_pressure() == 1.0


def test_engine_auto_fold():
    fold_engine = FoldEngine()
    engine = KnowledgeEngine("agent-a", fold_engine=fold_engine, knowledge_budget=5)

    engine.add_subscriber("agent-b", "topic.*")
    engine.acknowledge_sync("agent-b", 100)

    for i in range(10):
        engine.assert_fact(f"topic.{i}", i)

    fold_stmt = engine._auto_fold()
    assert fold_stmt is not None
    assert isinstance(fold_stmt, FoldStatement)
    assert engine.get_fact_count() <= 5


def test_engine_auto_fold_no_engine():
    engine = KnowledgeEngine("agent-a", knowledge_budget=2)

    for i in range(5):
        engine.assert_fact(f"topic.{i}", i)

    result = engine._auto_fold()
    assert result is None


# --- KnowledgeEngine: get_all_facts ---


def test_engine_get_all_facts():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("system.cpu", 85)
    engine.assert_fact("system.mem", 70)
    engine.assert_fact("app.errors", 3)

    facts = engine.get_all_facts()
    assert len(facts) == 3
    assert facts["system.cpu"] == (85, 1)
    assert facts["system.mem"] == (70, 2)
    assert facts["app.errors"] == (3, 3)


def test_engine_get_all_facts_returns_copy():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("a", 1)

    facts = engine.get_all_facts()
    facts["b"] = (2, 99)

    assert engine.get_fact("b") is None


# --- KnowledgeEngine: clear ---


# --- KnowledgeEngine: delete_fact ---


def test_engine_delete_fact():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("system.cpu", 85)
    engine.assert_fact("system.mem", 70)

    assert engine.delete_fact("system.cpu") is True
    assert engine.get_fact("system.cpu") is None
    assert engine.get_fact("system.mem") == (70, 2)
    assert engine.get_fact_count() == 1


def test_engine_delete_fact_nonexistent():
    engine = KnowledgeEngine("agent-a")
    assert engine.delete_fact("nonexistent") is False


# --- KnowledgeEngine: load_state ---


def test_engine_load_state():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("old", "data")

    new_facts = {
        "system.cpu": (85, 3),
        "system.mem": (70, 2),
    }
    engine.load_state(new_facts, 5)

    assert engine.get_local_version() == 5
    assert engine.get_fact("system.cpu") == (85, 3)
    assert engine.get_fact("system.mem") == (70, 2)
    assert engine.get_fact("old") is None
    assert engine.get_fact_count() == 2


def test_engine_load_state_does_not_share_reference():
    engine = KnowledgeEngine("agent-a")
    facts = {"a": (1, 1)}
    engine.load_state(facts, 1)
    facts["b"] = (2, 2)
    assert engine.get_fact("b") is None


# --- KnowledgeEngine: clear ---


def test_engine_clear():
    engine = KnowledgeEngine("agent-a")
    engine.assert_fact("system.cpu", 85)
    engine.subscribe("system.*")
    engine.add_subscriber("agent-b", "system.*")

    engine.clear()

    assert engine.get_fact_count() == 0
    assert engine.get_local_version() == 0
    assert len(engine.get_subscriptions()) == 0
    assert len(engine.get_subscribers()) == 0
