"""Tests for testgen.api.oauth.metadata — RFC 8414 discovery endpoint."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from testgen.api.oauth.metadata import router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_metadata_endpoint_returns_200():
    client = _make_client()
    resp = client.get("/.well-known/oauth-authorization-server")
    assert resp.status_code == 200


def test_metadata_includes_all_endpoints():
    client = _make_client()
    data = client.get("/.well-known/oauth-authorization-server").json()

    assert data["authorization_endpoint"].endswith("/oauth/authorize")
    assert data["token_endpoint"].endswith("/oauth/token")
    assert data["revocation_endpoint"].endswith("/oauth/revoke")
    assert data["registration_endpoint"].endswith("/oauth/register")
    assert data["end_session_endpoint"].endswith("/oauth/logout")


def test_metadata_includes_issuer():
    client = _make_client()
    data = client.get("/.well-known/oauth-authorization-server").json()

    assert "issuer" in data
    assert data["issuer"].startswith("http")


def test_metadata_lists_supported_grant_types():
    client = _make_client()
    data = client.get("/.well-known/oauth-authorization-server").json()

    assert "authorization_code" in data["grant_types_supported"]
    assert "client_credentials" in data["grant_types_supported"]
    assert "refresh_token" in data["grant_types_supported"]
    assert data["code_challenge_methods_supported"] == ["S256"]


def test_metadata_lists_auth_methods():
    client = _make_client()
    data = client.get("/.well-known/oauth-authorization-server").json()

    assert "client_secret_basic" in data["token_endpoint_auth_methods_supported"]
    assert "none" in data["token_endpoint_auth_methods_supported"]
