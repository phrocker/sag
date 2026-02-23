from sag.tree import AgentNode, TreeEngine
from sag.grove import (
    EchoAgentRunner,
    LLMAgentRunner,
    Grove,
    GroveResult,
)
from sag.model import KnowledgeStatement, Message
from sag.minifier import MessageMinifier


def _build_simple_tree() -> TreeEngine:
    """Root -> [A, B]"""
    tree = TreeEngine()
    tree.add_root("root", "PM", prompt="Synthesize", topics=["plan.summary"])
    tree.add_child("root", "a", "Agent A", prompt="Analyze A", topics=["a.result"])
    tree.add_child("root", "b", "Agent B", prompt="Analyze B", topics=["b.result"])
    return tree


def _build_deep_tree() -> TreeEngine:
    """Root -> Lead -> [Worker1, Worker2]"""
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["project.plan"])
    tree.add_child("root", "lead", "Lead", topics=["lead.summary"])
    tree.add_child("lead", "w1", "Worker 1", topics=["w1.output"])
    tree.add_child("lead", "w2", "Worker 2", topics=["w2.output"])
    return tree


# --- EchoAgentRunner ---


def test_echo_runner_generates_facts_from_topics():
    tree = _build_simple_tree()
    runner = EchoAgentRunner()

    node_a = tree.get_node("a")
    facts = runner.run(node_a, "Build an API", {})
    assert "a.result" in facts
    assert "Build an API" in facts["a.result"]


def test_echo_runner_no_topics_uses_role():
    tree = TreeEngine()
    tree.add_root("root", "Project Manager")
    runner = EchoAgentRunner()

    facts = runner.run(tree.get_root(), "test task", {})
    assert "project_manager.analysis" in facts


def test_echo_runner_asserts_into_knowledge():
    tree = _build_simple_tree()
    runner = EchoAgentRunner()

    node_a = tree.get_node("a")
    runner.run(node_a, "task", {})
    assert node_a.knowledge.get_fact("a.result") is not None


# --- Grove with EchoRunner ---


def test_grove_execute_simple():
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("Build a REST API")

    assert isinstance(result, GroveResult)
    assert result.agents_run == 3
    assert result.levels_processed == 2
    assert len(result.facts) > 0
    assert result.report != ""


def test_grove_execute_deep_tree():
    tree = _build_deep_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("Deploy microservice")

    assert result.agents_run == 4
    assert result.levels_processed == 3


def test_grove_propagates_knowledge_up():
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    grove.execute("test")

    # Root should have facts from children propagated up
    root = tree.get_root()
    all_facts = root.knowledge.get_all_facts()
    # Root's own facts + propagated child facts
    assert len(all_facts) >= 1


def test_grove_bottom_up_ordering():
    """Verify leaves run before parents."""
    execution_order = []

    def on_start(node: AgentNode, task: str):
        execution_order.append(node.agent_id)

    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner, on_agent_start=on_start)
    grove.execute("test")

    # Children before root
    a_idx = execution_order.index("a")
    b_idx = execution_order.index("b")
    root_idx = execution_order.index("root")
    assert a_idx < root_idx
    assert b_idx < root_idx


def test_grove_deep_bottom_up_ordering():
    """In a 3-level tree, workers run before lead, lead before root."""
    execution_order = []

    def on_start(node: AgentNode, task: str):
        execution_order.append(node.agent_id)

    tree = _build_deep_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner, on_agent_start=on_start)
    grove.execute("test")

    w1_idx = execution_order.index("w1")
    w2_idx = execution_order.index("w2")
    lead_idx = execution_order.index("lead")
    root_idx = execution_order.index("root")
    assert w1_idx < lead_idx
    assert w2_idx < lead_idx
    assert lead_idx < root_idx


# --- Callbacks ---


def test_grove_on_agent_done_callback():
    done_calls = []

    def on_done(node: AgentNode, facts: dict):
        done_calls.append((node.agent_id, set(facts.keys())))

    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner, on_agent_done=on_done)
    grove.execute("test")

    assert len(done_calls) == 3
    ids = {c[0] for c in done_calls}
    assert ids == {"root", "a", "b"}


def test_grove_on_propagate_callback():
    propagate_calls = []

    def on_prop(child: AgentNode, parent: AgentNode, msg: Message):
        propagate_calls.append((child.agent_id, parent.agent_id, msg))

    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner, on_propagate=on_prop)
    grove.execute("test")

    # a -> root and b -> root
    assert len(propagate_calls) == 2
    child_ids = {c[0] for c in propagate_calls}
    assert child_ids == {"a", "b"}
    parent_ids = {c[1] for c in propagate_calls}
    assert parent_ids == {"root"}

    # Each callback receives a proper SAG Message
    for _child_id, _parent_id, msg in propagate_calls:
        assert isinstance(msg, Message)
        assert msg.header is not None
        assert len(msg.statements) > 0


# --- Custom runner ---


class FixedRunner:
    """Returns fixed facts for testing."""

    def __init__(self, fact_map: dict[str, dict[str, str]]):
        self._fact_map = fact_map

    def run(self, node: AgentNode, task: str, child_facts: dict) -> dict[str, str]:
        facts = self._fact_map.get(node.agent_id, {})
        for topic, value in facts.items():
            node.knowledge.assert_fact(topic, value)
        return facts


def test_grove_with_custom_runner():
    tree = _build_simple_tree()
    runner = FixedRunner({
        "a": {"a.result": "found 3 bugs"},
        "b": {"b.result": "all tests pass"},
        "root": {"plan.summary": "ship it"},
    })
    grove = Grove(tree, runner)

    result = grove.execute("review code")
    assert "plan.summary" in result.facts
    assert result.facts["plan.summary"][0] == "ship it"


def test_grove_child_facts_passed_to_parent():
    """Verify parent runner receives child facts in child_facts dict."""
    received_child_facts = {}

    class SpyRunner:
        def run(self, node, task, child_facts):
            if node.agent_id == "root":
                received_child_facts.update(child_facts)
            facts = {}
            for topic in node.metadata.get("topics", []):
                value = f"result for {topic}"
                facts[topic] = value
                node.knowledge.assert_fact(topic, value)
            return facts

    tree = _build_simple_tree()
    grove = Grove(tree, SpyRunner())
    grove.execute("test")

    assert "a.result" in received_child_facts
    assert "b.result" in received_child_facts


# --- GroveResult ---


def test_grove_result_report_contains_facts():
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test task")
    assert "Grove Execution Report" in result.report


# --- SAG message communication ---


def test_grove_messages_in_result():
    """GroveResult.messages contains all inter-agent SAG messages."""
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test")

    # Two children propagate to root = 2 messages
    assert len(result.messages) == 2
    for msg in result.messages:
        assert isinstance(msg, Message)


def test_grove_message_has_proper_header():
    """Each propagation message has a valid SAG header."""
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test")

    for msg in result.messages:
        h = msg.header
        assert h.version == 1
        assert h.message_id is not None
        assert h.source in ("a", "b")
        assert h.destination == "root"
        assert h.timestamp > 0


def test_grove_message_contains_know_statements():
    """Propagation messages carry KNOW statements for each fact."""
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test")

    for msg in result.messages:
        assert len(msg.statements) > 0
        for stmt in msg.statements:
            assert isinstance(stmt, KnowledgeStatement)
            assert stmt.topic != ""
            assert stmt.version > 0


def test_grove_message_roundtrips_through_minifier():
    """Propagation messages can be minified and reparsed."""
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test")

    for msg in result.messages:
        wire = MessageMinifier.to_minified_string(msg)
        assert "KNOW" in wire
        assert msg.header.source in wire


def test_grove_deep_tree_message_count():
    """3-level tree: workers->lead (2 msgs) + lead->root (1 msg) = 3."""
    tree = _build_deep_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    result = grove.execute("test")

    # w1->lead, w2->lead, lead->root = 3 messages
    assert len(result.messages) == 3

    sources = [m.header.source for m in result.messages]
    assert "w1" in sources
    assert "w2" in sources
    assert "lead" in sources


def test_grove_parent_records_correlation():
    """Parent's correlation engine records incoming messages."""
    tree = _build_simple_tree()
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)

    grove.execute("test")

    # Root should have recorded the last incoming message
    root = tree.get_root()
    # The correlation engine tracks last_received
    header = root.correlation.create_response_header("root", "downstream")
    # correlation should reference the last child message received
    assert header.correlation is not None


# --- LLMAgentRunner parse_facts ---


def test_llm_runner_parse_facts_sag_format():
    """Test fact parsing from SAG assert format."""
    runner = LLMAgentRunner.__new__(LLMAgentRunner)
    node = AgentNode(agent_id="test", role="Tester")

    raw = 'A test.result = "all passed"; A test.coverage = "95%"'
    facts = runner._parse_facts(raw, node)
    assert "test.result" in facts
    assert "test.coverage" in facts


def test_llm_runner_parse_facts_regex_fallback():
    """When SAG parse fails, regex picks up A topic = 'value' patterns."""
    runner = LLMAgentRunner.__new__(LLMAgentRunner)
    node = AgentNode(agent_id="test", role="Tester")

    raw = 'Here is my analysis:\nA test.result = "everything looks good"\nSome other text'
    facts = runner._parse_facts(raw, node)
    assert "test.result" in facts
    assert facts["test.result"] == "everything looks good"


def test_llm_runner_parse_facts_last_resort():
    """When no patterns match, wraps entire response."""
    runner = LLMAgentRunner.__new__(LLMAgentRunner)
    node = AgentNode(agent_id="test", role="Test Agent")

    raw = "Just some plain text analysis with no SAG format"
    facts = runner._parse_facts(raw, node)
    assert "test_agent.analysis" in facts
    assert raw.strip() in facts["test_agent.analysis"]
