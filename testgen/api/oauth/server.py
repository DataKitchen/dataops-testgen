"""OAuth 2.1 Authorization Server built on authlib.

Grant types:
- Authorization Code + PKCE (for MCP clients)
- Refresh Token (for token renewal)

All DB operations use get_current_session() for thread-local session access.
"""

import secrets
import time
from typing import ClassVar

from authlib.oauth2.rfc6749 import AuthorizationServer, JsonRequest, OAuth2Request, grants
from authlib.oauth2.rfc6749.authenticate_client import authenticate_none
from authlib.oauth2.rfc6749.errors import InvalidRequestError
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7636 import CodeChallenge
from sqlalchemy import select

from testgen import settings
from testgen.common.auth import create_jwt_token
from testgen.common.models import get_current_session
from testgen.common.models.oauth import OAuth2AuthorizationCode, OAuth2Client, OAuth2ClientAuthMethod, OAuth2Token
from testgen.common.models.user import User

CLIENT_AUTH_METHODS = [method.value for method in OAuth2ClientAuthMethod]


class S256CodeChallenge(CodeChallenge):
    DEFAULT_CODE_CHALLENGE_METHOD = "S256"
    SUPPORTED_CODE_CHALLENGE_METHOD: ClassVar[list[str]] = ["S256"]

    def validate_code_challenge(self, grant, redirect_uri):
        # Authlib makes PKCE optional for confidential clients and lets an empty method through,
        # which stores a method the token endpoint cannot verify.
        data = grant.request.payload.data
        if not data.get("code_challenge"):
            raise InvalidRequestError("Missing 'code_challenge'")
        method = data.get("code_challenge_method")
        if method is not None and method not in self.SUPPORTED_CODE_CHALLENGE_METHOD:
            raise InvalidRequestError("Unsupported 'code_challenge_method'")
        super().validate_code_challenge(grant, redirect_uri)


class AuthorizationCodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[list[str]] = CLIENT_AUTH_METHODS

    def save_authorization_code(self, code, request):
        auth_code = OAuth2AuthorizationCode(
            code=code,
            client_id=request.client.client_id,
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            user_id=request.user.id,
            code_challenge=request.data.get("code_challenge"),
            code_challenge_method=request.data.get("code_challenge_method"),
        )
        session = get_current_session()
        session.add(auth_code)
        return auth_code

    def query_authorization_code(self, code, client):
        session = get_current_session()
        item = session.scalars(
            select(OAuth2AuthorizationCode).where(
                OAuth2AuthorizationCode.code == code,
                OAuth2AuthorizationCode.client_id == client.client_id,
            )
        ).first()
        if item and not item.is_expired():
            return item
        return None

    def delete_authorization_code(self, authorization_code):
        session = get_current_session()
        session.delete(authorization_code)

    def authenticate_user(self, authorization_code):
        session = get_current_session()
        return session.scalars(select(User).where(User.id == authorization_code.user_id)).first()


class RefreshTokenGrant(grants.RefreshTokenGrant):
    """Refresh token grant. Public clients get a rotated refresh token on every refresh;
    confidential clients keep reusing theirs until it expires.
    """

    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[list[str]] = CLIENT_AUTH_METHODS

    def _rotates_refresh_token(self) -> bool:
        return self.request.client.token_endpoint_auth_method == OAuth2ClientAuthMethod.NONE

    def issue_token(self, user, refresh_token):
        scope = self.request.payload.scope or refresh_token.get_scope()
        return self.generate_token(
            user=user,
            scope=scope,
            include_refresh_token=self._rotates_refresh_token(),
        )

    def authenticate_refresh_token(self, refresh_token):
        session = get_current_session()
        item = session.scalars(
            select(OAuth2Token).where(OAuth2Token.refresh_token == refresh_token)
        ).first()
        if item and item.is_refresh_token_active():
            return item
        return None

    def authenticate_user(self, credential):
        session = get_current_session()
        return session.scalars(select(User).where(User.id == credential.user_id)).first()

    def revoke_old_credential(self, credential):
        now = int(time.time())
        credential.access_token_revoked_at = now
        if self._rotates_refresh_token():
            credential.refresh_token_revoked_at = now


class TestGenRevocationEndpoint(RevocationEndpoint):
    CLIENT_AUTH_METHODS: ClassVar[list[str]] = CLIENT_AUTH_METHODS

    def query_token(self, token_string, token_type_hint):
        session = get_current_session()
        if token_type_hint == "access_token":  # noqa: S105
            return session.scalars(select(OAuth2Token).where(OAuth2Token.access_token == token_string)).first()
        if token_type_hint == "refresh_token":  # noqa: S105
            return session.scalars(select(OAuth2Token).where(OAuth2Token.refresh_token == token_string)).first()
        return (
            session.scalars(select(OAuth2Token).where(OAuth2Token.access_token == token_string)).first()
            or session.scalars(select(OAuth2Token).where(OAuth2Token.refresh_token == token_string)).first()
        )

    def revoke_token(self, token, request):
        now = int(time.time())
        hint = request.form.get("token_type_hint")
        if hint == "access_token":
            token.access_token_revoked_at = now
        else:
            token.access_token_revoked_at = now
            token.refresh_token_revoked_at = now


class TestGenAuthorizationServer(AuthorizationServer):
    """OAuth 2.1 Authorization Server using TestGen's DB session management."""

    def query_client(self, client_id):
        session = get_current_session()
        return session.scalars(select(OAuth2Client).where(OAuth2Client.client_id == client_id)).first()

    def save_token(self, token, request):
        user_id = request.user.id if request.user else None
        item = OAuth2Token(
            client_id=request.client.client_id,
            user_id=user_id,
            **token,
        )
        if token.get("refresh_token") and isinstance(request.refresh_token, OAuth2Token):
            item.refresh_token_chain_issued_at = request.refresh_token.refresh_chain_issued_at
        session = get_current_session()
        session.add(item)

    def create_oauth2_request(self, request):
        return request if isinstance(request, OAuth2Request) else None

    def create_json_request(self, request):
        return request if isinstance(request, JsonRequest) else None

    def handle_response(self, status_code, payload, headers):
        return status_code, payload, headers

    def send_signal(self, name, *args, **kwargs):
        pass


def _authenticate_none(query_client, request):
    """Authenticate a public client by client_id, unless the request also carries HTTP Basic credentials.

    A client presenting HTTP Basic credentials is authenticating with a secret, and a failed secret
    must not fall through to client_id-only authentication.
    """
    if request.headers.get("Authorization", "").lower().startswith("basic "):
        return None
    return authenticate_none(query_client, request)


def _generate_bearer_token(
    grant_type,  # noqa: ARG001
    client,
    user=None,
    scope=None,
    expires_in=None,
    include_refresh_token=True,
):
    """Generate a Bearer token with a JWT access_token."""
    if user is None:
        raise RuntimeError(f"Token generation requires a user (client_id={client.client_id})")
    access_token = create_jwt_token(user.username, expiry_seconds=settings.ACCESS_TOKEN_EXPIRES_IN)
    token = {
        "token_type": "Bearer",
        "access_token": access_token,
        "expires_in": expires_in or settings.ACCESS_TOKEN_EXPIRES_IN,
    }
    if include_refresh_token:
        token["refresh_token"] = secrets.token_urlsafe(48)
    if scope:
        token["scope"] = scope
    return token


def create_authorization_server() -> TestGenAuthorizationServer:
    """Create and configure the authorization server with all grant types."""
    server = TestGenAuthorizationServer()
    server.register_client_auth_method(OAuth2ClientAuthMethod.NONE, _authenticate_none)
    server.register_grant(AuthorizationCodeGrant, [S256CodeChallenge(required=True)])
    server.register_grant(RefreshTokenGrant)
    server.register_endpoint(TestGenRevocationEndpoint)
    server.register_token_generator("default", _generate_bearer_token)
    return server
