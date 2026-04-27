"""Tool system for grounding SAG agents in the real world.

Provides:
- Data models: ``Tool``, ``ToolParam``, ``ToolCall``, ``ToolResult``
- ``SafetyPolicy`` / ``DefaultSafetyPolicy``: controls what tools can do
- ``ToolExecutor``: registry + dispatch + safety gating
- Eight built-in tool handlers (filesystem, shell, web)
- Factory helpers for creating tool sets per phase
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol


# Max chars for any single tool result before truncation
_MAX_TOOL_OUTPUT_CHARS = 12_000


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolParam:
    """Definition of a single tool parameter."""

    name: str
    type: str  # "string", "integer", "boolean"
    description: str
    required: bool = True
    default: Any = None


@dataclass(frozen=True)
class ToolCall:
    """An LLM-issued request to call a tool."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool call."""

    call_id: str
    tool_name: str
    output: str
    is_error: bool = False


class Tool:
    """A callable tool with metadata for LLM schema generation."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: list[ToolParam],
        handler: Callable[..., str],
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def __repr__(self) -> str:
        return f"Tool({self.name!r})"


# ---------------------------------------------------------------------------
# Safety policy
# ---------------------------------------------------------------------------

# Shell commands/patterns that are always blocked
_BLOCKED_SHELL_PATTERNS: list[str] = [
    r"\brm\s+-rf\s+/",
    r"\bsudo\b",
    r"\bmkfs\b",
    r"\bdd\s+.*of=/dev/",
    r"\b:()\s*\{",  # fork bomb
    r"\bchmod\s+-R\s+777\s+/",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bkill\s+-9\s+-1\b",
]

_BLOCKED_RE = re.compile("|".join(_BLOCKED_SHELL_PATTERNS))


class SafetyPolicy(Protocol):
    """Controls what tools are allowed to do."""

    def check_shell_command(self, command: str) -> str | None:
        """Return an error string if the command is blocked, else None."""
        ...

    def check_write_path(self, path: str) -> str | None:
        """Return an error string if writing to this path is blocked."""
        ...

    def shell_needs_confirmation(self) -> bool:
        """Whether shell commands require user confirmation."""
        ...

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Whether a given tool is enabled in this policy."""
        ...


class DefaultSafetyPolicy:
    """Configurable safety policy for tool execution.

    Parameters
    ----------
    allowed_tools : set of tool names that are enabled (None = all)
    writable_dirs : directories where write_file/patch_file may write
    shell_confirmation : whether shell commands need user confirmation
    shell_blocked_patterns : extra regex patterns to block
    """

    def __init__(
        self,
        allowed_tools: set[str] | None = None,
        writable_dirs: list[str] | None = None,
        shell_confirmation: bool = False,
        shell_blocked_patterns: list[str] | None = None,
    ) -> None:
        self._allowed_tools = allowed_tools
        self._writable_dirs = [
            os.path.abspath(d) for d in (writable_dirs or [])
        ]
        self._shell_confirmation = shell_confirmation
        extra = shell_blocked_patterns or []
        if extra:
            combined = _BLOCKED_SHELL_PATTERNS + extra
            self._blocked_re = re.compile("|".join(combined))
        else:
            self._blocked_re = _BLOCKED_RE

    def check_shell_command(self, command: str) -> str | None:
        if self._blocked_re.search(command):
            return f"Shell command blocked by safety policy: {command!r}"
        return None

    def check_write_path(self, path: str) -> str | None:
        if not self._writable_dirs:
            return None  # no restriction
        abs_path = os.path.abspath(path)
        for wd in self._writable_dirs:
            if abs_path.startswith(wd + os.sep) or abs_path == wd:
                return None
        dirs_str = ", ".join(self._writable_dirs)
        return f"Write blocked: {path!r} is not under allowed directories: {dirs_str}"

    def shell_needs_confirmation(self) -> bool:
        return self._shell_confirmation

    def is_tool_allowed(self, tool_name: str) -> bool:
        if self._allowed_tools is None:
            return True
        return tool_name in self._allowed_tools


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------


class ToolExecutor:
    """Registry and dispatcher for tool calls.

    Holds a set of Tool objects and a SafetyPolicy. Executes ToolCall
    objects by looking up the handler and enforcing policy.
    """

    def __init__(
        self,
        tools: list[Tool],
        policy: SafetyPolicy | None = None,
        confirm_callback: Callable[[str], bool] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}
        self._policy = policy or DefaultSafetyPolicy()
        self._confirm_callback = confirm_callback

    @property
    def tools(self) -> list[Tool]:
        """Return the list of available tools."""
        return list(self._tools.values())

    def add_tool(self, tool: Tool) -> None:
        """Register an additional tool after construction."""
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute a tool call and return the result."""
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                output=f"Unknown tool: {call.name}",
                is_error=True,
            )

        if not self._policy.is_tool_allowed(call.name):
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                output=f"Tool '{call.name}' is not allowed by the current safety policy.",
                is_error=True,
            )

        try:
            output = tool.handler(self, **call.arguments)
            # Truncate excessively large outputs
            if len(output) > _MAX_TOOL_OUTPUT_CHARS:
                output = (
                    output[:_MAX_TOOL_OUTPUT_CHARS]
                    + f"\n... (output truncated at {_MAX_TOOL_OUTPUT_CHARS} chars, "
                    + f"original was {len(output)} chars)"
                )
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                output=output,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call.id,
                tool_name=call.name,
                output=f"Error executing {call.name}: {exc}",
                is_error=True,
            )

    @property
    def policy(self) -> SafetyPolicy:
        return self._policy

    @property
    def confirm_callback(self) -> Callable[[str], bool] | None:
        return self._confirm_callback


# ---------------------------------------------------------------------------
# Built-in tool handlers
# ---------------------------------------------------------------------------


def _handle_read_file(executor: ToolExecutor, path: str, max_lines: int = 200) -> str:
    """Read a file and return its contents (truncated to max_lines)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) > max_lines:
        truncated = lines[:max_lines]
        truncated.append(f"\n... ({len(lines) - max_lines} more lines truncated)")
        return "\n".join(truncated)
    return "\n".join(lines)


def _handle_list_directory(
    executor: ToolExecutor, path: str = ".", pattern: str = "*"
) -> str:
    """List directory entries matching a glob pattern."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {path}")
    if not p.is_dir():
        raise ValueError(f"Not a directory: {path}")

    entries: list[str] = []
    for entry in sorted(p.iterdir()):
        if not fnmatch.fnmatch(entry.name, pattern):
            continue
        suffix = "/" if entry.is_dir() else ""
        size = ""
        if entry.is_file():
            try:
                size = f"  ({entry.stat().st_size} bytes)"
            except OSError:
                pass
        entries.append(f"{entry.name}{suffix}{size}")

    if not entries:
        return f"No entries matching '{pattern}' in {path}"
    return "\n".join(entries)


def _handle_run_shell(
    executor: ToolExecutor, command: str, timeout: int = 30
) -> str:
    """Run a shell command and return stdout+stderr."""
    # Safety check
    error = executor.policy.check_shell_command(command)
    if error:
        raise PermissionError(error)

    # Confirmation check
    if executor.policy.shell_needs_confirmation():
        cb = executor.confirm_callback
        if cb is not None:
            if not cb(command):
                return "(shell command denied by user)"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output_parts: list[str] = []
        if result.stdout:
            stdout = result.stdout
            if len(stdout) > _MAX_TOOL_OUTPUT_CHARS:
                stdout = (
                    stdout[:_MAX_TOOL_OUTPUT_CHARS]
                    + f"\n... (stdout truncated at {_MAX_TOOL_OUTPUT_CHARS} chars)"
                )
            output_parts.append(stdout)
        if result.stderr:
            stderr = result.stderr[:5000] if len(result.stderr) > 5000 else result.stderr
            output_parts.append(f"[stderr]\n{stderr}")
        if result.returncode != 0:
            output_parts.append(f"[exit code: {result.returncode}]")
        return "\n".join(output_parts) if output_parts else "(no output)"
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Command timed out after {timeout}s: {command}")


def _handle_write_file(executor: ToolExecutor, path: str, content: str) -> str:
    """Write content to a file, creating parent directories as needed."""
    error = executor.policy.check_write_path(path)
    if error:
        raise PermissionError(error)

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


def _handle_patch_file(
    executor: ToolExecutor, path: str, search: str, replace: str
) -> str:
    """Search-and-replace in an existing file."""
    error = executor.policy.check_write_path(path)
    if error:
        raise PermissionError(error)

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    original = p.read_text(encoding="utf-8")
    if search not in original:
        raise ValueError(f"Search string not found in {path}")

    count = original.count(search)
    updated = original.replace(search, replace)
    p.write_text(updated, encoding="utf-8")
    return f"Replaced {count} occurrence(s) in {path}"


def _handle_search_files(
    executor: ToolExecutor, pattern: str, path: str = ".", max_results: int = 10
) -> str:
    """Search for a regex pattern across files in a directory tree."""
    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex: {e}")

    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    results: list[str] = []
    count = 0

    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        # Skip binary/hidden files
        if file_path.name.startswith("."):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue

        for line_num, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rel = file_path.relative_to(root) if root != file_path else file_path
                results.append(f"{rel}:{line_num}: {line.rstrip()}")
                count += 1
                if count >= max_results:
                    results.append(f"... (truncated at {max_results} results)")
                    return "\n".join(results)

    if not results:
        return f"No matches for '{pattern}' in {path}"
    return "\n".join(results)


def _handle_web_fetch(
    executor: ToolExecutor, url: str, max_chars: int = 20000
) -> str:
    """Fetch URL content and return as text."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "SAG-Agent/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n... (truncated at {max_chars} chars)"
            return content
    except urllib.error.URLError as e:
        raise ConnectionError(f"Failed to fetch {url}: {e}")


def _handle_web_search(
    executor: ToolExecutor, query: str, max_results: int = 5
) -> str:
    """Web search via DuckDuckGo instant answer API."""
    safe_query = urllib.request.quote(query)
    url = f"https://api.duckduckgo.com/?q={safe_query}&format=json&no_html=1"
    req = urllib.request.Request(
        url, headers={"User-Agent": "SAG-Agent/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json

            data = json.loads(resp.read().decode("utf-8"))

        parts: list[str] = []

        # Abstract
        abstract = data.get("AbstractText", "")
        if abstract:
            source = data.get("AbstractSource", "")
            parts.append(f"{abstract}")
            if source:
                parts.append(f"Source: {source}")

        # Related topics
        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and "Text" in topic:
                parts.append(f"- {topic['Text']}")

        if not parts:
            parts.append(f"No instant results for: {query}")
            parts.append("Try refining your query or use web_fetch with a specific URL.")

        return "\n".join(parts)
    except Exception as e:
        return f"Search failed: {e}. Try web_fetch with a direct URL instead."


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


READ_FILE = Tool(
    name="read_file",
    description="Read the contents of a file. Returns the text content, truncated to max_lines.",
    parameters=[
        ToolParam("path", "string", "Path to the file to read"),
        ToolParam("max_lines", "integer", "Maximum lines to return", required=False, default=200),
    ],
    handler=_handle_read_file,
)

LIST_DIRECTORY = Tool(
    name="list_directory",
    description="List entries in a directory, optionally filtered by glob pattern.",
    parameters=[
        ToolParam("path", "string", "Directory path", required=False, default="."),
        ToolParam("pattern", "string", "Glob pattern to filter entries", required=False, default="*"),
    ],
    handler=_handle_list_directory,
)

RUN_SHELL = Tool(
    name="run_shell",
    description="Run a shell command and return its output. Some dangerous commands are blocked.",
    parameters=[
        ToolParam("command", "string", "Shell command to execute"),
        ToolParam("timeout", "integer", "Timeout in seconds", required=False, default=30),
    ],
    handler=_handle_run_shell,
)

WRITE_FILE = Tool(
    name="write_file",
    description="Write content to a file, creating parent directories as needed.",
    parameters=[
        ToolParam("path", "string", "Path to the file to write"),
        ToolParam("content", "string", "Content to write"),
    ],
    handler=_handle_write_file,
)

PATCH_FILE = Tool(
    name="patch_file",
    description="Find and replace text in an existing file.",
    parameters=[
        ToolParam("path", "string", "Path to the file to modify"),
        ToolParam("search", "string", "Text to search for"),
        ToolParam("replace", "string", "Replacement text"),
    ],
    handler=_handle_patch_file,
)

SEARCH_FILES = Tool(
    name="search_files",
    description="Search for a regex pattern across files in a directory tree. Returns matching lines.",
    parameters=[
        ToolParam("pattern", "string", "Regex pattern to search for"),
        ToolParam("path", "string", "Root directory to search", required=False, default="."),
        ToolParam("max_results", "integer", "Maximum matching lines to return", required=False, default=10),
    ],
    handler=_handle_search_files,
)

WEB_FETCH = Tool(
    name="web_fetch",
    description="Fetch the content of a URL and return it as text.",
    parameters=[
        ToolParam("url", "string", "URL to fetch"),
        ToolParam("max_chars", "integer", "Maximum characters to return", required=False, default=20000),
    ],
    handler=_handle_web_fetch,
)

WEB_SEARCH = Tool(
    name="web_search",
    description="Search the web using DuckDuckGo and return results.",
    parameters=[
        ToolParam("query", "string", "Search query"),
        ToolParam("max_results", "integer", "Maximum results to return", required=False, default=5),
    ],
    handler=_handle_web_search,
)

# All built-in tools
ALL_TOOLS: list[Tool] = [
    READ_FILE,
    LIST_DIRECTORY,
    RUN_SHELL,
    WRITE_FILE,
    PATCH_FILE,
    SEARCH_FILES,
    WEB_FETCH,
    WEB_SEARCH,
]

# Named subsets for convenience
READ_ONLY_TOOLS: list[Tool] = [
    READ_FILE,
    LIST_DIRECTORY,
    RUN_SHELL,
    SEARCH_FILES,
    WEB_FETCH,
    WEB_SEARCH,
]

BROWSE_ONLY_TOOLS: list[Tool] = [
    READ_FILE,
    LIST_DIRECTORY,
    SEARCH_FILES,
    WEB_FETCH,
    WEB_SEARCH,
]


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_read_only_executor(
    confirm_callback: Callable[[str], bool] | None = None,
) -> ToolExecutor:
    """Create an executor with read-only tools (includes shell)."""
    policy = DefaultSafetyPolicy(
        allowed_tools={t.name for t in READ_ONLY_TOOLS},
        shell_confirmation=False,
    )
    return ToolExecutor(READ_ONLY_TOOLS, policy, confirm_callback)


def make_browse_only_executor() -> ToolExecutor:
    """Create an executor with browse-only tools (no shell, no writes)."""
    policy = DefaultSafetyPolicy(
        allowed_tools={t.name for t in BROWSE_ONLY_TOOLS},
    )
    return ToolExecutor(BROWSE_ONLY_TOOLS, policy)


def make_full_executor(
    writable_dirs: list[str] | None = None,
    shell_confirmation: bool = True,
    confirm_callback: Callable[[str], bool] | None = None,
) -> ToolExecutor:
    """Create an executor with all tools. Writes restricted to given dirs."""
    policy = DefaultSafetyPolicy(
        writable_dirs=writable_dirs,
        shell_confirmation=shell_confirmation,
    )
    return ToolExecutor(ALL_TOOLS, policy, confirm_callback)
