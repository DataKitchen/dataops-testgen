import logging

from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from testgen import settings
from testgen.common import version_service
from testgen.common.auth import decode_jwt_token
from testgen.common.models import with_database_session

LOG = logging.getLogger("testgen")

SERVER_INSTRUCTIONS = """\
You are connected to a TestGen data quality testing server.

WORKFLOW:
1. ALWAYS start with get_data_inventory to understand the available projects, connections, and table groups.
2. Use the appropriate tools to explore profiling results, test definitions, and test results.
3. When asked about data quality, reference specific test results and profiling anomalies.
4. Provide actionable recommendations based on the data quality findings.

IMPORTANT:
- Use ISO 8601 format for dates (YYYY-MM-DD).
- UUIDs are used as identifiers for most entities.
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


@with_database_session
def ping() -> dict:
    """Check server connectivity and return version information."""
    version_data = version_service.get_version()
    return {
        "status": "ok",
        "edition": version_data.edition,
        "version": version_data.current,
    }


def run_mcp() -> None:
    """Start the MCP server with streamable HTTP transport."""
    from testgen.mcp import get_server_url
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
    mcp.tool()(ping)

    LOG.info("Starting MCP server on %s:%s (auth issuer: %s)", settings.MCP_HOST, settings.MCP_PORT, server_url)
    mcp.run(transport="streamable-http")
