"""RFC 8414 — OAuth 2.0 Authorization Server Metadata."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from testgen import settings

router = APIRouter()


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    """Return OAuth 2.0 Authorization Server Metadata per RFC 8414.

    MCP clients use this for server discovery.
    """
    base_url = settings.BASE_URL.rstrip("/")

    return JSONResponse(content={
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "revocation_endpoint": f"{base_url}/oauth/revoke",
        "registration_endpoint": f"{base_url}/oauth/register",
        "end_session_endpoint": f"{base_url}/oauth/logout",
        "response_types_supported": ["code"],
        "grant_types_supported": [
            "authorization_code",
            "client_credentials",
            "refresh_token",
        ],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
            "none",
        ],
        "code_challenge_methods_supported": ["S256"],
    })
