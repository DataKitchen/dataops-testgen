"""Export the TestGen MCP server as a Markdown reference page.

Usage:
    python deploy/build_mcp_docs.py [--output PATH]

Introspects the FastMCP instance built by ``build_mcp_server()`` and emits
a single Markdown page listing prompts, tools, and resources. Tools are
grouped by the ``_DOC_GROUP`` constant defined on each tool module — when
adding a new tool module, declare ``_DOC_GROUP = "..."`` so the new tools
land under the right heading automatically.

The page is an overview index: each entry is one bullet carrying the opening
sentence of its docstring. Detail beyond that sentence is omitted from the page
by design; it still reaches MCP clients, which receive the full description.

An entry contributed by a plugin is followed by whatever label that plugin's
``get_doc_label`` returns, so a page can list core and plugin entries together and
still say which is which. A plugin's entries are only present when it is installed
in the environment this script runs in.
"""

import argparse
import logging
import re
import sys
import textwrap
from pathlib import Path
from typing import Any

from testgen.mcp.server import build_mcp_server
from testgen.mcp.tools.common import DocGroup
from testgen.utils.plugins import discover

LOG = logging.getLogger("testgen")

_DEFAULT_OUTPUT = Path("docs/mcp/supported-tools.md")
_SENTENCE_END_RE = re.compile(r"\.(?=\s|$)")
# Periods closing an abbreviation rather than a sentence — the summary runs on past them.
_ABBREVIATIONS = ("e.g.", "i.e.", "etc.", "vs.", "approx.")

# Order in which tool groups appear on the page. Each entry is a ``DocGroup``
# member; tools whose module declares a ``_DOC_GROUP`` not in this list are
# appended after these in the order they are first seen.
_GROUP_ORDER: list[DocGroup] = [
    DocGroup.DISCOVER,
    DocGroup.INVESTIGATE,
    DocGroup.BROWSE_PROFILING,
    DocGroup.TRIGGER,
    DocGroup.SCORING,
    DocGroup.MANAGE,
]
_FALLBACK_GROUP = "Other tools"


def _short_description(docstring: str) -> str:
    """Return the opening sentence of a docstring — the entry's one-line summary.

    The search is bounded by the first paragraph, so a docstring whose opening sentence
    carries no closing period yields that paragraph rather than reaching into later ones.
    """
    if not docstring:
        return ""
    text = textwrap.dedent(docstring).strip()
    first_paragraph = text.split("\n\n", 1)[0]
    summary = " ".join(line.strip() for line in first_paragraph.splitlines())
    for sentence_end in _SENTENCE_END_RE.finditer(summary):
        sentence = summary[: sentence_end.end()]
        if not sentence.endswith(_ABBREVIATIONS):
            return sentence
    return summary


def _entry_name(item: Any) -> str:
    """Display name for a tool, resource, or prompt."""
    return str(getattr(item, "uri", None) or item.name)


def _plugin_doc_labels() -> dict[str, str]:
    """Map installed plugin package name to the label it wants on its entries."""
    labels = {}
    for plugin in discover():
        try:
            label = plugin.load().get_doc_label()
        except Exception:
            LOG.warning("Plugin %s failed to load; its entries go unlabelled", plugin.package)
            continue
        if label:
            labels[plugin.package] = label
    return labels


def _entry_label(item: Any, plugin_labels: dict[str, str]) -> str:
    """Label for the entry's originating package, empty for a core entry.

    Resources are addressed by URI and expose no function, so they resolve to no package.
    """
    module = getattr(getattr(item, "fn", None), "__module__", "")
    return plugin_labels.get(module.split(".", 1)[0], "") if module else ""


def _render_entry(item: Any, plugin_labels: dict[str, str]) -> str:
    description = _short_description(item.description or "")
    label = _entry_label(item, plugin_labels)
    return f"- **`{_entry_name(item)}`** — {description}{f' {label}' if label else ''}"


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
    plugin_labels = _plugin_doc_labels()
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
    parts.extend(_render_entry(prompt, plugin_labels) for prompt in prompts)
    parts.append("")

    parts.extend(["## Tools", "", "Tools are operations the assistant calls during a conversation, picked based on what you ask.", ""])
    for heading, bucket in grouped_tools:
        parts.append(f"### {heading}")
        parts.append("")
        parts.extend(_render_entry(tool, plugin_labels) for tool in bucket)
        parts.append("")

    parts.extend(
        [
            "## Resources",
            "",
            "Resources are static reference documents that AI clients can fetch by URI.",
            "",
        ]
    )
    parts.extend(_render_entry(resource, plugin_labels) for resource in resources)

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
