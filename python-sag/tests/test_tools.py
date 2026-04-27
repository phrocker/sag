"""Tests for the tool system: data models, executor, safety policy, handlers."""

import os
import tempfile
from pathlib import Path

import pytest

from sag.tools import (
    ALL_TOOLS,
    BROWSE_ONLY_TOOLS,
    READ_ONLY_TOOLS,
    DefaultSafetyPolicy,
    Tool,
    ToolCall,
    ToolExecutor,
    ToolParam,
    ToolResult,
    make_browse_only_executor,
    make_full_executor,
    make_read_only_executor,
)


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------


class TestToolParam:
    def test_required_param(self):
        p = ToolParam("name", "string", "A name")
        assert p.name == "name"
        assert p.type == "string"
        assert p.required is True
        assert p.default is None

    def test_optional_param(self):
        p = ToolParam("count", "integer", "A count", required=False, default=10)
        assert p.required is False
        assert p.default == 10


class TestToolCall:
    def test_creation(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={"path": "/tmp/x"})
        assert tc.id == "call_1"
        assert tc.name == "read_file"
        assert tc.arguments == {"path": "/tmp/x"}

    def test_frozen(self):
        tc = ToolCall(id="call_1", name="read_file", arguments={})
        with pytest.raises(AttributeError):
            tc.id = "call_2"


class TestToolResult:
    def test_success(self):
        tr = ToolResult(call_id="c1", tool_name="read_file", output="hello")
        assert not tr.is_error

    def test_error(self):
        tr = ToolResult(call_id="c1", tool_name="read_file", output="fail", is_error=True)
        assert tr.is_error


class TestTool:
    def test_repr(self):
        t = Tool("my_tool", "desc", [], lambda ex: "ok")
        assert "my_tool" in repr(t)


# ---------------------------------------------------------------------------
# Safety policy tests
# ---------------------------------------------------------------------------


class TestDefaultSafetyPolicy:
    def test_allows_all_tools_by_default(self):
        policy = DefaultSafetyPolicy()
        assert policy.is_tool_allowed("read_file")
        assert policy.is_tool_allowed("anything")

    def test_restricts_tools(self):
        policy = DefaultSafetyPolicy(allowed_tools={"read_file", "list_directory"})
        assert policy.is_tool_allowed("read_file")
        assert not policy.is_tool_allowed("run_shell")

    def test_blocks_dangerous_shell_commands(self):
        policy = DefaultSafetyPolicy()
        assert policy.check_shell_command("rm -rf /") is not None
        assert policy.check_shell_command("sudo apt install vim") is not None
        assert policy.check_shell_command("shutdown now") is not None

    def test_allows_safe_shell_commands(self):
        policy = DefaultSafetyPolicy()
        assert policy.check_shell_command("ls -la") is None
        assert policy.check_shell_command("python --version") is None
        assert policy.check_shell_command("cat README.md") is None

    def test_write_path_unrestricted(self):
        policy = DefaultSafetyPolicy()
        assert policy.check_write_path("/any/path") is None

    def test_write_path_restricted(self):
        policy = DefaultSafetyPolicy(writable_dirs=["/tmp/output"])
        assert policy.check_write_path("/tmp/output/file.txt") is None
        assert policy.check_write_path("/home/user/file.txt") is not None

    def test_shell_confirmation_default_off(self):
        policy = DefaultSafetyPolicy()
        assert not policy.shell_needs_confirmation()

    def test_shell_confirmation_on(self):
        policy = DefaultSafetyPolicy(shell_confirmation=True)
        assert policy.shell_needs_confirmation()


# ---------------------------------------------------------------------------
# Executor tests
# ---------------------------------------------------------------------------


class TestToolExecutor:
    def test_unknown_tool(self):
        executor = ToolExecutor(tools=[])
        call = ToolCall(id="c1", name="no_such_tool", arguments={})
        result = executor.execute(call)
        assert result.is_error
        assert "Unknown tool" in result.output

    def test_blocked_tool(self):
        policy = DefaultSafetyPolicy(allowed_tools={"read_file"})
        tool = Tool("write_file", "write", [], lambda ex: "ok")
        executor = ToolExecutor(tools=[tool], policy=policy)
        call = ToolCall(id="c1", name="write_file", arguments={})
        result = executor.execute(call)
        assert result.is_error
        assert "not allowed" in result.output

    def test_handler_exception(self):
        def bad_handler(ex):
            raise RuntimeError("boom")
        tool = Tool("bad", "bad tool", [], bad_handler)
        executor = ToolExecutor(tools=[tool])
        call = ToolCall(id="c1", name="bad", arguments={})
        result = executor.execute(call)
        assert result.is_error
        assert "boom" in result.output

    def test_successful_execution(self):
        tool = Tool("echo", "echo", [], lambda ex, msg="hi": msg)
        executor = ToolExecutor(tools=[tool])
        call = ToolCall(id="c1", name="echo", arguments={"msg": "hello"})
        result = executor.execute(call)
        assert not result.is_error
        assert result.output == "hello"

    def test_tools_property(self):
        t1 = Tool("a", "a", [], lambda ex: "")
        t2 = Tool("b", "b", [], lambda ex: "")
        executor = ToolExecutor(tools=[t1, t2])
        assert len(executor.tools) == 2

    def test_get_tool(self):
        t1 = Tool("a", "a", [], lambda ex: "")
        executor = ToolExecutor(tools=[t1])
        assert executor.get_tool("a") is t1
        assert executor.get_tool("missing") is None


# ---------------------------------------------------------------------------
# Built-in handler tests (filesystem)
# ---------------------------------------------------------------------------


class TestReadFile:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("line1\nline2\nline3")
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="read_file", arguments={"path": str(f)})
        result = executor.execute(call)
        assert not result.is_error
        assert "line1" in result.output
        assert "line2" in result.output

    def test_truncates_long_file(self, tmp_path):
        f = tmp_path / "long.txt"
        f.write_text("\n".join(f"line {i}" for i in range(1000)))
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="read_file", arguments={"path": str(f), "max_lines": 10})
        result = executor.execute(call)
        assert "truncated" in result.output

    def test_missing_file(self, tmp_path):
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="read_file", arguments={"path": str(tmp_path / "nope.txt")})
        result = executor.execute(call)
        assert result.is_error


class TestListDirectory:
    def test_lists_entries(self, tmp_path):
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.py").touch()
        (tmp_path / "subdir").mkdir()
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="list_directory", arguments={"path": str(tmp_path)})
        result = executor.execute(call)
        assert "a.txt" in result.output
        assert "b.py" in result.output
        assert "subdir/" in result.output

    def test_glob_filter(self, tmp_path):
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.py").touch()
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="list_directory", arguments={"path": str(tmp_path), "pattern": "*.py"})
        result = executor.execute(call)
        assert "b.py" in result.output
        assert "a.txt" not in result.output

    def test_missing_dir(self, tmp_path):
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="list_directory", arguments={"path": str(tmp_path / "nope")})
        result = executor.execute(call)
        assert result.is_error


class TestSearchFiles:
    def test_finds_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("def world():\n    pass\n")
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="search_files", arguments={"pattern": "def hello", "path": str(tmp_path)})
        result = executor.execute(call)
        assert not result.is_error
        assert "hello" in result.output

    def test_no_matches(self, tmp_path):
        (tmp_path / "a.py").write_text("nothing here\n")
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="search_files", arguments={"pattern": "foobar", "path": str(tmp_path)})
        result = executor.execute(call)
        assert "No matches" in result.output


class TestWriteFile:
    def test_writes_file(self, tmp_path):
        target = str(tmp_path / "out.txt")
        executor = make_full_executor(writable_dirs=[str(tmp_path)], shell_confirmation=False)
        call = ToolCall(id="c1", name="write_file", arguments={"path": target, "content": "hello world"})
        result = executor.execute(call)
        assert not result.is_error
        assert Path(target).read_text() == "hello world"

    def test_creates_parent_dirs(self, tmp_path):
        target = str(tmp_path / "sub" / "dir" / "file.txt")
        executor = make_full_executor(writable_dirs=[str(tmp_path)], shell_confirmation=False)
        call = ToolCall(id="c1", name="write_file", arguments={"path": target, "content": "nested"})
        result = executor.execute(call)
        assert not result.is_error
        assert Path(target).read_text() == "nested"

    def test_blocked_by_policy(self, tmp_path):
        executor = make_full_executor(writable_dirs=["/tmp/allowed_only"], shell_confirmation=False)
        target = str(tmp_path / "out.txt")
        call = ToolCall(id="c1", name="write_file", arguments={"path": target, "content": "bad"})
        result = executor.execute(call)
        assert result.is_error
        assert "blocked" in result.output.lower()


class TestPatchFile:
    def test_patches_file(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("def old_name():\n    pass\n")
        executor = make_full_executor(writable_dirs=[str(tmp_path)], shell_confirmation=False)
        call = ToolCall(id="c1", name="patch_file", arguments={
            "path": str(f), "search": "old_name", "replace": "new_name",
        })
        result = executor.execute(call)
        assert not result.is_error
        assert "new_name" in f.read_text()

    def test_search_not_found(self, tmp_path):
        f = tmp_path / "code.py"
        f.write_text("hello")
        executor = make_full_executor(writable_dirs=[str(tmp_path)], shell_confirmation=False)
        call = ToolCall(id="c1", name="patch_file", arguments={
            "path": str(f), "search": "nonexistent", "replace": "new",
        })
        result = executor.execute(call)
        assert result.is_error


class TestRunShell:
    def test_runs_command(self):
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="run_shell", arguments={"command": "echo hello"})
        result = executor.execute(call)
        assert not result.is_error
        assert "hello" in result.output

    def test_blocked_command(self):
        executor = make_read_only_executor()
        call = ToolCall(id="c1", name="run_shell", arguments={"command": "rm -rf /"})
        result = executor.execute(call)
        assert result.is_error

    def test_confirmation_denied(self):
        executor = make_full_executor(
            shell_confirmation=True,
            confirm_callback=lambda cmd: False,
        )
        call = ToolCall(id="c1", name="run_shell", arguments={"command": "echo test"})
        result = executor.execute(call)
        assert "denied" in result.output

    def test_confirmation_accepted(self):
        executor = make_full_executor(
            shell_confirmation=True,
            confirm_callback=lambda cmd: True,
        )
        call = ToolCall(id="c1", name="run_shell", arguments={"command": "echo confirmed"})
        result = executor.execute(call)
        assert "confirmed" in result.output


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactories:
    def test_read_only_executor(self):
        ex = make_read_only_executor()
        names = {t.name for t in ex.tools}
        assert "read_file" in names
        assert "list_directory" in names
        assert "run_shell" in names
        assert "write_file" not in names

    def test_browse_only_executor(self):
        ex = make_browse_only_executor()
        names = {t.name for t in ex.tools}
        assert "read_file" in names
        assert "run_shell" not in names
        assert "write_file" not in names

    def test_full_executor(self):
        ex = make_full_executor()
        names = {t.name for t in ex.tools}
        assert "write_file" in names
        assert "patch_file" in names
        assert "run_shell" in names


# ---------------------------------------------------------------------------
# Tool constants
# ---------------------------------------------------------------------------


class TestToolSets:
    def test_all_tools_count(self):
        assert len(ALL_TOOLS) == 8

    def test_read_only_tools_count(self):
        assert len(READ_ONLY_TOOLS) == 6

    def test_browse_only_tools_count(self):
        assert len(BROWSE_ONLY_TOOLS) == 5

    def test_all_tools_unique_names(self):
        names = [t.name for t in ALL_TOOLS]
        assert len(names) == len(set(names))
