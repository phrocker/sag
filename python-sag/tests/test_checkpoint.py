from sag.checkpoint import CheckpointManager
from sag.tree import TreeEngine
from sag.grove import EchoAgentRunner, Grove


def _build_simple_tree() -> TreeEngine:
    tree = TreeEngine()
    tree.add_root("root", "PM", topics=["plan.summary"])
    tree.add_child("root", "a", "Agent A", topics=["a.result"])
    tree.add_child("root", "b", "Agent B", topics=["b.result"])
    return tree


def _run_grove(tree: TreeEngine):
    runner = EchoAgentRunner()
    grove = Grove(tree, runner)
    return grove.execute("test task")


# --- Save ---


def test_save_creates_file(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test task", result.messages, result.agents_run, 2, 2)

    assert (tmp_path / f"{meta.checkpoint_id}.json").exists()
    assert meta.task == "test task"
    assert meta.agents_run == 3
    assert len(meta.node_snapshots) == 3
    assert "root" in meta.node_snapshots
    assert "a" in meta.node_snapshots
    assert "b" in meta.node_snapshots


def test_save_captures_facts(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test", result.messages, result.agents_run, 2, 2)

    root_snap = meta.node_snapshots["root"]
    assert len(root_snap.facts) > 0
    assert root_snap.local_version > 0


def test_save_captures_messages(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test", result.messages, result.agents_run, 2, 2)

    assert len(meta.messages) == len(result.messages)
    for wire in meta.messages:
        assert "KNOW" in wire


# --- Load ---


def test_load_roundtrips(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test task", result.messages, result.agents_run, 1, 2)

    loaded = mgr.load(meta.checkpoint_id)
    assert loaded.checkpoint_id == meta.checkpoint_id
    assert loaded.task == "test task"
    assert loaded.agents_run == 3
    assert loaded.current_level == 1
    assert loaded.total_levels == 2
    assert len(loaded.node_snapshots) == 3
    assert len(loaded.messages) == len(meta.messages)


def test_load_nonexistent_raises(tmp_path):
    mgr = CheckpointManager(tmp_path)
    try:
        mgr.load("nonexistent")
        assert False, "Should have raised"
    except FileNotFoundError:
        pass


# --- Restore ---


def test_restore_resets_facts(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test", result.messages, result.agents_run, 2, 2)

    # Save original state
    original_facts = tree.get_root().knowledge.get_all_facts()

    # Mutate state
    tree.get_root().knowledge.assert_fact("new.fact", "mutated")

    # Restore
    loaded = mgr.load(meta.checkpoint_id)
    mgr.restore(loaded, tree)

    restored_facts = tree.get_root().knowledge.get_all_facts()
    assert "new.fact" not in restored_facts
    assert restored_facts == original_facts


def test_restore_resets_correlation(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test", result.messages, result.agents_run, 2, 2)

    original_state = tree.get_root().correlation.get_state()

    # Mutate
    tree.get_root().correlation.clear()

    # Restore
    loaded = mgr.load(meta.checkpoint_id)
    mgr.restore(loaded, tree)

    assert tree.get_root().correlation.get_state() == original_state


# --- List ---


def test_list_checkpoints(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    mgr.save(tree, "task1", result.messages, result.agents_run, 1, 2)
    mgr.save(tree, "task2", result.messages, result.agents_run, 2, 2)

    cps = mgr.list_checkpoints()
    assert len(cps) == 2
    # Sorted by timestamp
    assert cps[0].timestamp <= cps[1].timestamp


def test_list_empty(tmp_path):
    mgr = CheckpointManager(tmp_path)
    assert mgr.list_checkpoints() == []


# --- Delete ---


def test_delete_checkpoint(tmp_path):
    tree = _build_simple_tree()
    result = _run_grove(tree)

    mgr = CheckpointManager(tmp_path)
    meta = mgr.save(tree, "test", result.messages, result.agents_run, 2, 2)

    mgr.delete(meta.checkpoint_id)
    assert not (tmp_path / f"{meta.checkpoint_id}.json").exists()
    assert len(mgr.list_checkpoints()) == 0


def test_delete_nonexistent_is_silent(tmp_path):
    mgr = CheckpointManager(tmp_path)
    mgr.delete("nonexistent")  # Should not raise
