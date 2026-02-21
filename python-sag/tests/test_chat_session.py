import pytest

from sag.tree import TreeEngine
from sag.grove import (
    ChatResponse,
    ChatSession,
    EchoAgentRunner,
    Grove,
    GroveResult,
)
from sag.checkpoint import CheckpointManager
from sag.model import Message, KnowledgeStatement


def _build_tree_and_run() -> tuple[TreeEngine, GroveResult]:
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["plan.summary"])
    tree.add_child("root", "a", "Agent A", topics=["a.result"])
    tree.add_child("root", "b", "Agent B", topics=["b.result"])

    runner = EchoAgentRunner()
    grove = Grove(tree, runner)
    result = grove.execute("Build an API")
    return tree, result


# --- Basic chat ---


def test_chat_returns_response():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    resp = session.chat("Improve the design")
    assert isinstance(resp, ChatResponse)
    assert resp.reply != ""
    assert len(resp.facts_updated) > 0


def test_chat_updates_root_facts():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    resp = session.chat("Add caching layer")
    # EchoAgentRunner produces facts based on topics
    assert "plan.summary" in resp.facts_updated


def test_chat_produces_message():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    resp = session.chat("Refactor")
    assert resp.message is not None
    assert isinstance(resp.message, Message)
    assert resp.message.header.source == "root"
    assert resp.message.header.destination == "user"
    assert len(resp.message.statements) > 0
    for stmt in resp.message.statements:
        assert isinstance(stmt, KnowledgeStatement)


# --- Multi-turn ---


def test_chat_multi_turn():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    r1 = session.chat("First question")
    r2 = session.chat("Second question")

    assert r1.reply != ""
    assert r2.reply != ""
    # Facts should reflect the latest query
    assert len(r2.facts_updated) > 0


# --- Checkpointing ---


def test_chat_checkpoint_and_rollback(tmp_path):
    tree, result = _build_tree_and_run()
    mgr = CheckpointManager(tmp_path)
    session = ChatSession(result, tree, EchoAgentRunner(), checkpoint_mgr=mgr)

    # Chat once
    session.chat("Initial feedback")
    cp_id = session.checkpoint()

    # Get facts after checkpoint
    original_version = tree.get_root().knowledge.get_local_version()

    # Chat more (mutates state)
    session.chat("More feedback")
    assert tree.get_root().knowledge.get_local_version() > original_version

    # Rollback
    session.rollback(cp_id)
    assert tree.get_root().knowledge.get_local_version() == original_version


def test_chat_checkpoint_no_mgr_raises():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    with pytest.raises(RuntimeError, match="CheckpointManager"):
        session.checkpoint()


def test_chat_rollback_no_mgr_raises():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    with pytest.raises(RuntimeError, match="CheckpointManager"):
        session.rollback("some-id")


# --- History ---


def test_chat_history_builds_up():
    tree, result = _build_tree_and_run()
    session = ChatSession(result, tree, EchoAgentRunner())

    session.chat("Q1")
    session.chat("Q2")
    session.chat("Q3")

    assert len(session._history) == 3
    assert session._history[0][0] == "Q1"
    assert session._history[2][0] == "Q3"


def test_chat_rollback_clears_history(tmp_path):
    tree, result = _build_tree_and_run()
    mgr = CheckpointManager(tmp_path)
    session = ChatSession(result, tree, EchoAgentRunner(), checkpoint_mgr=mgr)

    cp_id = session.checkpoint()
    session.chat("Q1")
    assert len(session._history) == 1

    session.rollback(cp_id)
    assert len(session._history) == 0
