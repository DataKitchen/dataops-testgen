import logging

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from testgen import settings
from testgen.common.auth import decode_jwt_token
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")

SERVER_INSTRUCTIONS = """\
You are connected to a TestGen data quality testing server.

## Available Tools (8)

- **get_data_inventory()** — Complete overview of projects, connections, table groups, test suites, and latest run stats. START HERE.
- **list_projects()** — List all project codes and names.
- **list_test_suites(project_code)** — List test suites with run stats for a project.
- **get_recent_test_runs(project_code, test_suite?, limit?)** — Get recent test runs with pass/fail counts (default 5).
- **get_test_results(test_run_id, status?, table_name?, test_type?, limit?)** — Get individual test results with filters.
- **get_test_result_history(test_definition_id, limit?)** — Historical results for a test definition across runs (measure, threshold, status over time).
- **get_failure_summary(test_run_id, group_by?)** — Failures grouped by test_type, table, or column.
- **get_test_type(test_type)** — Detailed info about a test type (what it checks, thresholds, DQ dimension).

## Resources (2)

- **testgen://test-types** — Reference table of all active test types.
- **testgen://glossary** — Entity hierarchy, result statuses, DQ dimensions, test scopes.

## Workflow

1. ALWAYS start with `get_data_inventory` to understand the landscape.
2. Drill into specific runs with `get_recent_test_runs` and `get_test_results`.
3. DO NOT assume what a test type checks. Look at `testgen://test-types`
4. Use `get_failure_summary` to understand failure patterns, then `get_test_type` for each category.
5. Use `get_test_result_history` to see how a specific test's measure and status changed over time.
6. Reference `testgen://glossary` for definitions of statuses, dimensions, and scopes.

## Conventions

- UUIDs are used as identifiers — pass them as strings.
- Dates are in ISO 8601 format.
- Test results with disposition 'Dismissed' or 'Inactive' are excluded from counts by default.
"""


class JWTTokenVerifier:
    """Verify JWT Bearer tokens for MCP server authentication."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = decode_jwt_token(token)
            return AccessToken(
                token=token,
                client_id=payload["username"],
                scopes=[],
                expires_at=int(payload["exp_date"]),
            )
        except (ValueError, KeyError):
            return None


def run_mcp() -> None:
    """Start the MCP server with streamable HTTP transport."""
    from testgen.mcp import get_server_url
    from testgen.mcp.prompts.workflows import compare_runs, health_check, investigate_failures, table_health
    from testgen.mcp.tools.discovery import get_data_inventory, list_projects, list_test_suites
    from testgen.mcp.tools.reference import get_test_type, glossary_resource, test_types_resource
    from testgen.mcp.tools.test_results import get_failure_summary, get_test_result_history, get_test_results
    from testgen.mcp.tools.test_runs import get_recent_test_runs
    from testgen.utils.plugins import discover

    for plugin in discover():
        plugin.load()

    server_url = with_database_session(get_server_url)()

    mcp = FastMCP(
        "TestGen",
        host=settings.MCP_HOST,
        port=settings.MCP_PORT,
        instructions=SERVER_INSTRUCTIONS,
        auth=AuthSettings(
            issuer_url=server_url,
            resource_server_url=server_url,
        ),
        token_verifier=JWTTokenVerifier(),
    )

    # Tools (8)
    mcp.tool()(get_data_inventory)
    mcp.tool()(list_projects)
    mcp.tool()(list_test_suites)
    mcp.tool()(get_recent_test_runs)
    mcp.tool()(get_test_results)
    mcp.tool()(get_test_result_history)
    mcp.tool()(get_failure_summary)
    mcp.tool()(get_test_type)

    # Resources (2)
    mcp.resource("testgen://test-types")(test_types_resource)
    mcp.resource("testgen://glossary")(glossary_resource)

    # Prompts (4)
    mcp.prompt()(health_check)
    mcp.prompt()(investigate_failures)
    mcp.prompt()(table_health)
    mcp.prompt()(compare_runs)

    LOG.info("Starting MCP server on %s:%s (auth issuer: %s)", settings.MCP_HOST, settings.MCP_PORT, server_url)
    mcp.run(transport="streamable-http")
