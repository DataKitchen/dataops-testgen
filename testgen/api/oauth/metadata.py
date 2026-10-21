"""RFC 8414 — OAuth 2.1 Authorization Server Metadata."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from testgen import settings
from testgen.common.models.oauth import OAuth2ClientAuthMethod

router = APIRouter(tags=["OAuth"])


@router.get("/.well-known/oauth-authorization-server", summary="Read the authorization server metadata")
def authorization_server_metadata():
    """The authorization server metadata defined by RFC 8414: the endpoints, grant types and client authentication
    methods an OAuth client discovers before it authorizes.
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
            "refresh_token",
        ],
        "token_endpoint_auth_methods_supported": [method.value for method in OAuth2ClientAuthMethod],
        "revocation_endpoint_auth_methods_supported": [method.value for method in OAuth2ClientAuthMethod],
        "code_challenge_methods_supported": ["S256"],
    })
