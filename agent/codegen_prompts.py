"""Prompts for Phase 2 code generation.

Two main prompts:
- PLANNER_SYSTEM_PROMPT: examines Phase 1 facts, outputs a JSON file manifest
- FILE_GEN_SYSTEM_PROMPT: template for generating individual files

Plus helper functions that format the user messages with context.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Clarification prompt — root agent asks questions before codegen
# ---------------------------------------------------------------------------

CLARIFY_SYSTEM_PROMPT = """\
You are the root coordinator of a software agent team. Phase 1 analysis is \
complete and the user wants to generate code. Before code generation begins, \
review the accumulated design facts and identify any critical ambiguities or \
missing decisions that would block writing a complete, runnable project.

Output a JSON object:
{
  "needs_clarification": true/false,
  "questions": [
    "Question about an ambiguous requirement..."
  ],
  "summary": "Brief summary of what we know so far"
}

Rules:
- Ask 1-4 questions MAX — only ask about things that would genuinely block \
code generation (e.g. missing auth strategy, unclear data model, no framework chosen).
- If the facts are clear enough to generate code, set "needs_clarification": false \
and leave "questions" empty.
- Output ONLY valid JSON. No markdown fences, no explanation outside the JSON.
"""


# ---------------------------------------------------------------------------
# Planning prompt — produces the file manifest
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = """\
You are a senior software architect planning a code generation pass.

You will receive:
1. A task description
2. Design facts from an analysis phase (topic = value pairs)

Your job: produce a JSON file manifest for a COMPLETE, RUNNABLE project.

If you have tools available, use them first:
- list_directory(".") to see what already exists in the project
- read_file on any existing code to understand the current state
- search_files to find patterns or conventions

Then plan files that integrate with or extend what already exists.

Output this exact JSON structure:
{
  "tech_stack": {"language": "python", "framework": "fastapi", ...},
  "rationale": "Brief explanation of tech choices",
  "project_structure": "src/\\n  api/\\n    routes.py\\n  ...",
  "files": [
    {
      "path": "src/api/routes.py",
      "description": "REST API route definitions with CRUD endpoints",
      "language": "python",
      "relevant_facts": ["api.endpoints", "api.auth"],
      "depends_on": ["src/models.py"],
      "max_tokens": 4096
    }
  ]
}

Rules:
- Plan 10-30 files for a complete, runnable project.
- Include build/config files (requirements.txt, pyproject.toml, Dockerfile, etc.).
- Include a README.md with setup and run instructions.
- Order files so dependencies come first (models before routes, config before app).
- Each file's "depends_on" lists other files from this manifest that it imports/references.
- "relevant_facts" lists topic keys from the analysis facts that are relevant to this file.
- Set "max_tokens" higher (8192) for complex files, lower (2048) for configs.
- The "language" field should match the file extension (python, typescript, yaml, markdown, etc.).
- Output ONLY valid JSON. No markdown fences, no explanation outside the JSON.
"""


# ---------------------------------------------------------------------------
# Per-file generation prompt
# ---------------------------------------------------------------------------

FILE_GEN_SYSTEM_PROMPT = """\
You are a senior software engineer. Generate the file: {path}

Purpose: {description}
Language: {language}

Rules:
- Write ONE complete, functional, production-quality file.
- Include all necessary imports, type hints, error handling, and docstrings.
- Follow standard conventions for the language ({language}).
- Output ONLY the file content in a SINGLE fenced code block.
- No explanation before or after the code block.
- The code must be correct and runnable — not pseudocode or stubs.
"""

FILE_GEN_SYSTEM_PROMPT_WITH_TOOLS = """\
You are a senior software engineer. Generate the file: {path}

Purpose: {description}
Language: {language}

You have tools to explore the project. Before writing code:
1. Use read_file to examine any existing files in the project that are related
2. Use list_directory to check the output directory structure
3. Use search_files to find patterns, imports, or API conventions in existing code

After gathering context, write the complete file.

Rules:
- Write ONE complete, functional, production-quality file.
- Include all necessary imports, type hints, error handling, and docstrings.
- Follow standard conventions for the language ({language}).
- If you used tools, incorporate what you learned into the code.
- Output the file content in a fenced code block after your tool exploration.
- The code must be correct and runnable — not pseudocode or stubs.
"""


def build_file_gen_prompt(
    path: str, description: str, language: str, has_tools: bool = False,
) -> str:
    """Format the per-file system prompt with file-specific details."""
    template = FILE_GEN_SYSTEM_PROMPT_WITH_TOOLS if has_tools else FILE_GEN_SYSTEM_PROMPT
    return template.format(
        path=path,
        description=description,
        language=language,
    )


def build_file_gen_user_message(
    spec_path: str,
    spec_description: str,
    task: str,
    facts: dict[str, str],
    relevant_fact_keys: list[str],
    project_structure: str,
    generated_so_far: dict[str, str],
    depends_on: list[str],
) -> str:
    """Build the user message for a per-file generation call.

    Includes: task description, relevant facts, project structure,
    and content of dependency files already generated.
    """
    parts: list[str] = []

    parts.append(f"# Task\n{task}")

    # Relevant facts from Phase 1
    relevant = {}
    for key in relevant_fact_keys:
        if key in facts:
            relevant[key] = facts[key]
    if not relevant:
        # Fall back to all facts if no specific ones listed
        relevant = facts

    if relevant:
        parts.append("# Design Facts")
        for topic, value in relevant.items():
            val_str = str(value)
            if len(val_str) > 500:
                val_str = val_str[:497] + "..."
            parts.append(f"  {topic} = {val_str}")

    parts.append(f"# Project Structure\n{project_structure}")

    # Include content of dependency files (truncated)
    if depends_on:
        dep_parts: list[str] = []
        total_chars = 0
        max_chars = 32000  # ~8000 tokens cap for dependency context
        max_lines_per_file = 200

        for dep_path in depends_on:
            if dep_path in generated_so_far and total_chars < max_chars:
                content = generated_so_far[dep_path]
                lines = content.splitlines()
                if len(lines) > max_lines_per_file:
                    content = "\n".join(lines[:max_lines_per_file])
                    content += f"\n# ... ({len(lines) - max_lines_per_file} more lines)"
                dep_parts.append(f"## {dep_path}\n```\n{content}\n```")
                total_chars += len(content)

        if dep_parts:
            parts.append("# Already Generated Dependencies\n" + "\n\n".join(dep_parts))

    parts.append(
        f"# Instructions\n"
        f"Generate the complete file: {spec_path}\n"
        f"Purpose: {spec_description}\n"
        f"Output ONLY the code in a single fenced code block."
    )

    return "\n\n".join(parts)
