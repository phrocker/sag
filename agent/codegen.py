"""Phase 2: Code generation from Phase 1 analysis facts.

Components:
- Data models: FileSpec, CodeGenPlan, GeneratedFile, CodeGenResult
- extract_code_content(): extracts code from LLM fenced-block responses
- ClarificationAgent: asks user to resolve ambiguities before codegen
- CodeGenPlanner: produces a file manifest from Phase 1 facts
- CodeGenExecutor: generates files one at a time via LLM calls
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from codegen_prompts import (
    CLARIFY_SYSTEM_PROMPT,
    PLANNER_SYSTEM_PROMPT,
    build_file_gen_prompt,
    build_file_gen_user_message,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FileSpec:
    """Specification for a single file to generate."""

    path: str
    description: str
    language: str
    relevant_facts: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    max_tokens: int = 4096


@dataclass
class CodeGenPlan:
    """The full code generation plan (file manifest)."""

    files: list[FileSpec] = field(default_factory=list)
    project_structure: str = ""
    tech_stack: dict[str, str] = field(default_factory=dict)
    rationale: str = ""


@dataclass
class GeneratedFile:
    """Result of generating a single file."""

    spec: FileSpec
    content: str
    success: bool
    error: str | None = None


@dataclass
class CodeGenResult:
    """Aggregate result of the entire code generation phase."""

    plan: CodeGenPlan
    files: list[GeneratedFile] = field(default_factory=list)
    output_dir: str = ""
    files_written: int = 0
    files_failed: int = 0


@dataclass
class ClarificationResult:
    """Result of the clarification step."""

    needs_clarification: bool
    questions: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Code extraction
# ---------------------------------------------------------------------------


def extract_code_content(raw: str) -> str:
    """Extract code content from an LLM response.

    Tries to find a fenced code block (```...```). Falls back to detecting
    the start of code (import/def/class/#/etc.) and using the rest.
    Returns empty string if the response is an error marker (e.g. max
    tool turns reached) rather than real code.
    """
    # Guard: reject known error markers so they don't become file content
    if "max tool turns reached" in raw and len(raw) < 200:
        return ""

    # Try fenced code block first
    fence_match = re.search(r'```[\w]*\n(.*?)```', raw, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()

    # Fallback: detect code start patterns
    code_starts = re.compile(
        r'^(import |from |def |class |#!|#\s|package |'
        r'const |let |var |function |export |'
        r'<!DOCTYPE|<html|---\n|'
        r'\[|{)',
        re.MULTILINE,
    )
    match = code_starts.search(raw)
    if match:
        return raw[match.start():].strip()

    # Last resort: return as-is
    return raw.strip()


# ---------------------------------------------------------------------------
# Clarification agent
# ---------------------------------------------------------------------------


class ClarificationAgent:
    """Asks the LLM to identify ambiguities in the Phase 1 facts."""

    def __init__(self, client) -> None:
        self._client = client

    def check(self, task: str, facts: dict[str, str]) -> ClarificationResult:
        """Check if clarification is needed before code generation."""
        facts_text = "\n".join(f"  {k} = {v}" for k, v in facts.items())
        user_msg = f"# Task\n{task}\n\n# Design Facts\n{facts_text}"

        raw = self._client.complete(
            CLARIFY_SYSTEM_PROMPT,
            [{"role": "user", "content": user_msg}],
            max_tokens=1024,
        )
        return self._parse_response(raw)

    def _parse_response(self, raw: str) -> ClarificationResult:
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            return ClarificationResult(needs_clarification=False)

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return ClarificationResult(needs_clarification=False)

        return ClarificationResult(
            needs_clarification=bool(data.get("needs_clarification", False)),
            questions=data.get("questions", []),
            summary=data.get("summary", ""),
        )


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class CodeGenPlanner:
    """Produces a CodeGenPlan (file manifest) from Phase 1 facts."""

    def __init__(self, client=None, tool_client=None) -> None:
        self._client = tool_client or client

    def plan(self, task: str, facts: dict[str, str]) -> CodeGenPlan:
        """Create a code generation plan. Uses LLM if available, else template."""
        if self._client:
            result = self._plan_llm(task, facts)
            if result:
                return result
        return self._plan_echo(task, facts)

    def _plan_llm(self, task: str, facts: dict[str, str]) -> CodeGenPlan | None:
        """Ask the LLM to design a file manifest."""
        facts_text = "\n".join(f"  {k} = {v}" for k, v in facts.items())
        user_msg = f"# Task\n{task}\n\n# Design Facts from Analysis Phase\n{facts_text}"

        try:
            raw = self._client.complete(
                PLANNER_SYSTEM_PROMPT,
                [{"role": "user", "content": user_msg}],
                max_tokens=4096,
            )
            return self._parse_plan_json(raw)
        except Exception:
            return None

    def _parse_plan_json(self, raw: str) -> CodeGenPlan | None:
        """Parse a JSON file manifest from LLM output."""
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        files: list[FileSpec] = []
        for f in data.get("files", []):
            if not isinstance(f, dict) or "path" not in f:
                continue
            files.append(FileSpec(
                path=f["path"],
                description=f.get("description", ""),
                language=f.get("language", "unknown"),
                relevant_facts=f.get("relevant_facts", []),
                depends_on=f.get("depends_on", []),
                max_tokens=f.get("max_tokens", 4096),
            ))

        if not files:
            return None

        return CodeGenPlan(
            files=files,
            project_structure=data.get("project_structure", ""),
            tech_stack=data.get("tech_stack", {}),
            rationale=data.get("rationale", ""),
        )

    def _plan_echo(self, task: str, facts: dict[str, str]) -> CodeGenPlan:
        """Template-based plan for echo mode. Inspects fact topic prefixes."""
        # Detect what kind of project from fact topics
        prefixes = {k.split(".")[0] for k in facts}

        has_api = "api" in prefixes or "engineering" in prefixes
        has_frontend = "frontend" in prefixes or "ui" in prefixes
        has_db = any("database" in k or "model" in k for k in facts)

        files: list[FileSpec] = []
        structure_lines: list[str] = []
        tech: dict[str, str] = {"language": "python", "framework": "fastapi"}

        # Always include project-level files
        files.append(FileSpec(
            "requirements.txt", "Python dependencies", "text",
            max_tokens=512,
        ))
        files.append(FileSpec(
            "README.md", "Project documentation with setup instructions", "markdown",
            max_tokens=2048,
        ))
        files.append(FileSpec(
            "Dockerfile", "Container definition", "dockerfile",
            max_tokens=1024,
        ))

        # Config
        files.append(FileSpec(
            "src/config.py", "Application configuration and environment variables",
            "python", max_tokens=2048,
        ))

        # Models
        if has_db or has_api:
            files.append(FileSpec(
                "src/models.py", "Data models and database schema",
                "python", ["api.endpoints", "engineering.architecture"],
                max_tokens=4096,
            ))

        # API layer
        if has_api:
            files.append(FileSpec(
                "src/main.py", "FastAPI application entry point",
                "python", ["api.endpoints"],
                depends_on=["src/config.py"],
                max_tokens=2048,
            ))
            files.append(FileSpec(
                "src/routes.py", "API route definitions",
                "python", ["api.endpoints", "api.auth"],
                depends_on=["src/models.py", "src/main.py"],
                max_tokens=4096,
            ))
            files.append(FileSpec(
                "src/schemas.py", "Pydantic request/response schemas",
                "python", ["api.endpoints"],
                depends_on=["src/models.py"],
                max_tokens=4096,
            ))
            files.append(FileSpec(
                "src/auth.py", "Authentication and authorization",
                "python", ["api.auth", "security.controls"],
                depends_on=["src/config.py", "src/models.py"],
                max_tokens=4096,
            ))

        # Frontend layer
        if has_frontend:
            files.append(FileSpec(
                "src/static/index.html", "Main HTML page",
                "html", ["ui.layout", "ui.components"],
                max_tokens=4096,
            ))
            files.append(FileSpec(
                "src/static/app.js", "Frontend JavaScript application",
                "javascript", ["frontend.components", "frontend.state"],
                max_tokens=4096,
            ))
            files.append(FileSpec(
                "src/static/style.css", "Stylesheet",
                "css", ["ui.layout"],
                max_tokens=2048,
            ))

        # Tests
        files.append(FileSpec(
            "tests/__init__.py", "Test package init", "python", max_tokens=256,
        ))
        files.append(FileSpec(
            "tests/test_api.py", "API endpoint tests",
            "python", ["test.strategy"],
            depends_on=["src/routes.py", "src/models.py"],
            max_tokens=4096,
        ))

        # Build project structure string
        dirs: set[str] = set()
        for f in files:
            parts = Path(f.path).parts
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        for d in sorted(dirs):
            indent = "  " * (d.count("/"))
            structure_lines.append(f"{indent}{d.split('/')[-1]}/")
        for f in files:
            parts = Path(f.path).parts
            indent = "  " * (len(parts) - 1)
            structure_lines.append(f"{indent}{parts[-1]}")

        # Simpler: just build a flat sorted list
        structure = "\n".join(f.path for f in files)

        return CodeGenPlan(
            files=files,
            project_structure=structure,
            tech_stack=tech,
            rationale="Template-based plan from analysis fact topics.",
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class CodeGenExecutor:
    """Generates files one at a time via LLM calls."""

    def __init__(
        self,
        client=None,
        collector=None,
        on_file_start: Callable[[FileSpec, int, int], None] | None = None,
        on_file_done: Callable[[GeneratedFile, int, int], None] | None = None,
        tool_client=None,
    ) -> None:
        self._client = tool_client or client
        self._collector = collector
        self._on_file_start = on_file_start
        self._on_file_done = on_file_done

    def execute(
        self,
        plan: CodeGenPlan,
        task: str,
        facts: dict[str, str],
        output_dir: Path,
    ) -> CodeGenResult:
        """Generate all files in the plan and write them to output_dir."""
        result = CodeGenResult(
            plan=plan,
            output_dir=str(output_dir),
        )

        generated_content: dict[str, str] = {}  # path -> content
        total = len(plan.files)

        for idx, spec in enumerate(plan.files):
            if self._on_file_start:
                self._on_file_start(spec, idx, total)

            gen_file = self._generate_file(
                spec, task, facts, plan, generated_content,
            )
            result.files.append(gen_file)

            if gen_file.success:
                # Write to disk
                file_path = output_dir / spec.path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(gen_file.content, encoding="utf-8")
                result.files_written += 1
                generated_content[spec.path] = gen_file.content
            else:
                result.files_failed += 1

            if self._on_file_done:
                self._on_file_done(gen_file, idx, total)

        return result

    def _generate_file(
        self,
        spec: FileSpec,
        task: str,
        facts: dict[str, str],
        plan: CodeGenPlan,
        generated_so_far: dict[str, str],
    ) -> GeneratedFile:
        """Generate a single file. Uses LLM if available, else echo placeholder."""
        if self._collector:
            self._collector.set_current_agent(f"codegen:{spec.path}")

        if self._client:
            return self._generate_llm(spec, task, facts, plan, generated_so_far)
        return self._generate_echo(spec, facts)

    def _generate_llm(
        self,
        spec: FileSpec,
        task: str,
        facts: dict[str, str],
        plan: CodeGenPlan,
        generated_so_far: dict[str, str],
    ) -> GeneratedFile:
        """Generate a file via LLM call."""
        has_tools = hasattr(self._client, 'executor')
        system_prompt = build_file_gen_prompt(
            spec.path, spec.description, spec.language, has_tools=has_tools,
        )
        user_message = build_file_gen_user_message(
            spec_path=spec.path,
            spec_description=spec.description,
            task=task,
            facts=facts,
            relevant_fact_keys=spec.relevant_facts,
            project_structure=plan.project_structure,
            generated_so_far=generated_so_far,
            depends_on=spec.depends_on,
        )

        try:
            raw = self._client.complete(
                system_prompt,
                [{"role": "user", "content": user_message}],
                max_tokens=spec.max_tokens,
            )
            content = extract_code_content(raw)
            if not content:
                return GeneratedFile(
                    spec=spec, content="", success=False,
                    error="LLM produced no usable code (possible tool turn exhaustion)",
                )
            return GeneratedFile(spec=spec, content=content, success=True)
        except Exception as e:
            return GeneratedFile(
                spec=spec, content="", success=False, error=str(e),
            )

    def _generate_echo(
        self, spec: FileSpec, facts: dict[str, str],
    ) -> GeneratedFile:
        """Echo mode: write a placeholder file showing purpose and relevant facts."""
        lines: list[str] = []

        # Pick comment style based on language
        comment = "#"
        if spec.language in ("javascript", "typescript", "java", "css", "c", "go", "rust"):
            comment = "//"
        elif spec.language in ("html", "xml"):
            comment = "<!--"
        elif spec.language in ("markdown",):
            comment = "<!--"

        close = ""
        if comment == "<!--":
            close = " -->"

        lines.append(f"{comment} {spec.path}{close}")
        lines.append(f"{comment} Purpose: {spec.description}{close}")
        lines.append(f"{comment} Language: {spec.language}{close}")
        lines.append(f"{comment}{close}")

        if spec.relevant_facts:
            lines.append(f"{comment} Relevant design facts:{close}")
            for key in spec.relevant_facts:
                val = facts.get(key, "(not available)")
                val_str = str(val)
                if len(val_str) > 100:
                    val_str = val_str[:97] + "..."
                lines.append(f"{comment}   {key} = {val_str}{close}")
            lines.append(f"{comment}{close}")

        if spec.depends_on:
            lines.append(f"{comment} Dependencies: {', '.join(spec.depends_on)}{close}")
            lines.append(f"{comment}{close}")

        lines.append(f"{comment} TODO: implement{close}")
        lines.append("")

        return GeneratedFile(
            spec=spec, content="\n".join(lines), success=True,
        )


# ---------------------------------------------------------------------------
# Edit agent — modify existing files via tool-aware LLM
# ---------------------------------------------------------------------------

_EDIT_SYSTEM_PROMPT = """\
You are a senior software engineer editing an existing file.

You have tools available. ALWAYS use them:
1. First, use read_file to see the current contents of the file
2. Understand the code structure and what needs to change
3. Use patch_file to make targeted modifications
4. Use read_file again to verify your changes are correct

If the edit requires understanding other files in the project, use read_file \
or search_files to gather context first.

After making changes, briefly describe what you changed and why.
"""


class EditAgent:
    """Modifies existing files using a tool-aware LLM client."""

    def __init__(self, client, collector=None) -> None:
        self._client = client
        self._collector = collector

    def edit(self, file_path: str, instruction: str) -> str:
        """Edit a file according to the instruction. Returns summary of changes."""
        if self._collector:
            self._collector.set_current_agent(f"edit:{Path(file_path).name}")

        user_msg = (
            f"File to edit: {file_path}\n\n"
            f"Instruction: {instruction}\n\n"
            "Read the file, make the necessary changes with patch_file, "
            "and verify the result."
        )

        try:
            return self._client.complete(
                _EDIT_SYSTEM_PROMPT,
                [{"role": "user", "content": user_msg}],
                max_tokens=1024,
            )
        except Exception as e:
            return f"Edit failed: {e}"


# ---------------------------------------------------------------------------
# Project runner — execute and test the generated project
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Result of running a command on the generated project."""

    command: str
    output: str
    exit_code: int
    success: bool


class ProjectRunner:
    """Runs commands in the context of the generated project."""

    def __init__(self, output_dir: str) -> None:
        self._output_dir = output_dir

    def run(self, command: str, timeout: int = 30) -> RunResult:
        """Run a shell command in the output directory."""
        import subprocess

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._output_dir,
            )
            output_parts: list[str] = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(result.stderr)
            output = "\n".join(output_parts) if output_parts else "(no output)"
            return RunResult(
                command=command,
                output=output,
                exit_code=result.returncode,
                success=result.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            return RunResult(
                command=command,
                output=f"Command timed out after {timeout}s",
                exit_code=-1,
                success=False,
            )
        except Exception as e:
            return RunResult(
                command=command,
                output=str(e),
                exit_code=-1,
                success=False,
            )

    def verify_syntax(self) -> list[RunResult]:
        """Run syntax checks on generated files."""
        import sys

        results: list[RunResult] = []
        output_path = Path(self._output_dir)

        if not output_path.exists():
            return results

        python = sys.executable or "python3"

        # Check Python files — use relative paths since run() sets cwd
        for py_file in sorted(output_path.rglob("*.py")):
            rel = py_file.relative_to(output_path)
            r = self.run(f"{python} -m py_compile {rel}", timeout=10)
            r.command = f"py_compile {rel}"
            results.append(r)

        return results

    def run_tests(self, command: str | None = None, timeout: int = 60) -> TestResult:
        """Run tests and parse results into structured output.

        If no command given, auto-detects test framework from project files.
        """
        if command is None:
            command = self._detect_test_command()

        run_result = self.run(command, timeout=timeout)
        return TestResultParser.parse(run_result.output, run_result.exit_code)

    def _detect_test_command(self) -> str:
        """Auto-detect the appropriate test command."""
        import sys

        output_path = Path(self._output_dir)
        python = sys.executable or "python3"

        if (output_path / "pytest.ini").exists() or (output_path / "pyproject.toml").exists():
            return f"{python} -m pytest -v"
        if (output_path / "setup.py").exists():
            return f"{python} -m pytest -v"
        if (output_path / "package.json").exists():
            return "npm test"
        if (output_path / "go.mod").exists():
            return "go test ./..."
        if (output_path / "Cargo.toml").exists():
            return "cargo test"
        # Default to pytest for Python projects
        if any(output_path.rglob("*.py")):
            return f"{python} -m pytest -v"
        return "echo 'No test framework detected'"


# ---------------------------------------------------------------------------
# Test result parsing
# ---------------------------------------------------------------------------


@dataclass
class TestCase:
    """A single test case result."""

    name: str
    status: str  # "passed", "failed", "error", "skipped"
    message: str = ""


@dataclass
class TestResult:
    """Structured test execution result."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    success: bool = True
    cases: list[TestCase] = field(default_factory=list)
    raw_output: str = ""
    framework: str = "unknown"

    @property
    def summary(self) -> str:
        parts = []
        if self.passed:
            parts.append(f"{self.passed} passed")
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.errors:
            parts.append(f"{self.errors} errors")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        return ", ".join(parts) if parts else "no tests"


class TestResultParser:
    """Parses test output from various frameworks into structured TestResult."""

    @staticmethod
    def parse(output: str, exit_code: int = 0) -> TestResult:
        """Auto-detect framework and parse test output."""
        if "pytest" in output or "PASSED" in output or "FAILED" in output:
            result = TestResultParser._parse_pytest(output)
        elif "--- PASS" in output or "--- FAIL" in output:
            result = TestResultParser._parse_go(output)
        elif "Tests:" in output and ("suites" in output.lower() or "test suites" in output.lower()):
            result = TestResultParser._parse_jest(output)
        else:
            result = TestResultParser._parse_generic(output, exit_code)

        result.raw_output = output
        result.success = result.failed == 0 and result.errors == 0 and exit_code == 0
        return result

    @staticmethod
    def _parse_pytest(output: str) -> TestResult:
        """Parse pytest -v output."""
        result = TestResult(framework="pytest")

        # Parse individual test lines: "test_file.py::test_name PASSED"
        test_line_re = re.compile(
            r'([\w/\\.-]+::[\w.-]+(?:\[.*?\])?)\s+(PASSED|FAILED|ERROR|SKIPPED)'
        )
        for match in test_line_re.finditer(output):
            name = match.group(1)
            status_raw = match.group(2).lower()
            status = "error" if status_raw == "error" else status_raw
            result.cases.append(TestCase(name=name, status=status))

        # Parse summary line: "5 passed, 2 failed, 1 error in 1.23s"
        summary_re = re.compile(
            r'=+\s*(.*?)\s*=+'
        )
        for match in summary_re.finditer(output):
            summary_text = match.group(1)
            passed_m = re.search(r'(\d+)\s+passed', summary_text)
            failed_m = re.search(r'(\d+)\s+failed', summary_text)
            error_m = re.search(r'(\d+)\s+error', summary_text)
            skipped_m = re.search(r'(\d+)\s+skipped', summary_text)

            if passed_m:
                result.passed = int(passed_m.group(1))
            if failed_m:
                result.failed = int(failed_m.group(1))
            if error_m:
                result.errors = int(error_m.group(1))
            if skipped_m:
                result.skipped = int(skipped_m.group(1))

        # If no summary line found, count from individual test lines
        if result.passed == 0 and result.failed == 0 and result.cases:
            result.passed = sum(1 for c in result.cases if c.status == "passed")
            result.failed = sum(1 for c in result.cases if c.status == "failed")
            result.errors = sum(1 for c in result.cases if c.status == "error")
            result.skipped = sum(1 for c in result.cases if c.status == "skipped")

        result.total = result.passed + result.failed + result.errors + result.skipped

        # Extract failure details
        failure_re = re.compile(
            r'FAILED\s+([\w/\\.-]+::[\w.-]+(?:\[.*?\])?)\s*-\s*(.*?)$',
            re.MULTILINE,
        )
        for match in failure_re.finditer(output):
            name = match.group(1)
            msg = match.group(2).strip()
            for case in result.cases:
                if case.name == name:
                    case.message = msg

        return result

    @staticmethod
    def _parse_go(output: str) -> TestResult:
        """Parse `go test ./...` output."""
        result = TestResult(framework="go")

        # "--- PASS: TestName (0.00s)"  or  "--- FAIL: TestName (0.00s)"
        go_test_re = re.compile(
            r'---\s+(PASS|FAIL|SKIP):\s+(\S+)\s+\(([^)]+)\)'
        )
        for match in go_test_re.finditer(output):
            status_raw = match.group(1).lower()
            name = match.group(2)
            status = {"pass": "passed", "fail": "failed", "skip": "skipped"}.get(
                status_raw, status_raw
            )
            result.cases.append(TestCase(name=name, status=status))

        result.passed = sum(1 for c in result.cases if c.status == "passed")
        result.failed = sum(1 for c in result.cases if c.status == "failed")
        result.skipped = sum(1 for c in result.cases if c.status == "skipped")
        result.total = len(result.cases)

        return result

    @staticmethod
    def _parse_jest(output: str) -> TestResult:
        """Parse jest/vitest output."""
        result = TestResult(framework="jest")

        # "Tests:  2 failed, 5 passed, 7 total"
        tests_re = re.compile(
            r'Tests:\s+(?:(\d+)\s+failed,?\s*)?(?:(\d+)\s+skipped,?\s*)?'
            r'(?:(\d+)\s+passed,?\s*)?(\d+)\s+total'
        )
        match = tests_re.search(output)
        if match:
            result.failed = int(match.group(1) or 0)
            result.skipped = int(match.group(2) or 0)
            result.passed = int(match.group(3) or 0)
            result.total = int(match.group(4) or 0)

        # Individual test lines: "✓ test name (5ms)" or "✕ test name"
        pass_re = re.compile(r'[✓✔✅]\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$', re.MULTILINE)
        fail_re = re.compile(r'[✕✗❌×]\s+(.+?)(?:\s+\(\d+\s*m?s\))?\s*$', re.MULTILINE)
        for match in pass_re.finditer(output):
            result.cases.append(TestCase(name=match.group(1).strip(), status="passed"))
        for match in fail_re.finditer(output):
            result.cases.append(TestCase(name=match.group(1).strip(), status="failed"))

        return result

    @staticmethod
    def _parse_generic(output: str, exit_code: int) -> TestResult:
        """Fallback parser — count pass/fail keywords."""
        result = TestResult(framework="generic")

        # Try to count "ok" and "not ok" (TAP format)
        ok_count = len(re.findall(r'^ok\b', output, re.MULTILINE))
        not_ok_count = len(re.findall(r'^not ok\b', output, re.MULTILINE))

        if ok_count + not_ok_count > 0:
            result.passed = ok_count
            result.failed = not_ok_count
            result.total = ok_count + not_ok_count
        else:
            # Bare minimum: exit code
            result.success = exit_code == 0
            result.total = 1
            if exit_code == 0:
                result.passed = 1
            else:
                result.failed = 1

        return result
