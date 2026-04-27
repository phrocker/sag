"""File state tracker — Code as Assertions.

Tracks file state (hash, size, status) and asserts it into a KnowledgeEngine
as structured facts. This lets the agent tree reason about file state changes
using the same knowledge propagation system used for all other facts.

Usage::

    tracker = FileStateTracker(knowledge_engine)
    tracker.scan("/path/to/project")
    # Now knowledge has facts like:
    #   file.src/main.py.hash = "a1b2c3..."
    #   file.src/main.py.size = "1234"
    #   file.src/main.py.status = "tracked"

    tracker.mark_modified("src/main.py")
    # file.src/main.py.status = "modified"
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sag.knowledge import KnowledgeEngine


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileState:
    """Snapshot of a single file's state."""

    path: str
    hash: str
    size: int
    status: str  # "tracked", "modified", "created", "deleted"
    last_modified: float = 0.0

    @property
    def topic_prefix(self) -> str:
        """Knowledge topic prefix for this file (e.g. 'file.src/main.py')."""
        return f"file.{self.path}"


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

# File extensions we consider "code" — others are tracked but not hashed
_CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".rb",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".scala",
    ".html", ".css", ".scss", ".less", ".sql", ".sh", ".bash",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".md", ".txt",
    ".dockerfile", ".makefile", ".gitignore", ".env",
    ".cfg", ".ini", ".conf",
}

# Directories to always skip
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".egg-info", ".eggs",
}

# Max file size for hashing (skip binaries / large files)
_MAX_HASH_SIZE = 1_000_000  # 1 MB


def _file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # short hash for readability


def _should_track(path: Path) -> bool:
    """Whether a file should be tracked."""
    name = path.name.lower()
    # Track files by extension
    if path.suffix.lower() in _CODE_EXTENSIONS:
        return True
    # Track extensionless files like Makefile, Dockerfile
    if name in ("makefile", "dockerfile", "procfile", "gemfile", "rakefile"):
        return True
    return False


class FileStateTracker:
    """Tracks file state and asserts it into a KnowledgeEngine.

    The tracker maintains a mapping of relative paths to FileState snapshots.
    When ``scan()`` is called, it walks the directory, computes hashes, and
    asserts facts into the attached KnowledgeEngine.

    Subsequent calls to ``scan()`` detect changes (modified, created, deleted)
    and assert updated facts.
    """

    def __init__(
        self,
        knowledge: KnowledgeEngine,
        root_dir: str | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._root_dir = root_dir
        self._states: dict[str, FileState] = {}

    @property
    def root_dir(self) -> str | None:
        return self._root_dir

    @root_dir.setter
    def root_dir(self, value: str) -> None:
        self._root_dir = value

    @property
    def states(self) -> dict[str, FileState]:
        """Return a copy of all tracked file states."""
        return dict(self._states)

    def scan(self, root_dir: str | None = None) -> list[FileState]:
        """Scan a directory tree and assert file states into knowledge.

        Returns the list of FileState objects that were new or changed.
        """
        root = Path(root_dir or self._root_dir or ".")
        if not root.exists():
            return []

        self._root_dir = str(root)
        is_first_scan = len(self._states) == 0
        current_paths: set[str] = set()
        changed: list[FileState] = []

        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue

            # Skip hidden/ignored directories
            parts = file_path.relative_to(root).parts
            if any(p in _SKIP_DIRS for p in parts):
                continue

            if not _should_track(file_path):
                continue

            rel = str(file_path.relative_to(root))
            current_paths.add(rel)

            try:
                stat = file_path.stat()
            except OSError:
                continue

            # Compute hash for reasonably-sized files
            if stat.st_size <= _MAX_HASH_SIZE:
                try:
                    file_h = _file_hash(file_path)
                except OSError:
                    continue
            else:
                file_h = f"large:{stat.st_size}"

            old_state = self._states.get(rel)

            if old_state is None:
                status = "tracked" if is_first_scan else "created"
            elif old_state.hash != file_h:
                status = "modified"
            else:
                # Unchanged — don't re-assert
                continue

            new_state = FileState(
                path=rel,
                hash=file_h,
                size=stat.st_size,
                status=status,
                last_modified=stat.st_mtime,
            )

            self._states[rel] = new_state
            self._assert_state(new_state)
            changed.append(new_state)

        # Detect deletions
        for old_path in set(self._states.keys()) - current_paths:
            old = self._states[old_path]
            deleted = FileState(
                path=old_path,
                hash="",
                size=0,
                status="deleted",
                last_modified=0.0,
            )
            self._states[old_path] = deleted
            self._assert_state(deleted)
            changed.append(deleted)

        return changed

    def track_file(self, path: str, content: str | None = None) -> FileState:
        """Manually track a single file.

        If ``content`` is provided, uses it for hashing instead of reading
        from disk. Useful for tracking files written by tool handlers.
        """
        if content is not None:
            h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
            size = len(content.encode("utf-8"))
            status = "modified" if path in self._states else "created"
            state = FileState(
                path=path, hash=h, size=size,
                status=status, last_modified=0.0,
            )
        else:
            root = Path(self._root_dir or ".")
            full = root / path
            if not full.exists():
                state = FileState(
                    path=path, hash="", size=0,
                    status="deleted", last_modified=0.0,
                )
            else:
                stat = full.stat()
                h = _file_hash(full)
                old = self._states.get(path)
                if old is None:
                    status = "created"
                elif old.hash != h:
                    status = "modified"
                else:
                    return old  # unchanged
                state = FileState(
                    path=path, hash=h, size=stat.st_size,
                    status=status, last_modified=stat.st_mtime,
                )

        self._states[path] = state
        self._assert_state(state)
        return state

    def mark_modified(self, path: str) -> FileState | None:
        """Mark a file as modified without re-scanning.

        Returns the updated FileState, or None if the file is not tracked.
        """
        old = self._states.get(path)
        if old is None:
            return None

        new_state = FileState(
            path=path,
            hash=old.hash,
            size=old.size,
            status="modified",
            last_modified=old.last_modified,
        )
        self._states[path] = new_state
        self._assert_state(new_state)
        return new_state

    def get_state(self, path: str) -> FileState | None:
        """Get the current state of a tracked file."""
        return self._states.get(path)

    def get_modified_files(self) -> list[FileState]:
        """Return all files with status 'modified' or 'created'."""
        return [
            s for s in self._states.values()
            if s.status in ("modified", "created")
        ]

    def get_summary(self) -> dict[str, int]:
        """Return counts by status."""
        summary: dict[str, int] = {}
        for s in self._states.values():
            summary[s.status] = summary.get(s.status, 0) + 1
        return summary

    # -- Snapshot / Restore --

    def snapshot(self) -> str:
        """Save current file contents to a temp directory.

        Returns the snapshot ID (temp directory path). The snapshot
        preserves directory structure and file contents so that
        ``restore()`` can revert any changes.
        """
        root = Path(self._root_dir or ".")
        if not root.exists():
            raise FileNotFoundError(f"Root directory not found: {root}")

        snap_dir = tempfile.mkdtemp(prefix="sag_snapshot_")

        for rel_path, state in self._states.items():
            if state.status == "deleted":
                continue
            src = root / rel_path
            if not src.exists():
                continue
            dst = Path(snap_dir) / rel_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))

        # Save manifest of tracked paths
        manifest = Path(snap_dir) / ".sag_manifest"
        manifest.write_text("\n".join(sorted(self._states.keys())))

        return snap_dir

    def restore(self, snapshot_id: str) -> list[str]:
        """Restore files from a snapshot, reverting all changes.

        Returns the list of files that were restored or removed.
        """
        snap_dir = Path(snapshot_id)
        if not snap_dir.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_id}")

        root = Path(self._root_dir or ".")
        restored: list[str] = []

        # Read manifest to know what was originally tracked
        manifest_path = snap_dir / ".sag_manifest"
        if manifest_path.exists():
            original_paths = set(manifest_path.read_text().strip().split("\n"))
        else:
            original_paths = set()

        # Restore all files from snapshot
        for snap_file in snap_dir.rglob("*"):
            if not snap_file.is_file():
                continue
            if snap_file.name == ".sag_manifest":
                continue
            rel = str(snap_file.relative_to(snap_dir))
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(snap_file), str(dst))
            restored.append(rel)

        # Remove files that were created after the snapshot
        if original_paths:
            for rel_path in list(self._states.keys()):
                if rel_path not in original_paths:
                    full = root / rel_path
                    if full.exists():
                        full.unlink()
                        restored.append(f"(removed) {rel_path}")

        # Re-scan to update state
        self._states.clear()
        self.scan(str(root))

        # Clean up snapshot directory
        shutil.rmtree(snapshot_id, ignore_errors=True)

        return restored

    def clear(self) -> None:
        """Clear all tracked state."""
        self._states.clear()

    def _assert_state(self, state: FileState) -> None:
        """Assert file state into the knowledge engine."""
        prefix = state.topic_prefix
        self._knowledge.assert_fact(f"{prefix}.hash", state.hash)
        self._knowledge.assert_fact(f"{prefix}.size", str(state.size))
        self._knowledge.assert_fact(f"{prefix}.status", state.status)
