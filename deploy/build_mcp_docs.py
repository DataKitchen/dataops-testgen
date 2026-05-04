"""Export the TestGen MCP server as a Markdown reference page.

Usage:
    python deploy/build_mcp_docs.py [--output PATH]

Introspects the FastMCP instance built by ``build_mcp_server()`` and emits
a single Markdown page listing prompts, tools, and resources. Tools are
grouped by the ``_DOC_GROUP`` constant defined on each tool module — when
adding a new tool module, declare ``_DOC_GROUP = "..."`` so the new tools
land under the right heading automatically.
"""

import argparse
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

from testgen.mcp.server import build_mcp_server
from testgen.mcp.tools.common import DocGroup

_DEFAULT_OUTPUT = Path("docs/mcp/supported-tools.md")
_ARGS_HEADER_RE = re.compile(r"^\s*Args:\s*$", re.MULTILINE)

# Order in which tool groups appear on the page. Each entry is a ``DocGroup``
# member; tools whose module declares a ``_DOC_GROUP`` not in this list are
# appended after these in the order they are first seen.
_GROUP_ORDER: list[DocGroup] = [
    DocGroup.DISCOVER,
    DocGroup.INVESTIGATE,
    DocGroup.BROWSE_PROFILING,
    DocGroup.TRIGGER,
]
_FALLBACK_GROUP = "Other tools"


def _short_description(docstring: str) -> str:
    """Return the first prose paragraph of a docstring, stripped of Args/Returns sections."""
    if not docstring:
        return ""
    text = textwrap.dedent(docstring).strip()
    match = _ARGS_HEADER_RE.search(text)
    if match:
        text = text[: match.start()].rstrip()
    first_paragraph = text.split("\n\n", 1)[0]
    return " ".join(line.strip() for line in first_paragraph.splitlines())


def _entry_name(item: Any) -> str:
    """Display name for a tool, resource, or prompt."""
    return str(getattr(item, "uri", None) or item.name)


def _render_entry(item: Any) -> str:
    description = _short_description(item.description or "")
    return f"- **`{_entry_name(item)}`** — {description}"


def _group_for_tool(tool: Any) -> str:
    """Resolve a tool's display group via its module's ``_DOC_GROUP`` constant."""
    module = sys.modules.get(tool.fn.__module__)
    group = getattr(module, "_DOC_GROUP", None)
    return str(group) if group is not None else _FALLBACK_GROUP


def _group_tools(tools: list[Any]) -> list[tuple[str, list[Any]]]:
    """Bucket tools by their module's ``_DOC_GROUP``, ordered by ``_GROUP_ORDER``."""
    buckets: dict[str, list[Any]] = {}
    for tool in tools:
        buckets.setdefault(_group_for_tool(tool), []).append(tool)

    ordered: list[tuple[str, list[Any]]] = []
    for group in _GROUP_ORDER:
        title = str(group)
        if title in buckets:
            ordered.append((title, sorted(buckets.pop(title), key=lambda t: t.name)))
    for title, bucket in buckets.items():
        ordered.append((title, sorted(bucket, key=lambda t: t.name)))
    return ordered


def _build_markdown(mcp: Any) -> str:
    tools = mcp._tool_manager.list_tools()
    resources = sorted(mcp._resource_manager.list_resources(), key=lambda r: str(r.uri))
    prompts = sorted(mcp._prompt_manager.list_prompts(), key=lambda p: p.name)
    grouped_tools = _group_tools(list(tools))

    parts: list[str] = [
        "# Supported Tools",
        "",
        "The TestGen MCP server exposes the prompts, tools, and resources listed below.",
        "",
        "For setup instructions, see [Set up the MCP Server](setup.md).",
        "For example questions to ask an assistant, see [MCP Server](index.md#what-you-can-ask).",
        "",
        "## Prompts",
        "",
        (
            "Prompts are pre-built workflows you can invoke directly through your AI client — typically "
            "as a slash command (for example, `/testgen:table_health` in Claude Code) or "
            "from a quick-action menu. They orchestrate several tool calls behind the scenes for common "
            "investigations. Exact UX varies by client."
        ),
        "",
    ]
    parts.extend(_render_entry(prompt) for prompt in prompts)
    parts.append("")

    parts.extend(["## Tools", "", "Tools are operations the assistant calls during a conversation, picked based on what you ask.", ""])
    for heading, bucket in grouped_tools:
        parts.append(f"### {heading}")
        parts.append("")
        parts.extend(_render_entry(tool) for tool in bucket)
        parts.append("")

    parts.extend(
        [
            "## Resources",
            "",
            "Resources are static reference documents that AI clients can fetch by URI.",
            "",
        ]
    )
    parts.extend(_render_entry(resource) for resource in resources)

    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the TestGen MCP server as a Markdown reference.")
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output Markdown file path (default: {_DEFAULT_OUTPUT}, relative to cwd)",
    )
    args = parser.parse_args()

    mcp = build_mcp_server(api_base_url="https://testgen.example.com")
    markdown = _build_markdown(mcp)

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = "---\nsearch:\n  boost: 0.5\n---\n"
    output.write_text(frontmatter + markdown, encoding="utf-8")
    print(f"Exported MCP supported tools -> {output}")


if __name__ == "__main__":
    main()
