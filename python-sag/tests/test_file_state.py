"""Tests for file state tracker — Code as Assertions."""

import os
import time

import pytest

from sag.file_state import FileState, FileStateTracker, _file_hash, _should_track
from sag.knowledge import KnowledgeEngine


# ---------------------------------------------------------------------------
# FileState dataclass
# ---------------------------------------------------------------------------


class TestFileState:
    def test_create(self):
        fs = FileState(
            path="src/main.py", hash="abc123", size=100,
            status="tracked", last_modified=0.0,
        )
        assert fs.path == "src/main.py"
        assert fs.hash == "abc123"
        assert fs.size == 100
        assert fs.status == "tracked"

    def test_frozen(self):
        fs = FileState(path="a.py", hash="x", size=1, status="tracked")
        with pytest.raises(AttributeError):
            fs.path = "b.py"  # type: ignore

    def test_topic_prefix(self):
        fs = FileState(path="src/main.py", hash="x", size=1, status="tracked")
        assert fs.topic_prefix == "file.src/main.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_file_hash(self, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("hello world")
        h = _file_hash(p)
        assert isinstance(h, str)
        assert len(h) == 16  # short hash

    def test_file_hash_deterministic(self, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("hello world")
        h1 = _file_hash(p)
        h2 = _file_hash(p)
        assert h1 == h2

    def test_file_hash_changes(self, tmp_path):
        p = tmp_path / "test.py"
        p.write_text("hello world")
        h1 = _file_hash(p)
        p.write_text("goodbye world")
        h2 = _file_hash(p)
        assert h1 != h2

    def test_should_track_python(self, tmp_path):
        p = tmp_path / "main.py"
        p.touch()
        assert _should_track(p) is True

    def test_should_track_js(self, tmp_path):
        p = tmp_path / "app.js"
        p.touch()
        assert _should_track(p) is True

    def test_should_track_binary(self, tmp_path):
        p = tmp_path / "image.png"
        p.touch()
        assert _should_track(p) is False

    def test_should_track_makefile(self, tmp_path):
        p = tmp_path / "Makefile"
        p.touch()
        assert _should_track(p) is True


# ---------------------------------------------------------------------------
# FileStateTracker
# ---------------------------------------------------------------------------


class TestFileStateTracker:
    def test_scan_empty_dir(self, tmp_path):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        changed = tracker.scan(str(tmp_path))
        assert changed == []
        assert tracker.states == {}

    def test_scan_with_files(self, tmp_path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "config.yaml").write_text("key: value")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")  # should be skipped

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        changed = tracker.scan(str(tmp_path))

        assert len(changed) == 2
        paths = {f.path for f in changed}
        assert "main.py" in paths
        assert "config.yaml" in paths
        assert "image.png" not in paths

    def test_scan_asserts_facts(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        # Should have asserted hash, size, status facts
        h = ke.get_fact("file.app.py.hash")
        assert h is not None
        s = ke.get_fact("file.app.py.size")
        assert s is not None
        st = ke.get_fact("file.app.py.status")
        assert st is not None
        assert st[0] == "tracked"

    def test_scan_detects_modifications(self, tmp_path):
        f = tmp_path / "app.py"
        f.write_text("version 1")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        # Modify file
        f.write_text("version 2")
        changed = tracker.scan(str(tmp_path))

        assert len(changed) == 1
        assert changed[0].status == "modified"
        assert changed[0].path == "app.py"

    def test_scan_detects_creation(self, tmp_path):
        (tmp_path / "old.py").write_text("old")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        # Create new file
        (tmp_path / "new.py").write_text("new")
        changed = tracker.scan(str(tmp_path))

        assert len(changed) == 1
        assert changed[0].status == "created"
        assert changed[0].path == "new.py"

    def test_scan_detects_deletion(self, tmp_path):
        f = tmp_path / "doomed.py"
        f.write_text("bye")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        # Delete file
        f.unlink()
        changed = tracker.scan(str(tmp_path))

        assert len(changed) == 1
        assert changed[0].status == "deleted"
        assert changed[0].path == "doomed.py"

    def test_scan_skips_pycache(self, tmp_path):
        pycache = tmp_path / "__pycache__"
        pycache.mkdir()
        (pycache / "module.cpython-310.pyc").write_bytes(b"\x00")
        (tmp_path / "app.py").write_text("ok")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        changed = tracker.scan(str(tmp_path))

        paths = {f.path for f in changed}
        assert "app.py" in paths
        assert "__pycache__/module.cpython-310.pyc" not in paths

    def test_track_file_with_content(self):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke, root_dir=".")

        state = tracker.track_file("virtual.py", content="print('hello')")
        assert state.status == "created"
        assert state.size == len("print('hello')".encode("utf-8"))

        # Track again with different content
        state2 = tracker.track_file("virtual.py", content="print('world')")
        assert state2.status == "modified"

    def test_mark_modified(self, tmp_path):
        (tmp_path / "app.py").write_text("x = 1")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        result = tracker.mark_modified("app.py")
        assert result is not None
        assert result.status == "modified"

    def test_mark_modified_untracked(self):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        result = tracker.mark_modified("nonexistent.py")
        assert result is None

    def test_get_summary(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        summary = tracker.get_summary()
        assert summary["tracked"] == 2

    def test_get_modified_files(self, tmp_path):
        (tmp_path / "a.py").write_text("a")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))

        # Initially no modified files (first scan = "tracked")
        assert tracker.get_modified_files() == []

        # Modify
        (tmp_path / "a.py").write_text("b")
        tracker.scan(str(tmp_path))
        modified = tracker.get_modified_files()
        assert len(modified) == 1
        assert modified[0].path == "a.py"

    def test_clear(self, tmp_path):
        (tmp_path / "a.py").write_text("a")

        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        tracker.scan(str(tmp_path))
        assert len(tracker.states) > 0

        tracker.clear()
        assert len(tracker.states) == 0

    def test_nonexistent_root(self):
        ke = KnowledgeEngine("test")
        tracker = FileStateTracker(ke)
        changed = tracker.scan("/nonexistent/path/that/doesnt/exist")
        assert changed == []
