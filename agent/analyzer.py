"""Task analyzer that proposes agent trees based on task description.

In LLM mode, asks the model to design a team. In echo mode, uses
keyword matching against predefined templates.

Phase 0 pre-analysis uses tool-aware LLM calls to explore the project
filesystem before designing the team.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python-sag", "src"))

from sag.prompt import LLMClient
from sag.tools import ToolExecutor
from sag.tree import TreeEngine


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AgentSpec:
    """Specification for a single agent in a proposed tree."""

    agent_id: str
    role: str
    parent_id: str | None  # None = root
    topics: list[str] = field(default_factory=list)
    prompt: str = ""


@dataclass
class TreeProposal:
    """A proposed agent tree for a task."""

    agents: list[AgentSpec] = field(default_factory=list)
    rationale: str = ""


# ---------------------------------------------------------------------------
# Templates for echo mode
# ---------------------------------------------------------------------------

_SOFTWARE_AGENTS = [
    AgentSpec("pm", "Project Manager", None,
              ["project.plan", "project.risks", "project.timeline"],
              "You are a Project Manager. Synthesize reports from your leads into a concrete project plan with prioritized tasks, risk register, and timeline."),
    AgentSpec("design-lead", "Design Lead", "pm",
              ["design.strategy", "design.system"],
              "You are a Design Lead. Merge UI and UX reports into a unified design specification with component inventory and design tokens."),
    AgentSpec("eng-lead", "Engineering Lead", "pm",
              ["engineering.architecture", "engineering.stack"],
              "You are an Engineering Lead. Merge API and Frontend reports into an architecture decision record with system diagram and tech stack."),
    AgentSpec("qa-lead", "QA Lead", "pm",
              ["quality.plan", "quality.risks"],
              "You are a QA Lead. Merge Test and Security reports into quality gate specs with acceptance criteria and compliance requirements."),
    AgentSpec("ui", "UI Specialist", "design-lead",
              ["ui.components", "ui.layout"],
              "You are a UI specialist. Produce a list of UI components, layout grid spec, and responsive behavior description."),
    AgentSpec("ux", "UX Specialist", "design-lead",
              ["ux.flows", "ux.accessibility"],
              "You are a UX specialist. Produce user flows, WCAG 2.1 AA checklist, and information architecture outline."),
    AgentSpec("api", "API Architect", "eng-lead",
              ["api.endpoints", "api.auth"],
              "You are an API architect. Produce REST endpoint table, authentication flow, and rate limiting rules."),
    AgentSpec("frontend", "Frontend Architect", "eng-lead",
              ["frontend.components", "frontend.state"],
              "You are a Frontend architect. Produce component tree, state management plan, and routing table."),
    AgentSpec("test", "Test Strategist", "qa-lead",
              ["test.strategy", "test.coverage"],
              "You are a Test strategist. Produce test matrix, coverage targets, and CI pipeline stages."),
    AgentSpec("security", "Security Analyst", "qa-lead",
              ["security.threats", "security.controls"],
              "You are a Security analyst. Produce threat model (STRIDE), security controls, and auth/authz matrix."),
]

_DATA_AGENTS = [
    AgentSpec("lead", "Data Lead", None,
              ["project.findings", "project.recommendations"],
              "You are a Data Lead. Synthesize analyst reports into key findings and actionable recommendations."),
    AgentSpec("collection", "Data Collection", "lead",
              ["data.sources", "data.quality"],
              "You are a Data Collection specialist. Identify data sources, assess data quality, and flag gaps."),
    AgentSpec("analysis", "Data Analyst", "lead",
              ["analysis.patterns", "analysis.metrics"],
              "You are a Data Analyst. Identify patterns, compute key metrics, and produce statistical summaries."),
    AgentSpec("viz", "Visualization Specialist", "lead",
              ["viz.charts", "viz.dashboards"],
              "You are a Visualization specialist. Design chart types, dashboard layouts, and narrative flow."),
]

_CONTENT_AGENTS = [
    AgentSpec("editor", "Editor-in-Chief", None,
              ["content.plan", "content.schedule"],
              "You are an Editor-in-Chief. Synthesize research and writing into a content plan with publishing schedule."),
    AgentSpec("researcher", "Research Analyst", "editor",
              ["research.topics", "research.sources"],
              "You are a Research Analyst. Identify topics, gather sources, and produce research briefs."),
    AgentSpec("writer", "Content Writer", "editor",
              ["writing.outline", "writing.drafts"],
              "You are a Content Writer. Produce outlines, draft key sections, and suggest headlines."),
    AgentSpec("seo", "SEO Strategist", "editor",
              ["seo.keywords", "seo.structure"],
              "You are an SEO Strategist. Research keywords, suggest content structure, and optimize for search."),
]

_CHAOS_AGENTS = [
    AgentSpec("chaos-lead", "Chaos Lead", None,
              ["chaos.summary", "chaos.findings", "chaos.recommendations"],
              "You are a Chaos Engineering Lead. Synthesize reports from your specialists into a resilience assessment. "
              "Identify the most critical failure modes, rank them by blast radius, and recommend hardening priorities."),
    AgentSpec("fault-injector", "Fault Injector", "chaos-lead",
              ["fault.targets", "fault.injections", "fault.techniques"],
              "You are a Fault Injection Specialist. Identify WHERE and HOW to inject faults.\n\n"
              "EXPLORATION STRATEGY (follow this order):\n"
              "1. list_directory the project root to understand structure\n"
              "2. read_file the main entry point(s) and config files to understand architecture\n"
              "3. list_directory each source package/directory to see modules\n"
              "4. read_file 3-5 critical modules (routes, services, models, database) — NOT the whole project\n"
              "5. search_files for SPECIFIC patterns in SPECIFIC directories, e.g.:\n"
              "   - search_files('requests\\.', 'src/services') for HTTP calls\n"
              "   - search_files('connect|cursor|session', 'src/db') for DB connections\n"
              "   Do NOT grep broad patterns like 'try|except' across the entire project.\n\n"
              "For each fault target found, describe: the file, the function, the fault to inject "
              "(e.g. raise exception, return None, add 5s delay, corrupt response), and expected impact.\n"
              "Output ASSERT statements with the fault injection plan."),
    AgentSpec("observer", "Resilience Observer", "chaos-lead",
              ["observe.error_handling", "observe.graceful_degradation", "observe.recovery"],
              "You are a Resilience Observer. Analyze existing error handling and recovery mechanisms.\n\n"
              "EXPLORATION STRATEGY (follow this order):\n"
              "1. list_directory the project root, then each source directory\n"
              "2. read_file the main entry point to understand the app's error handling philosophy\n"
              "3. Pick 3-5 key modules and read_file each one fully — look for:\n"
              "   - How exceptions are caught and handled\n"
              "   - Whether errors are logged or silently swallowed\n"
              "   - Retry logic, circuit breakers, fallback values\n"
              "   - Timeout configurations\n"
              "4. search_files for 'except.*pass' or 'except.*:' in specific directories to spot bare excepts\n\n"
              "Rate each module's resilience: robust, fragile, or missing. "
              "Be specific — cite the file and function name."),
    AgentSpec("blast-analyst", "Blast Radius Analyst", "chaos-lead",
              ["blast.dependencies", "blast.critical_paths", "blast.cascading"],
              "You are a Blast Radius Analyst. Map dependencies and identify cascading failure paths.\n\n"
              "EXPLORATION STRATEGY (follow this order):\n"
              "1. list_directory the project root to see all top-level modules\n"
              "2. read_file requirements.txt/pyproject.toml/package.json to see external dependencies\n"
              "3. Pick each source module and search_files for 'import' or 'from.*import' WITHIN that module only\n"
              "4. read_file the database/config layer to understand shared state\n"
              "5. read_file the routing/API layer to understand which endpoints depend on which services\n\n"
              "Build a dependency map: Module A -> Module B -> External Service X.\n"
              "Identify single points of failure and rate blast radius: isolated, moderate, catastrophic."),
    AgentSpec("recovery-validator", "Recovery Validator", "chaos-lead",
              ["recovery.mechanisms", "recovery.gaps", "recovery.test_coverage"],
              "You are a Recovery Validation Specialist. Assess whether the codebase can recover from faults.\n\n"
              "EXPLORATION STRATEGY (follow this order):\n"
              "1. list_directory to find test directories (tests/, test/, spec/, __tests__/)\n"
              "2. list_directory the test directory to see what's tested\n"
              "3. read_file 3-5 test files to see if they test error/failure scenarios\n"
              "4. search_files for 'raises|pytest.raises|assertRaises|expect.*throw' in the test directory\n"
              "5. read_file any health check or startup/shutdown modules\n\n"
              "Flag specific recovery gaps: which error paths have no tests, which services have no retry logic, "
              "which database operations have no transaction rollback. Cite file and function names."),
]

_GENERIC_AGENTS = [
    AgentSpec("coordinator", "Coordinator", None,
              ["project.summary", "project.next_steps"],
              "You are a Coordinator. Synthesize specialist reports into a summary with clear next steps."),
    AgentSpec("researcher", "Researcher", "coordinator",
              ["research.findings", "research.gaps"],
              "You are a Researcher. Investigate the topic, identify key findings, and flag knowledge gaps."),
    AgentSpec("analyst", "Analyst", "coordinator",
              ["analysis.assessment", "analysis.risks"],
              "You are an Analyst. Assess feasibility, identify risks, and provide structured evaluation."),
    AgentSpec("planner", "Planner", "coordinator",
              ["plan.steps", "plan.resources"],
              "You are a Planner. Break the task into actionable steps, estimate resources, and define milestones."),
]

TEMPLATES: dict[str, tuple[list[AgentSpec], str]] = {
    "software": (
        _SOFTWARE_AGENTS,
        "Software development requires design, engineering, and QA across "
        "UI/UX, API/frontend, and test/security specialties.",
    ),
    "data": (
        _DATA_AGENTS,
        "Data tasks need collection, analysis, and visualization working "
        "under a lead who synthesizes findings.",
    ),
    "content": (
        _CONTENT_AGENTS,
        "Content creation benefits from research, writing, and SEO "
        "coordinated by an editorial lead.",
    ),
    "chaos": (
        _CHAOS_AGENTS,
        "Chaos engineering requires fault injection, resilience observation, "
        "blast radius analysis, and recovery validation under a chaos lead.",
    ),
    "generic": (
        _GENERIC_AGENTS,
        "General tasks benefit from research, analysis, and planning "
        "coordinated by a single lead.",
    ),
}

_SOFTWARE_KEYWORDS = {
    "api", "rest", "graphql", "code", "build", "app", "web", "frontend",
    "backend", "database", "auth", "deploy", "test", "microservice",
    "server", "endpoint", "crud", "sdk", "library", "framework",
    "mobile", "react", "vue", "django", "flask", "node",
}
_DATA_KEYWORDS = {
    "data", "analytics", "dashboard", "metrics", "report", "visualization",
    "dataset", "etl", "pipeline", "warehouse", "bi", "statistics",
}
_CONTENT_KEYWORDS = {
    "content", "blog", "article", "marketing", "campaign", "social",
    "brand", "copy", "newsletter", "seo", "editorial",
}
_CHAOS_KEYWORDS = {
    "chaos", "fault", "resilience", "reliability", "failure", "inject",
    "blast", "recovery", "degrade", "graceful", "stress", "break",
    "fragile", "robust", "error", "crash", "timeout", "retry",
    "circuit", "breaker", "failover", "fallback", "outage",
}

# ---------------------------------------------------------------------------
# Exploration discipline footer (appended to every specialist agent prompt)
# ---------------------------------------------------------------------------

_EXPLORATION_FOOTER = """

EXPLORATION DISCIPLINE (mandatory):
1. list_directory the project root first
2. read_file 3-5 critical modules — NOT the entire project
3. search_files for SPECIFIC patterns in SPECIFIC directories only
HARD CONSTRAINTS:
- Never search_files across the entire project root
- Never read more than 8 files total
- Always cite specific file paths and function names"""


def extract_project_dir(task: str) -> str | None:
    """Extract an absolute directory path from a task description.

    Looks for absolute paths (starting with ``/``) in the task string
    and returns the first one that exists as a directory on disk.
    Returns ``None`` if no valid directory path is found.
    """
    # Match absolute paths — stop at quotes, whitespace, or end of string
    candidates = re.findall(r'(/[^\s\'",:;]+)', task)
    for candidate in candidates:
        # Strip trailing punctuation that might have been captured
        candidate = candidate.rstrip(".,;:!?)")
        if Path(candidate).is_dir():
            return candidate
    return None


def match_template(task: str) -> str:
    """Pick the best template name based on task keywords."""
    task_words = set(re.findall(r'[a-z]+', task.lower()))

    scores = {
        "software": len(task_words & _SOFTWARE_KEYWORDS),
        "data": len(task_words & _DATA_KEYWORDS),
        "content": len(task_words & _CONTENT_KEYWORDS),
        "chaos": len(task_words & _CHAOS_KEYWORDS),
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    return "generic"


# ---------------------------------------------------------------------------
# LLM prompt for agent design
# ---------------------------------------------------------------------------

_ANALYZER_SYSTEM_PROMPT = """\
You design teams of AI agents to analyze and plan tasks.

Given a task, output a SAG message containing a KNOW statement with the team proposal.
The message MUST follow this exact format:

H v 1 id=proposal src=designer dst=planner ts=0
KNOW team.proposal = {"rationale": "Why this team fits", "agents": [{"id": "short-id", "role": "Human Readable Role", "parent": null, "topics": ["topic.one", "topic.two"], "prompt": "You are a ... Produce: ..."}]} v 1

Rules:
- The KNOW value must be a single-line JSON object (no newlines inside the JSON).
- First agent MUST have "parent": null — this is the root coordinator.
- All other agents reference their parent's "id".
- Use 2-3 levels deep, 5-12 agents total.
- Topic strings are dot-separated (e.g. "api.endpoints").
- Each agent prompt should ask it to output SAG ASSERT statements:
  A topic.name = "your analysis"
- Output ONLY the SAG message. No markdown fences, no explanation outside the message.
"""

_CHAOS_SAG_SYSTEM_PROMPT = """\
You design chaos engineering teams tailored to a specific project.

You will receive a task description and a Phase 0 context summary describing the \
project's structure, tech stack, and key files. Design a team of chaos engineering \
agents that target THIS specific project — not generic chaos.

Output a SAG message containing a KNOW statement with your team proposal. \
The message MUST follow this exact format:

H v 1 id=proposal src=designer dst=planner ts=0
KNOW team.proposal = {"rationale": "Why this team fits the project", "agents": [{"id": "chaos-lead", "role": "Chaos Lead", "parent": null, "topics": ["chaos.summary"], "prompt": "You are a Chaos Lead. ..."}]} v 1

SAG syntax rules:
- Header line starts with H and has version, id, src, dst, ts fields.
- KNOW statement: KNOW <topic> = <json_value> v <version>
- The JSON value must be on a SINGLE LINE (no newlines inside the JSON).
- version must be a positive integer.

Coverage categories (include at least one agent for each):
1. Fault Injection — WHERE and HOW to inject faults in this project's code
2. Resilience — evaluate error handling, retry logic, circuit breakers
3. Blast Radius — map dependencies, find cascading failure paths
4. Recovery — assess test coverage of error paths, rollback mechanisms

Agent design rules:
- First agent MUST be "chaos-lead" with "parent": null (root coordinator).
- All other agents have "parent": "chaos-lead".
- Use 4-7 agents total (1 lead + 3-6 specialists).
- Topic strings are dot-separated (e.g. "fault.targets", "blast.dependencies").
- Each specialist prompt MUST reference specific aspects of the project from the context.
- Each specialist prompt should instruct agents to use tools (list_directory, read_file, search_files) \
and output SAG ASSERT statements.

Good specialist prompt example:
  "You are a Fault Injection Specialist for a Flask web app. \
Focus on routes in src/routes/ and database calls in src/db/. \
Use read_file to examine error handling in each route handler. \
search_files for 'requests.' in src/services/ to find HTTP calls that lack timeouts. \
For each fault target, describe the file, function, fault to inject, and expected impact."

Bad specialist prompt example (too vague):
  "You are a Fault Injector. Find things that could break."

Output ONLY the SAG message. No markdown fences, no explanation outside the message.
"""


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


_PRE_ANALYZE_SYSTEM_PROMPT = """\
You are a project analyst. Your job is to explore a project's filesystem \
and understand its structure before a team of agents is designed.

Use your tools to explore the project directory specified by the user:
1. List the project directory to see what files/folders exist
2. Read key files: README, package.json, pyproject.toml, Makefile, etc.
3. Search for patterns that reveal the project's tech stack

Then output a concise summary (under 500 words) of:
- Project type and tech stack
- Directory structure overview
- Key entry points and configuration files
- What already exists vs what needs to be built

Output ONLY the summary text. No markdown fences, no JSON.
"""


class TaskAnalyzer:
    """Proposes agent trees based on task description."""

    def __init__(
        self,
        client: LLMClient | None = None,
        tool_client=None,
    ) -> None:
        self._client = client
        self._tool_client = tool_client

    def pre_analyze(self, task: str, project_dir: str | None = None) -> str:
        """Phase 0: Explore the project with tools before designing a team.

        Returns a grounded context string that describes what already exists
        in the project directory.

        Args:
            task: The task description.
            project_dir: Explicit project directory to explore. If ``None``,
                attempts to extract a path from the task string, falling back
                to the current directory.

        In echo mode (no tool_client), returns the output of list_directory.
        """
        target = project_dir or extract_project_dir(task) or "."
        if self._tool_client is not None:
            return self._pre_analyze_with_tools(task, target)
        return self._pre_analyze_echo(target)

    def _pre_analyze_with_tools(self, task: str, project_dir: str = ".") -> str:
        """Use the tool-aware LLM client to explore the project."""
        user_msg = (
            f"Task: {task}\n\n"
            f"Please explore the project directory at: {project_dir}\n"
            f"Start by listing {project_dir}, then read any README or "
            "configuration files you find."
        )
        try:
            result = self._tool_client.complete(
                _PRE_ANALYZE_SYSTEM_PROMPT,
                [{"role": "user", "content": user_msg}],
                max_tokens=1024,
            )
            return result
        except Exception:
            return self._pre_analyze_echo(project_dir)

    def _pre_analyze_echo(self, project_dir: str = ".") -> str:
        """Fallback: list the project directory without tools."""
        from sag.tools import ToolCall, ToolExecutor, make_read_only_executor

        executor = make_read_only_executor()
        call = ToolCall(id="pre_0", name="list_directory", arguments={"path": project_dir})
        result = executor.execute(call)

        lines = ["Project directory contents:", result.output]

        # Try to read README
        for name in ("README.md", "README.rst", "README.txt", "README"):
            readme_path = Path(project_dir) / name
            if readme_path.is_file():
                read_call = ToolCall(
                    id="pre_1", name="read_file",
                    arguments={"path": str(readme_path), "max_lines": 50},
                )
                read_result = executor.execute(read_call)
                if not read_result.is_error:
                    lines.append(f"\n{name}:")
                    lines.append(read_result.output)
                break

        return "\n".join(lines)

    def propose(self, task: str, context: str = "") -> TreeProposal:
        """Propose an agent tree for the given task.

        If context is provided (e.g. from pre_analyze), it is included
        in the LLM prompt to ground the team design.

        Chaos template uses hybrid SAG-native design when an LLM client
        and project context are available. Other specialized templates
        (data, content) always use their static definitions.
        """
        template = match_template(task)

        # Chaos: try hybrid SAG-native design, fall back to static template
        if template == "chaos":
            if self._client and context:
                proposal = self._propose_hybrid(
                    task, context,
                    _CHAOS_SAG_SYSTEM_PROMPT, _EXPLORATION_FOOTER,
                )
                if proposal:
                    return proposal
            agents, rationale = TEMPLATES["chaos"]
            return TreeProposal(agents=list(agents), rationale=rationale)

        # Other specialized templates: always static
        if template not in ("software", "generic"):
            agents, rationale = TEMPLATES[template]
            return TreeProposal(agents=list(agents), rationale=rationale)

        # Software / generic: try LLM design, fall back to template
        if self._client:
            proposal = self._propose_llm(task, context)
            if proposal:
                return proposal
        return self._propose_echo(task)

    def _propose_llm(self, task: str, context: str = "") -> TreeProposal | None:
        """Ask the LLM to design a team using SAG KNOW output."""
        try:
            user_parts = [f"Task: {task}"]
            if context:
                user_parts.append(f"\n# Project Context\n{context}")
            messages = [{"role": "user", "content": "\n".join(user_parts)}]
            raw = self._client.complete(_ANALYZER_SYSTEM_PROMPT, messages, 2048)
            return _parse_proposal_sag(raw)
        except Exception:
            return None

    def _propose_hybrid(
        self,
        task: str,
        context: str,
        system_prompt: str,
        exploration_footer: str,
    ) -> TreeProposal | None:
        """LLM-designed team with SAG-native proposal and exploration footer.

        Calls the LLM with a SAG-aware system prompt that includes the
        Phase 0 project context. Parses the response as a SAG ``KNOW``
        statement and appends *exploration_footer* to every non-root agent.
        """
        try:
            user_parts = [
                f"Task: {task}",
                f"\n# Project Context\n{context}",
            ]
            messages = [{"role": "user", "content": "\n".join(user_parts)}]
            raw = self._client.complete(system_prompt, messages, 2048)
            proposal = _parse_proposal_sag(raw)
            if proposal is None:
                return None

            # Append exploration footer to every non-root agent
            for agent in proposal.agents:
                if agent.parent_id is not None:
                    agent.prompt += exploration_footer

            return proposal
        except Exception:
            return None

    def _propose_echo(self, task: str) -> TreeProposal:
        """Use keyword matching to pick a predefined template."""
        name = match_template(task)
        agents, rationale = TEMPLATES[name]
        return TreeProposal(agents=list(agents), rationale=rationale)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_proposal_from_dict(data: dict) -> TreeProposal | None:
    """Convert a dict with ``agents`` list to a :class:`TreeProposal`.

    Shared by both SAG and JSON parsing paths.
    """
    agents: list[AgentSpec] = []
    for a in data.get("agents", []):
        if not isinstance(a, dict) or "id" not in a or "role" not in a:
            continue
        agents.append(AgentSpec(
            agent_id=a["id"],
            role=a["role"],
            parent_id=a.get("parent"),
            topics=a.get("topics", []),
            prompt=a.get("prompt", f"You are a {a['role']}."),
        ))

    if not agents:
        return None

    return TreeProposal(
        agents=agents,
        rationale=data.get("rationale", ""),
    )


def _parse_proposal_json(raw: str) -> TreeProposal | None:
    """Extract and parse a TreeProposal from LLM JSON output."""
    json_match = re.search(r'\{[\s\S]*\}', raw)
    if not json_match:
        return None
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return None
    return _build_proposal_from_dict(data)


def _parse_proposal_sag(raw: str) -> TreeProposal | None:
    """Parse a SAG ``KNOW team.proposal`` message into a :class:`TreeProposal`.

    Falls back to JSON extraction if the SAG parse fails.
    """
    from sag.model import KnowledgeStatement
    from sag.parser import SAGMessageParser

    try:
        msg = SAGMessageParser.parse(raw)
    except Exception:
        return _parse_proposal_json(raw)

    for stmt in msg.statements:
        if isinstance(stmt, KnowledgeStatement) and "proposal" in stmt.topic:
            data = stmt.value
            if isinstance(data, dict):
                return _build_proposal_from_dict(data)
    return None


def build_tree_from_proposal(proposal: TreeProposal) -> TreeEngine:
    """Build a TreeEngine from a TreeProposal."""
    tree = TreeEngine()

    for agent in proposal.agents:
        if agent.parent_id is None:
            tree.add_root(
                agent.agent_id, agent.role,
                prompt=agent.prompt,
                topics=agent.topics,
            )
        else:
            tree.add_child(
                agent.parent_id, agent.agent_id, agent.role,
                prompt=agent.prompt,
                topics=agent.topics,
            )

    return tree
