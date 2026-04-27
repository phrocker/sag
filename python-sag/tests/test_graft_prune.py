"""Tests for graft/prune operations on TreeEngine."""

import pytest

from sag.fold import FoldEngine
from sag.tree import AgentNode, TreeEngine


class TestGraft:
    def test_graft_adds_child(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.graft("root", "new-agent", "Reviewer")

        node = tree.get_node("new-agent")
        assert node is not None
        assert node.role == "Reviewer"
        assert node.parent.agent_id == "root"

    def test_graft_wires_subscription(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        node = tree.graft("root", "new-agent", "Reviewer")

        # The new agent should have root subscribed to its facts
        subscribers = node.knowledge.get_subscribers()
        assert "root" in subscribers

    def test_graft_to_nonexistent_parent(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        with pytest.raises(KeyError):
            tree.graft("nonexistent", "new-agent", "Reviewer")

    def test_graft_duplicate_id(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.graft("root", "child1", "Worker")
        with pytest.raises(ValueError):
            tree.graft("root", "child1", "Duplicate")

    def test_graft_to_non_root(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "mid", "Manager")
        tree.graft("mid", "leaf", "Worker")

        node = tree.get_node("leaf")
        assert node is not None
        assert node.parent.agent_id == "mid"

    def test_graft_with_metadata(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        node = tree.graft(
            "root", "agent", "Coder",
            prompt="Write clean code",
            topics=["code.quality"],
        )
        assert node.metadata["prompt"] == "Write clean code"
        assert node.metadata["topics"] == ["code.quality"]


class TestPrune:
    def test_prune_leaf(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        # Add some facts first
        child = tree.get_node("child")
        child.knowledge.assert_fact("test.fact", "value")

        pruned = tree.prune("child")
        assert "test.fact" in pruned
        assert tree.get_node("child") is None

    def test_prune_propagates_to_parent(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        child = tree.get_node("child")
        child.knowledge.assert_fact("analysis.result", "important finding")

        tree.prune("child")

        root = tree.get_root()
        fact = root.knowledge.get_fact("analysis.result")
        assert fact is not None
        assert fact[0] == "important finding"

    def test_prune_root_raises(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        with pytest.raises(ValueError, match="Cannot prune the root"):
            tree.prune("root")

    def test_prune_nonexistent_raises(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        with pytest.raises(KeyError):
            tree.prune("nonexistent")

    def test_prune_reparents_children(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "mid", "Manager")
        tree.add_child("mid", "leaf1", "Worker A")
        tree.add_child("mid", "leaf2", "Worker B")

        tree.prune("mid")

        # leaf1 and leaf2 should now be children of root
        root = tree.get_root()
        child_ids = {c.agent_id for c in root.children}
        assert "leaf1" in child_ids
        assert "leaf2" in child_ids
        assert "mid" not in child_ids

        # Check parent pointers
        assert tree.get_node("leaf1").parent.agent_id == "root"
        assert tree.get_node("leaf2").parent.agent_id == "root"

    def test_prune_with_fold_engine(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        child = tree.get_node("child")
        child.knowledge.assert_fact("analysis.code", "clean")
        child.knowledge.assert_fact("analysis.tests", "passing")

        fold_engine = FoldEngine()
        tree.prune("child", fold_engine=fold_engine)

        # Fold should have been created
        assert fold_engine.get_fold_count() == 1

    def test_prune_without_fold_engine(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        child = tree.get_node("child")
        child.knowledge.assert_fact("fact", "value")

        # Should not raise even without fold_engine
        pruned = tree.prune("child")
        assert "fact" in pruned


class TestRenderGroveView:
    def test_empty_tree(self):
        tree = TreeEngine()
        result = tree.render_grove_view()
        assert result == "(empty tree)"

    def test_basic_rendering(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        result = tree.render_grove_view()
        assert "Coordinator" in result
        assert "Worker" in result

    def test_active_decoration(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        tree.add_child("root", "child", "Worker")

        result = tree.render_grove_view(active_agents={"child"})
        assert "[ACTIVE]" in result

    def test_assert_decoration(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        root = tree.get_root()
        root.knowledge.assert_fact("test", "value")

        result = tree.render_grove_view()
        assert "[ASSERT:1]" in result

    def test_folded_decoration(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")

        fold = FoldEngine()
        fold.fold([], "test fold")

        result = tree.render_grove_view(fold_engine=fold)
        assert "[FOLDED:1]" in result

    def test_pressure_decoration(self):
        tree = TreeEngine()
        tree.add_root("root", "Coordinator")
        root = tree.get_root()

        # Set a low budget and add facts to exceed threshold
        root.knowledge._knowledge_budget = 10
        for i in range(8):
            root.knowledge.assert_fact(f"fact.{i}", f"value {i}")

        result = tree.render_grove_view()
        assert "[PRESSURE:" in result
