import pytest

from sag.tree import AgentNode, TreeEngine
from sag.knowledge import KnowledgeEngine
from sag.correlation import CorrelationEngine


# --- AgentNode basics ---


def test_agent_node_auto_creates_engines():
    node = AgentNode(agent_id="a1", role="worker")
    assert isinstance(node.knowledge, KnowledgeEngine)
    assert isinstance(node.correlation, CorrelationEngine)


def test_agent_node_leaf_and_root():
    root = AgentNode(agent_id="root", role="PM")
    child = AgentNode(agent_id="child", role="dev", parent=root)
    root.children.append(child)

    assert root.is_root is True
    assert root.is_leaf is False
    assert child.is_root is False
    assert child.is_leaf is True


def test_agent_node_metadata():
    node = AgentNode(agent_id="a1", role="worker", metadata={"prompt": "Do stuff"})
    assert node.metadata["prompt"] == "Do stuff"


# --- TreeEngine: node management ---


def test_add_root():
    tree = TreeEngine()
    root = tree.add_root("pm", "Project Manager", prompt="Synthesize")
    assert root.agent_id == "pm"
    assert root.role == "Project Manager"
    assert root.metadata["prompt"] == "Synthesize"
    assert root.is_root is True


def test_add_root_twice_raises():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    with pytest.raises(ValueError, match="already has a root"):
        tree.add_root("pm2", "PM2")


def test_add_child():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    child = tree.add_child("pm", "dev", "Developer")
    assert child.parent.agent_id == "pm"
    assert child.role == "Developer"
    assert child in tree.get_root().children


def test_add_child_missing_parent_raises():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    with pytest.raises(KeyError, match="not found"):
        tree.add_child("nonexistent", "dev", "Developer")


def test_add_child_duplicate_id_raises():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    tree.add_child("pm", "dev", "Developer")
    with pytest.raises(ValueError, match="already exists"):
        tree.add_child("pm", "dev", "Developer 2")


def test_get_node():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    tree.add_child("pm", "dev", "Developer")

    assert tree.get_node("pm").role == "PM"
    assert tree.get_node("dev").role == "Developer"
    assert tree.get_node("nonexistent") is None


def test_get_all_node_ids():
    tree = _build_grove_tree()
    ids = tree.get_all_node_ids()
    assert set(ids) == {
        "pm", "design-lead", "eng-lead", "qa-lead",
        "ui", "ux", "api", "frontend", "test", "security",
    }


def test_get_all_node_ids_empty():
    tree = TreeEngine()
    assert tree.get_all_node_ids() == []


def test_get_root_empty_raises():
    tree = TreeEngine()
    with pytest.raises(ValueError, match="no root"):
        tree.get_root()


# --- TreeEngine: traversal ---


def _build_grove_tree() -> TreeEngine:
    """Build the software dev grove tree for testing."""
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    tree.add_child("pm", "design-lead", "Design Lead")
    tree.add_child("pm", "eng-lead", "Engineering Lead")
    tree.add_child("pm", "qa-lead", "QA Lead")
    tree.add_child("design-lead", "ui", "UI Agent")
    tree.add_child("design-lead", "ux", "UX Agent")
    tree.add_child("eng-lead", "api", "API Agent")
    tree.add_child("eng-lead", "frontend", "Frontend Agent")
    tree.add_child("qa-lead", "test", "Test Agent")
    tree.add_child("qa-lead", "security", "Security Agent")
    return tree


def test_get_leaves():
    tree = _build_grove_tree()
    leaves = tree.get_leaves()
    leaf_ids = {n.agent_id for n in leaves}
    assert leaf_ids == {"ui", "ux", "api", "frontend", "test", "security"}


def test_get_levels_bottom_up():
    tree = _build_grove_tree()
    levels = tree.get_levels_bottom_up()

    assert len(levels) == 3
    # Level 0 (deepest): leaves
    assert {n.agent_id for n in levels[0]} == {
        "ui", "ux", "api", "frontend", "test", "security"
    }
    # Level 1: leads
    assert {n.agent_id for n in levels[1]} == {
        "design-lead", "eng-lead", "qa-lead"
    }
    # Level 2: root
    assert {n.agent_id for n in levels[2]} == {"pm"}


def test_get_levels_single_node():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    levels = tree.get_levels_bottom_up()
    assert len(levels) == 1
    assert levels[0][0].agent_id == "pm"


def test_get_levels_empty_tree():
    tree = TreeEngine()
    assert tree.get_levels_bottom_up() == []


def test_get_depth():
    tree = _build_grove_tree()
    assert tree.get_depth() == 2


def test_get_depth_single_node():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    assert tree.get_depth() == 0


def test_get_depth_empty():
    tree = TreeEngine()
    assert tree.get_depth() == 0


# --- TreeEngine: knowledge propagation ---


def test_setup_subscriptions():
    tree = _build_grove_tree()
    tree.setup_subscriptions("**")

    # Child "ui" should have parent "design-lead" as subscriber
    ui = tree.get_node("ui")
    subs = ui.knowledge.get_subscribers()
    assert "design-lead" in subs
    assert "**" in subs["design-lead"]


def test_propagate_up():
    tree = _build_grove_tree()
    tree.setup_subscriptions("**")

    ui = tree.get_node("ui")
    ui.knowledge.assert_fact("ui.components", "3 major components identified")

    applied = tree.propagate_up("ui")
    assert len(applied) == 1
    assert applied[0].topic == "ui.components"

    design_lead = tree.get_node("design-lead")
    fact = design_lead.knowledge.get_fact("ui.components")
    assert fact is not None
    assert fact[0] == "3 major components identified"


def test_propagate_up_multiple_facts():
    tree = _build_grove_tree()
    tree.setup_subscriptions("**")

    api = tree.get_node("api")
    api.knowledge.assert_fact("api.endpoints", "5 REST endpoints")
    api.knowledge.assert_fact("api.auth", "JWT-based auth")

    applied = tree.propagate_up("api")
    assert len(applied) == 2

    eng = tree.get_node("eng-lead")
    assert eng.knowledge.get_fact("api.endpoints") is not None
    assert eng.knowledge.get_fact("api.auth") is not None


def test_propagate_up_root_is_noop():
    tree = _build_grove_tree()
    tree.setup_subscriptions("**")

    result = tree.propagate_up("pm")
    assert result == []


def test_propagate_up_unknown_node_raises():
    tree = _build_grove_tree()
    with pytest.raises(KeyError, match="not found"):
        tree.propagate_up("nonexistent")


def test_propagate_up_chain():
    """Propagate from leaf → middle → root across two levels."""
    tree = _build_grove_tree()
    tree.setup_subscriptions("**")

    ui = tree.get_node("ui")
    ui.knowledge.assert_fact("ui.layout", "grid-based")

    # Leaf → middle
    tree.propagate_up("ui")
    design = tree.get_node("design-lead")
    assert design.knowledge.get_fact("ui.layout") is not None

    # Middle → root
    tree.propagate_up("design-lead")
    pm = tree.get_node("pm")
    assert pm.knowledge.get_fact("ui.layout") is not None


# --- TreeEngine: render_ascii ---


def test_render_ascii():
    tree = _build_grove_tree()
    output = tree.render_ascii()

    assert "PM (pm)" in output
    assert "Design Lead (design-lead)" in output
    assert "UI Agent (ui)" in output
    assert "Security Agent (security)" in output


def test_render_ascii_empty():
    tree = TreeEngine()
    assert tree.render_ascii() == "(empty tree)"


def test_render_ascii_single_node():
    tree = TreeEngine()
    tree.add_root("pm", "PM")
    output = tree.render_ascii()
    assert "PM (pm)" in output
