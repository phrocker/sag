import pytest

from sag.tree import TreeEngine
from sag.grove import (
    EchoAgentRunner,
    InteractiveGrove,
    StepResult,
    GroveResult,
)
from sag.checkpoint import CheckpointManager
from sag.model import Message


def _build_simple_tree() -> TreeEngine:
    """Root -> [A, B]"""
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["plan.summary"])
    tree.add_child("root", "a", "Agent A", topics=["a.result"])
    tree.add_child("root", "b", "Agent B", topics=["b.result"])
    return tree


def _build_deep_tree() -> TreeEngine:
    """Root -> Lead -> [W1, W2]"""
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["project.plan"])
    tree.add_child("root", "lead", "Lead", topics=["lead.summary"])
    tree.add_child("lead", "w1", "Worker 1", topics=["w1.output"])
    tree.add_child("lead", "w2", "Worker 2", topics=["w2.output"])
    return tree


# --- Setup ---


def test_setup_returns_levels():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    levels = ig.setup("Build API")

    assert len(levels) == 2
    # First level: leaves [a, b]
    assert {n.agent_id for n in levels[0]} == {"a", "b"}
    # Second level: root
    assert {n.agent_id for n in levels[1]} == {"root"}


def test_step_before_setup_raises():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    with pytest.raises(RuntimeError, match="setup"):
        ig.step()


# --- Step-by-step execution ---


def test_step_processes_one_level():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("Build API")

    step = ig.step()
    assert isinstance(step, StepResult)
    assert step.level == 0
    assert step.total_levels == 2
    assert set(step.agents_run) == {"a", "b"}
    assert "a" in step.facts_produced
    assert "b" in step.facts_produced
    assert step.is_complete is False


def test_step_then_complete():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("Build API")

    step1 = ig.step()
    assert step1.is_complete is False

    step2 = ig.step()
    assert step2.is_complete is True
    assert step2.agents_run == ["root"]


def test_step_past_end_raises():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")
    ig.step()  # level 0
    ig.step()  # level 1
    with pytest.raises(RuntimeError, match="complete"):
        ig.step()


def test_complete_runs_all_remaining():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("Build API")

    result = ig.complete()
    assert isinstance(result, GroveResult)
    assert result.agents_run == 3
    assert result.levels_processed == 2
    assert len(result.facts) > 0


def test_step_then_complete_result():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("Build API")

    ig.step()  # leaves
    result = ig.complete()  # runs root

    assert result.agents_run == 3
    assert result.levels_processed == 2


def test_deep_tree_step_ordering():
    tree = _build_deep_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("Deploy")

    step1 = ig.step()  # workers
    assert set(step1.agents_run) == {"w1", "w2"}

    step2 = ig.step()  # lead
    assert step2.agents_run == ["lead"]

    step3 = ig.step()  # root
    assert step3.agents_run == ["root"]
    assert step3.is_complete is True


# --- Propagation messages ---


def test_step_captures_messages():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")

    step = ig.step()
    # Leaves propagate to root
    assert len(step.messages) == 2
    for msg in step.messages:
        assert isinstance(msg, Message)


# --- Inspect and edit ---


def test_inspect_node():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")
    ig.step()  # run leaves

    facts = ig.inspect_node("a")
    assert "a.result" in facts


def test_inspect_unknown_raises():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")
    with pytest.raises(KeyError):
        ig.inspect_node("nonexistent")


def test_edit_fact():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")
    ig.step()

    ig.edit_fact("a", "a.override", "manual edit")
    facts = ig.inspect_node("a")
    assert facts["a.override"][0] == "manual edit"


# --- Callbacks ---


def test_callbacks_fire():
    starts = []
    dones = []
    props = []

    tree = _build_simple_tree()
    ig = InteractiveGrove(
        tree,
        EchoAgentRunner(),
        on_agent_start=lambda n, t: starts.append(n.agent_id),
        on_agent_done=lambda n, f: dones.append(n.agent_id),
        on_propagate=lambda c, p, m: props.append((c.agent_id, p.agent_id)),
    )
    ig.setup("task")
    ig.complete()

    assert set(starts) == {"root", "a", "b"}
    assert set(dones) == {"root", "a", "b"}
    assert len(props) == 2


# --- Checkpointing ---


def test_checkpoint_and_rollback(tmp_path):
    tree = _build_simple_tree()
    mgr = CheckpointManager(tmp_path)
    ig = InteractiveGrove(tree, EchoAgentRunner(), checkpoint_mgr=mgr)
    ig.setup("task")

    ig.step()  # run leaves
    cp_id = ig.checkpoint()

    # Mutate
    ig.edit_fact("a", "a.extra", "mutated")
    assert "a.extra" in ig.inspect_node("a")

    # Rollback
    ig.rollback(cp_id)
    assert "a.extra" not in ig.inspect_node("a")


def test_checkpoint_no_mgr_raises():
    tree = _build_simple_tree()
    ig = InteractiveGrove(tree, EchoAgentRunner())
    ig.setup("task")
    with pytest.raises(RuntimeError, match="CheckpointManager"):
        ig.checkpoint()


def test_list_checkpoints(tmp_path):
    tree = _build_simple_tree()
    mgr = CheckpointManager(tmp_path)
    ig = InteractiveGrove(tree, EchoAgentRunner(), checkpoint_mgr=mgr)
    ig.setup("task")
    ig.step()
    ig.checkpoint()
    ig.checkpoint()

    cps = ig.list_checkpoints()
    assert len(cps) == 2


def test_rollback_restores_level(tmp_path):
    tree = _build_simple_tree()
    mgr = CheckpointManager(tmp_path)
    ig = InteractiveGrove(tree, EchoAgentRunner(), checkpoint_mgr=mgr)
    ig.setup("task")

    ig.step()  # level 0
    cp_id = ig.checkpoint()

    ig.step()  # level 1

    ig.rollback(cp_id)
    # After rollback we should be back to level 1 (current_level was 1 after step 0)
    # We can step again to run root
    step = ig.step()
    assert step.agents_run == ["root"]
    assert step.is_complete is True
