"""Tests that every registered MCP tool documents its parameters in the JSON Schema.

The MCP SDK never merges a docstring ``Args:`` block into the generated schema — the prose
description and the schema are built from separate sources and never meet. Parameter docs
therefore have to be declared as ``Annotated[T, Field(description=...)]`` to reach clients.
These tests fail a tool that regresses to documenting its parameters in prose only.

The server is built once for the whole module, so whichever plugins are installed in the
running environment have their tools checked alongside the core ones.
"""

import pytest

from testgen.mcp.server import build_mcp_server

# Clients diverge on where they truncate. Prose descriptions are capped by several clients
# (OpenAI hard-rejects over 1024); schema node text is capped by others (VS Code at 1024).
# Staying under the smaller of the two everywhere keeps every client whole.
MAX_DESCRIPTION_LEN = 1024

# A first line has to stand on its own in catalogs that shorten tool descriptions for
# selection, so it carries the whole summary within this budget.
MAX_FIRST_LINE_LEN = 80


@pytest.fixture(scope="module")
def mcp_server():
    """Build the server once. ``build_mcp_server`` reparents the ``mcp`` and ``uvicorn``
    loggers onto testgen's and clears the root handlers, so extra calls repeat that
    process-wide mutation for nothing.
    """
    return build_mcp_server(api_base_url="https://testgen.example.com")


@pytest.fixture(scope="module")
def tools(mcp_server):
    return mcp_server._tool_manager.list_tools()


@pytest.fixture(scope="module")
def prompts(mcp_server):
    return mcp_server._prompt_manager.list_prompts()


def test_tools_are_registered(tools):
    """Guard the fixture itself: an empty registry would make every other test vacuous."""
    assert len(tools) > 50


def test_every_parameter_has_a_schema_description(tools):
    undocumented = [
        f"{tool.name}.{name}"
        for tool in tools
        for name, schema in tool.parameters.get("properties", {}).items()
        if not schema.get("description")
    ]
    assert not undocumented, (
        "Parameters documented nowhere the client can read them. Declare each as "
        f"Annotated[T, Field(description=...)]: {undocumented}"
    )


def test_no_tool_documents_parameters_in_prose(tools):
    """An ``Args:`` block in the description means the docs never reached the schema."""
    offenders = [tool.name for tool in tools if "Args:" in (tool.description or "")]
    assert not offenders, offenders


def test_descriptions_stay_within_the_client_budget(tools):
    too_long = [
        (tool.name, len(tool.description or ""))
        for tool in tools
        if len(tool.description or "") > MAX_DESCRIPTION_LEN
    ]
    assert not too_long, f"Descriptions over {MAX_DESCRIPTION_LEN} chars are truncated by some clients: {too_long}"


def test_parameter_descriptions_stay_within_the_client_budget(tools):
    too_long = [
        (f"{tool.name}.{name}", len(schema["description"]))
        for tool in tools
        for name, schema in tool.parameters.get("properties", {}).items()
        if len(schema.get("description") or "") > MAX_DESCRIPTION_LEN
    ]
    assert not too_long, f"Schema descriptions over {MAX_DESCRIPTION_LEN} chars are truncated per node: {too_long}"


def test_first_lines_are_self_sufficient(tools):
    too_long = []
    for tool in tools:
        description = (tool.description or "").strip()
        assert description, f"{tool.name} has no description"
        first_line = description.splitlines()[0]
        if len(first_line) > MAX_FIRST_LINE_LEN:
            too_long.append((tool.name, len(first_line)))
    assert not too_long, f"First lines over {MAX_FIRST_LINE_LEN} chars: {too_long}"


def test_every_prompt_argument_has_a_description(prompts):
    undocumented = [
        f"{prompt.name}.{argument.name}"
        for prompt in prompts
        for argument in prompt.arguments or []
        if not argument.description
    ]
    assert not undocumented, undocumented


def test_prompt_descriptions_are_self_sufficient(prompts):
    """Prompts appear in the same client pickers as tools, under the same budgets."""
    offenders = []
    for prompt in prompts:
        description = (prompt.description or "").strip()
        assert description, f"{prompt.name} has no description"
        if len(description) > MAX_DESCRIPTION_LEN:
            offenders.append((prompt.name, "description", len(description)))
        first_line = description.splitlines()[0]
        if len(first_line) > MAX_FIRST_LINE_LEN:
            offenders.append((prompt.name, "first line", len(first_line)))
    assert not offenders, offenders
