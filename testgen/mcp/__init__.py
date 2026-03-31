from testgen import settings


def get_server_url() -> str:
    """Derive the externally-reachable MCP server URL."""
    return f"{settings.BASE_URL}/mcp"
