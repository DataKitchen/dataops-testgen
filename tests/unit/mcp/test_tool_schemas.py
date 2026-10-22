"""Tests that every registered MCP tool documents its parameters in the JSON Schema.

The MCP SDK never merges a docstring ``Args:`` block into the generated schema — the prose
description and the schema are built from separate sources and never meet. Parameter docs
therefore have to be declared as ``Annotated[T, Field(description=...)]`` to reach clients.
These tests fail a tool that regresses to documenting its parameters in prose only.

The server is built once for the whole module, so whichever plugins are installed in the
running environment have their tools checked alongside the core ones.
"""

import asyncio
from unittest.mock import patch
from uuid import uuid4

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

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


def test_every_tool_schema_refuses_undeclared_arguments(tools):
    permissive = [tool.name for tool in tools if tool.parameters.get("additionalProperties") is not False]
    assert not permissive, f"Input schemas that do not declare additionalProperties: false: {permissive}"


def test_every_tool_rejects_an_undeclared_argument(tools):
    accepting = []
    for tool in tools:
        try:
            tool.fn_metadata.arg_model.model_validate({"not_an_argument": "x"})
        except ValidationError as error:
            if any(e["type"] == "extra_forbidden" and e["loc"] == ("not_an_argument",) for e in error.errors()):
                continue
        accepting.append(tool.name)
    assert not accepting, f"Tools that drop an undeclared argument without an error: {accepting}"


def test_a_misplaced_argument_fails_the_call_and_names_it(mcp_server):
    # A field that belongs inside ``fields``, passed at the top level, would otherwise be dropped and create a test
    # with no column.
    with patch("testgen.mcp.tools.test_definitions.TestDefinition") as test_definition_mock:
        with pytest.raises(ToolError, match="column_name"):
            asyncio.run(mcp_server.call_tool(
                "create_test",
                {
                    "test_suite_id": str(uuid4()),
                    "test_type": "Alpha Truncation",
                    "table_name": "customers",
                    "column_name": "email",
                },
            ))
    test_definition_mock.assert_not_called()


def _argument_error(mcp_server, tool_name: str, arguments: dict) -> str:
    with pytest.raises(ToolError) as raised:
        asyncio.run(mcp_server.call_tool(tool_name, arguments))
    return str(raised.value)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        (
            "get_project",
            {"project_code": "DEFAULT", "bogus": 1},
            "- `bogus`: not an argument of `get_project`. Its arguments are `project_code`.",
        ),
        ("get_test_suite", {}, "- `test_suite_id`: required."),
        ("get_test_suite", {"test_suite_id": 123}, "- `test_suite_id`: Input should be a valid string."),
        (
            "create_table_group",
            {
                "connection_id": 1,
                "table_group_name": "files",
                "file_declarations": [{"name": "orders", "uri": "orders.xml", "format": "xml"}],
            },
            "- `file_declarations[0].format`: Input should be 'csv', 'parquet' or 'json'.",
        ),
    ],
)
def test_an_argument_error_is_described_in_plain_words(mcp_server, tool_name, arguments, expected):
    message = _argument_error(mcp_server, tool_name, arguments)

    assert message.startswith(f"Invalid arguments for `{tool_name}`.")
    assert expected in message.splitlines()
    assert "pydantic" not in message.lower()
    assert "validation error" not in message


def test_every_argument_error_of_a_call_is_listed(mcp_server):
    message = _argument_error(mcp_server, "get_test_suite", {"test_suite_id": 123, "bogus": 1, "other": 2})

    assert [line for line in message.splitlines() if line.startswith("- ")] == [
        "- `test_suite_id`: Input should be a valid string.",
        "- `bogus`: not an argument of `get_test_suite`. Its arguments are `test_suite_id`.",
        "- `other`: not an argument of `get_test_suite`. Its arguments are `test_suite_id`.",
    ]


def _parse_arguments(tools, tool_name: str, arguments: dict):
    tool = next(tool for tool in tools if tool.name == tool_name)
    return tool.fn_metadata.arg_model.model_validate(arguments)


def test_the_failure_trend_bucket_is_read_in_any_case(tools):
    assert _parse_arguments(tools, "get_failure_trend", {"bucket": "Week"}).bucket == "week"


def test_a_file_declaration_format_is_read_in_any_case(tools):
    parsed = _parse_arguments(tools, "create_table_group", {
        "connection_id": 1,
        "table_group_name": "files",
        "file_declarations": [{"name": "orders", "uri": "orders/*.parquet", "format": " Parquet"}],
    })

    assert parsed.file_declarations[0].format == "parquet"


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
