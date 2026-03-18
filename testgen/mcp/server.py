import logging

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette

from testgen.common.auth import decode_jwt_token
from testgen.mcp.permissions import set_mcp_token, set_mcp_username

LOG = logging.getLogger("testgen")

SERVER_INSTRUCTIONS = """\
TestGen is a data quality platform that profiles databases, generates tests, and monitors tables.

DATA MODEL

Projects contain Connections (to target databases) and Table Groups (sets of tables to profile and test together).
Table Groups contains Test Suites — collections of Test Definitions with configured thresholds.
Test Runs execute a Test Suite and produce Test Results (one per Test Definition).
Profiling Runs scan a Table Group and produce column-level statistics and detects data hygiene issues.
Monitors track table health over time: freshness, volume, schema changes, and custom metrics.

NAVIGATION

Tools return entity IDs that feed into other tools. Start with get_data_inventory for broad discovery, then drill
into specific entities.

Test types have specific, non-obvious meanings (e.g., Alpha_Trunc). Do not guess what a test checks.
ALWAYS look them up using either the `testgen://test-types` resource or the `get_test_type()` tool.

CONVENTIONS
- Identifiers are UUIDs passed as strings.
- Dates are ISO 8601 format.
"""


class JWTTokenVerifier:
    """Verify JWT Bearer tokens for MCP server authentication."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = decode_jwt_token(token)
            set_mcp_username(payload["username"])
            set_mcp_token(token)
            return AccessToken(
                token=token,
                client_id=payload["username"],
                scopes=[],
                expires_at=int(payload["exp"]),
            )
        except (ValueError, KeyError):
            return None


def _configure_mcp_logging() -> None:
    """Route FastMCP and uvicorn logs through the testgen logger."""
    testgen_logger = logging.getLogger("testgen")

    # FastMCP.__init__ calls basicConfig() which adds a RichHandler to the root logger — remove it
    logging.getLogger().handlers.clear()

    # Reparent top-level third-party loggers so they (and their children) propagate through testgen's handler
    for name in ("mcp", "uvicorn"):
        logging.getLogger(name).parent = testgen_logger


def build_mcp_app(
    api_base_url: str, server_url: str | None = None,
) -> tuple[Starlette, StreamableHTTPSessionManager]:
    """Create the MCP Starlette app with tools, resources, and prompts registered.

    Returns the Starlette app and its session manager. The caller must run
    ``session_manager.run()`` as an async context manager (e.g. in the host
    app's lifespan) to initialize the task group before requests arrive.

    Args:
        api_base_url: OAuth issuer URL (the API server).
        server_url: MCP resource server URL. Defaults to ``{api_base_url}/mcp``.
    """
    from testgen.mcp.prompts.workflows import compare_runs, health_check, investigate_failures, table_health
    from testgen.mcp.tools.discovery import get_data_inventory, list_projects, list_tables, list_test_suites
    from testgen.mcp.tools.reference import get_test_type, glossary_resource, test_types_resource
    from testgen.mcp.tools.test_results import get_failure_summary, get_test_result_history, get_test_results
    from testgen.mcp.tools.test_runs import get_recent_test_runs

    if server_url is None:
        server_url = f"{api_base_url}/mcp"

    mcp = FastMCP(
        "TestGen",
        instructions=SERVER_INSTRUCTIONS,
        auth=AuthSettings(
            issuer_url=api_base_url,
            resource_server_url=server_url,
        ),
        token_verifier=JWTTokenVerifier(),
    )
    _configure_mcp_logging()

    # Tools (9)
    mcp.tool()(get_data_inventory)
    mcp.tool()(list_projects)
    mcp.tool()(list_tables)
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

    app = mcp.streamable_http_app()
    return app, mcp.session_manager
