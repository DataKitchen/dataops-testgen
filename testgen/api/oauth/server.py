"""OAuth 2.1 Authorization Server built on authlib.

Grant types:
- Authorization Code + PKCE (for MCP clients)
- Client Credentials (for automation scripts)
- Refresh Token (for token renewal)

All DB operations use get_current_session() for thread-local session access.
"""

import secrets
import time
from typing import ClassVar

from authlib.oauth2.rfc6749 import AuthorizationServer, JsonRequest, OAuth2Request, grants
from authlib.oauth2.rfc6749.errors import InvalidGrantError
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7636 import CodeChallenge

from testgen.api.oauth.models import OAuth2AuthorizationCode, OAuth2Client, OAuth2Token
from testgen.common.auth import create_jwt_token
from testgen.common.models import get_current_session
from testgen.common.models.user import User

ACCESS_TOKEN_EXPIRES_IN = 3600  # 1 hour


class AuthorizationCodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS: ClassVar[list[str]] = ["client_secret_basic", "client_secret_post", "none"]

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
        item = session.query(OAuth2AuthorizationCode).filter_by(
            code=code, client_id=client.client_id,
        ).first()
        if item and not item.is_expired():
            return item
        return None

    def delete_authorization_code(self, authorization_code):
        session = get_current_session()
        session.delete(authorization_code)

    def authenticate_user(self, authorization_code):
        session = get_current_session()
        return session.query(User).filter(User.id == authorization_code.user_id).first()


class RefreshTokenGrant(grants.RefreshTokenGrant):
    INCLUDE_NEW_REFRESH_TOKEN = True

    def authenticate_refresh_token(self, refresh_token):
        session = get_current_session()
        item = session.query(OAuth2Token).filter_by(
            refresh_token=refresh_token,
        ).first()
        if item and not item.is_revoked():
            return item
        return None

    def authenticate_user(self, credential):
        session = get_current_session()
        return session.query(User).filter(User.id == credential.user_id).first()

    def revoke_old_credential(self, credential):
        now = int(time.time())
        credential.access_token_revoked_at = now
        credential.refresh_token_revoked_at = now


class ClientCredentialsGrant(grants.ClientCredentialsGrant):
    """Client credentials grant that resolves the client's owner as the token user.

    Ensures every token has a real User identity — no "ghost" usernames.
    """

    def validate_token_request(self):
        super().validate_token_request()
        client = self.request.client
        if not client.user_id:
            raise InvalidGrantError(description="Client has no registered owner.")
        session = get_current_session()
        owner = session.query(User).filter(User.id == client.user_id).first()
        if owner is None:
            raise InvalidGrantError(description="Client owner no longer exists.")
        self.request.user = owner


class TestGenRevocationEndpoint(RevocationEndpoint):
    def query_token(self, token_string, token_type_hint):
        session = get_current_session()
        if token_type_hint == "access_token":  # noqa: S105
            return session.query(OAuth2Token).filter_by(access_token=token_string).first()
        if token_type_hint == "refresh_token":  # noqa: S105
            return session.query(OAuth2Token).filter_by(refresh_token=token_string).first()
        return (
            session.query(OAuth2Token).filter_by(access_token=token_string).first()
            or session.query(OAuth2Token).filter_by(refresh_token=token_string).first()
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
        return session.query(OAuth2Client).filter_by(client_id=client_id).first()

    def save_token(self, token, request):
        user_id = request.user.id if request.user else None
        item = OAuth2Token(
            client_id=request.client.client_id,
            user_id=user_id,
            **token,
        )
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
    access_token = create_jwt_token(user.username, expiry_seconds=ACCESS_TOKEN_EXPIRES_IN)
    token = {
        "token_type": "Bearer",
        "access_token": access_token,
        "expires_in": expires_in or ACCESS_TOKEN_EXPIRES_IN,
    }
    if include_refresh_token:
        token["refresh_token"] = secrets.token_urlsafe(48)
    if scope:
        token["scope"] = scope
    return token


def create_authorization_server() -> TestGenAuthorizationServer:
    """Create and configure the authorization server with all grant types."""
    server = TestGenAuthorizationServer()
    server.register_grant(AuthorizationCodeGrant, [CodeChallenge(required=True)])
    server.register_grant(ClientCredentialsGrant)
    server.register_grant(RefreshTokenGrant)
    server.register_endpoint(TestGenRevocationEndpoint)
    server.register_token_generator("default", _generate_bearer_token)
    return server
