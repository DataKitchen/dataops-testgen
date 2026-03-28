from testgen import settings
from testgen.common.models.settings import PersistedSetting


def get_server_url() -> str:
    """Derive the externally-reachable MCP server URL from the persisted BASE_URL."""
    base_url = PersistedSetting.get("BASE_URL", "")
    if base_url:
        scheme, _, host_port = base_url.partition("://")
        host = host_port.split(":")[0]
        return f"{scheme}://{host}:{settings.MCP_PORT}"
    return f"http://localhost:{settings.MCP_PORT}"
