"""Tests for testgen.server — combined API + MCP application."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_version():
    return MagicMock(current="1.0.0", edition="Test")


@pytest.fixture()
def _server_deps():
    """Patch database and auth dependencies so create_app() works without a live DB."""

    def fake_with_db_session(fn):
        def wrapper(*args, **kwargs):
            if fn.__name__ == "get_version":
                return _mock_version()
            return fn(*args, **kwargs)

        return wrapper

    with (
        patch("testgen.server.with_database_session", side_effect=fake_with_db_session),
        patch("testgen.server.create_authorization_server", return_value=MagicMock()),
        patch("testgen.server.init_routes"),
    ):
        yield


def test_metadata_on_combined_app(_server_deps):
    """OAuth metadata endpoint works on the combined server app."""
    with patch("testgen.settings.MCP_ENABLED", False), patch("testgen.settings.IS_DEBUG", False):
        from testgen.server import create_app

        app = create_app()

    client = TestClient(app)
    resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200

    data = resp.json()
    assert data["authorization_endpoint"].endswith("/oauth/authorize")
    assert data["token_endpoint"].endswith("/oauth/token")


def test_api_routes_when_mcp_disabled(_server_deps):
    """API routes are registered when MCP is disabled."""
    with patch("testgen.settings.MCP_ENABLED", False), patch("testgen.settings.IS_DEBUG", False):
        from testgen.server import create_app

        app = create_app()

    route_paths = {getattr(r, "path", None) for r in app.routes}
    assert "/api/v1/health" in route_paths
    assert "/api/v1/jobs/{job_id}" in route_paths
    assert "/.well-known/oauth-authorization-server" in route_paths


def test_mcp_mounted_when_enabled(_server_deps):
    """MCP sub-app is mounted at '' when MCP_ENABLED is True."""
    mock_mcp_app = MagicMock()
    mock_session_mgr = MagicMock()

    with (
        patch("testgen.settings.MCP_ENABLED", True),
        patch("testgen.settings.IS_DEBUG", False),
        patch("testgen.settings.BASE_URL", "http://localhost:8530"),
        patch("testgen.mcp.server.build_mcp_app", return_value=(mock_mcp_app, mock_session_mgr)) as mock_build,
    ):
        from testgen.server import create_app

        app = create_app()

    mock_build.assert_called_once_with("http://localhost:8530")

    mount_found = any(hasattr(r, "app") and r.path == "" for r in app.routes)
    assert mount_found


def test_no_mcp_mount_when_disabled(_server_deps):
    """No MCP sub-app is mounted when MCP_ENABLED is False."""
    with patch("testgen.settings.MCP_ENABLED", False), patch("testgen.settings.IS_DEBUG", False):
        from testgen.server import create_app

        app = create_app()

    mount_found = any(hasattr(r, "app") and r.path == "" for r in app.routes)
    assert not mount_found
