"""Session persistence with fold-based conversation compression.

Saves full session state (proposal, grove results, agent logs, accounting,
codegen results, conversation history) to JSON files under ~/.sag/sessions/.

Older conversation turns are folded into compact summaries via the FoldEngine,
keeping LLM context manageable while retaining the ability to unfold.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.fold import FoldEngine
from sag.minifier import MessageMinifier


SCHEMA_VERSION = 1


def serialize_execution(result, output_path: str) -> str:
    """Write all grove messages to a SAG transcript file.

    Each message is serialized to SAG wire format with a blank line separator.
    Creates parent directories as needed.

    Returns the output path.
    """
    lines: list[str] = []
    for msg in result.messages:
        lines.append(MessageMinifier.to_minified_string(msg))
        lines.append("")  # blank line separator

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
DEFAULT_SESSIONS_DIR = Path.home() / ".sag" / "sessions"


@dataclass
class SessionData:
    """All persistent state for a single agent session."""

    session_id: str = ""
    label: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    task: str = ""
    provider: str = ""
    model: str = ""
    echo_mode: bool = False

    # Phase 0: pre-analysis context
    pre_analysis_context: str | None = None

    # Proposed agent tree
    proposal: dict | None = None

    # Grove execution result
    grove_result: dict | None = None

    # Per-agent logs (agent_id -> log data)
    agent_logs: dict[str, dict] = field(default_factory=dict)

    # Accounting call metrics
    accounting: dict = field(default_factory=lambda: {"calls": []})

    # Code generation results
    codegen: dict | None = None

    # Conversation history with fold support
    conversation: dict = field(
        default_factory=lambda: {"turns": [], "folds": []}
    )

    # Raw turn data backing each fold (fold_id -> turns)
    fold_store: dict[str, list[dict]] = field(default_factory=dict)


class SessionManager:
    """Handles session persistence lifecycle."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._dir = sessions_dir or DEFAULT_SESSIONS_DIR
        self._data: SessionData | None = None

    @property
    def data(self) -> SessionData | None:
        return self._data

    # -- Lifecycle --

    def new_session(
        self,
        task: str,
        provider: str = "",
        model: str = "",
        echo_mode: bool = False,
    ) -> SessionData:
        """Create a fresh session."""
        now = time.time()
        self._data = SessionData(
            session_id=str(uuid.uuid4()),
            label=task[:80] if task else "",
            created_at=now,
            updated_at=now,
            task=task,
            provider=provider,
            model=model,
            echo_mode=echo_mode,
        )
        return self._data

    def save(self) -> str:
        """Persist current session to disk. Returns session_id."""
        if self._data is None:
            raise RuntimeError("No active session to save")

        self._data.updated_at = time.time()
        self._dir.mkdir(parents=True, exist_ok=True)

        path = self._dir / f"{self._data.session_id}.json"
        payload = {
            "schema_version": SCHEMA_VERSION,
            "session_id": self._data.session_id,
            "label": self._data.label,
            "created_at": self._data.created_at,
            "updated_at": self._data.updated_at,
            "task": self._data.task,
            "provider": self._data.provider,
            "model": self._data.model,
            "echo_mode": self._data.echo_mode,
            "pre_analysis_context": self._data.pre_analysis_context,
            "proposal": self._data.proposal,
            "grove_result": self._data.grove_result,
            "agent_logs": self._data.agent_logs,
            "accounting": self._data.accounting,
            "codegen": self._data.codegen,
            "conversation": self._data.conversation,
            "fold_store": self._data.fold_store,
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return self._data.session_id

    def load(self, session_id: str) -> SessionData:
        """Load a session from disk."""
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Session not found: {session_id}")

        raw = json.loads(path.read_text(encoding="utf-8"))
        self._data = SessionData(
            session_id=raw.get("session_id", session_id),
            label=raw.get("label", ""),
            created_at=raw.get("created_at", 0.0),
            updated_at=raw.get("updated_at", 0.0),
            task=raw.get("task", ""),
            provider=raw.get("provider", ""),
            model=raw.get("model", ""),
            echo_mode=raw.get("echo_mode", False),
            pre_analysis_context=raw.get("pre_analysis_context"),
            proposal=raw.get("proposal"),
            grove_result=raw.get("grove_result"),
            agent_logs=raw.get("agent_logs", {}),
            accounting=raw.get("accounting", {"calls": []}),
            codegen=raw.get("codegen"),
            conversation=raw.get("conversation", {"turns": [], "folds": []}),
            fold_store=raw.get("fold_store", {}),
        )
        return self._data

    def list_sessions(self) -> list[dict]:
        """List all saved sessions (sorted newest first)."""
        if not self._dir.exists():
            return []

        sessions = []
        for f in self._dir.glob("*.json"):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": raw.get("session_id", f.stem),
                    "label": raw.get("label", ""),
                    "task": raw.get("task", ""),
                    "created_at": raw.get("created_at", 0.0),
                    "updated_at": raw.get("updated_at", 0.0),
                    "echo_mode": raw.get("echo_mode", False),
                    "provider": raw.get("provider", ""),
                    "model": raw.get("model", ""),
                    "turns": len(raw.get("conversation", {}).get("turns", [])),
                    "folds": len(raw.get("conversation", {}).get("folds", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue

        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted."""
        path = self._dir / f"{session_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # -- Progressive capture --

    def set_pre_analysis(self, context: str) -> None:
        if self._data:
            self._data.pre_analysis_context = context

    def set_proposal(self, proposal) -> None:
        """Record the proposed agent tree."""
        if self._data is None:
            return
        # Serialize TreeProposal to dict
        self._data.proposal = {
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "role": a.role,
                    "parent_id": a.parent_id,
                    "topics": a.topics,
                    "prompt": a.prompt,
                }
                for a in proposal.agents
            ],
            "rationale": proposal.rationale,
        }

    def set_grove_result(self, result) -> None:
        """Record grove execution outcome."""
        if self._data is None:
            return
        from sag.minifier import MessageMinifier

        self._data.grove_result = {
            "facts": {
                topic: [str(value), version]
                for topic, (value, version) in result.facts.items()
            },
            "messages": [
                MessageMinifier.to_minified_string(m) for m in result.messages
            ],
            "agents_run": result.agents_run,
            "levels_processed": result.levels_processed,
        }

    def set_agent_logs(self, logs: dict) -> None:
        """Record per-agent logs including RLHF ratings."""
        if self._data is None:
            return
        self._data.agent_logs = {
            agent_id: {
                "agent_id": log.agent_id,
                "role": log.role,
                "facts": dict(log.facts),
                "sag_transcript": list(log.sag_transcript) if hasattr(log, "sag_transcript") else [],
                "rating": log.rating,
                "feedback": log.feedback,
            }
            for agent_id, log in logs.items()
        }

    def set_accounting(self, collector) -> None:
        """Snapshot call metrics from the accounting collector."""
        if self._data is None:
            return
        self._data.accounting = {
            "calls": [
                {
                    "agent_id": c.agent_id,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "cost_usd": c.cost_usd,
                    "latency_ms": c.latency_ms,
                    "model": c.model,
                    "timestamp": c.timestamp,
                }
                for c in collector.get_calls()
            ]
        }

    def set_codegen(self, result) -> None:
        """Record code generation results."""
        if self._data is None or result is None:
            return
        self._data.codegen = {
            "output_dir": result.output_dir,
            "files_written": result.files_written,
            "files_failed": result.files_failed,
        }

    # -- Conversation --

    def add_conversation_turn(self, role: str, content: str) -> None:
        """Append a chat turn to conversation history."""
        if self._data is None:
            return
        self._data.conversation["turns"].append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })

    def fold_conversation(
        self, fold_engine: FoldEngine, keep_recent: int = 6
    ) -> int:
        """Fold older conversation turns using the fold engine.

        Groups turns older than the most recent ``keep_recent`` into blocks
        of ~10 and creates fold summaries.  Returns the number of new folds
        created.
        """
        if self._data is None:
            return 0

        turns = self._data.conversation["turns"]
        if len(turns) <= keep_recent:
            return 0

        foldable = turns[: len(turns) - keep_recent]
        if not foldable:
            return 0

        new_folds = 0
        block_size = 10
        start_idx = 0

        # Calculate the global offset: how many turns have already been folded
        existing_folds = self._data.conversation["folds"]
        global_offset = 0
        if existing_folds:
            last_range = existing_folds[-1].get("turn_range", [0, 0])
            global_offset = last_range[1] + 1

        # Only fold turns that haven't been folded yet
        already_folded_count = sum(
            r[1] - r[0] + 1
            for f in existing_folds
            for r in [f.get("turn_range", [0, 0])]
        )
        unfoldable_start = already_folded_count
        foldable = turns[unfoldable_start : len(turns) - keep_recent]
        if not foldable:
            return 0

        for i in range(0, len(foldable), block_size):
            block = foldable[i : i + block_size]
            if not block:
                break

            abs_start = unfoldable_start + i
            abs_end = abs_start + len(block) - 1

            # Build a mechanical summary
            n_user = sum(1 for t in block if t["role"] == "user")
            n_asst = sum(1 for t in block if t["role"] == "assistant")
            summary = (
                f"Turns {abs_start}-{abs_end}: "
                f"{n_user + n_asst} exchanges ({n_user} user, {n_asst} assistant)"
            )

            # Register the fold (we pass an empty message list since we're
            # storing raw turn dicts in fold_store, not SAG Messages)
            fold_stmt = fold_engine.fold([], summary)

            self._data.conversation["folds"].append({
                "fold_id": fold_stmt.fold_id,
                "summary": summary,
                "turn_range": [abs_start, abs_end],
            })
            self._data.fold_store[fold_stmt.fold_id] = block
            new_folds += 1

        # Remove folded turns from the turns list (keep only recent)
        self._data.conversation["turns"] = turns[len(turns) - keep_recent :]

        return new_folds

    def get_folded_history(self) -> list[dict[str, str]]:
        """Return conversation messages for LLM context.

        Fold summaries become synthetic user messages, followed by
        recent raw turns.
        """
        if self._data is None:
            return []

        messages: list[dict[str, str]] = []

        # Add fold summaries as context
        for fold in self._data.conversation.get("folds", []):
            messages.append({
                "role": "user",
                "content": f"[Previous context]\n{fold['summary']}",
            })

        # Add recent raw turns
        for turn in self._data.conversation.get("turns", []):
            messages.append({
                "role": turn["role"],
                "content": turn["content"],
            })

        return messages

    # -- Fold store serialization --

    def serialize_fold_store(self, fold_engine: FoldEngine) -> None:
        """Capture fold engine state into the session's fold_store."""
        if self._data is None:
            return
        # The fold engine stores SAG Messages, but our conversation folds
        # store raw turn dicts. We keep both in sync — the fold_store in
        # SessionData already has raw turns from fold_conversation().
        # This method is a no-op for now since fold_conversation() handles it.

    def restore_fold_store(self, fold_engine: FoldEngine) -> None:
        """Reload fold data into the fold engine.

        Registers empty message lists so has_fold() returns True for
        all persisted fold IDs.
        """
        if self._data is None:
            return
        for fold in self._data.conversation.get("folds", []):
            fold_id = fold["fold_id"]
            # Register the fold in the engine so has_fold/get_fold_count work
            if not fold_engine.has_fold(fold_id):
                fold_engine.fold([], fold["summary"])
