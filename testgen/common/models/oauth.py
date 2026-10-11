import time
from enum import StrEnum

from authlib.integrations.sqla_oauth2 import (
    OAuth2AuthorizationCodeMixin,
    OAuth2ClientMixin,
    OAuth2TokenMixin,
)
from sqlalchemy import Column, ForeignKey, Integer, String, case, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.hybrid import hybrid_property

from testgen import settings
from testgen.common.models import Base


class OAuth2ClientType(StrEnum):
    """How an OAuth2 client was provisioned.

    PAT clients are created by the authenticated personal-access-token path and owned by
    a user; EXTERNAL clients are dynamically registered (MCP apps, automation scripts).
    """

    PAT = "pat"
    EXTERNAL = "external"


class OAuth2ClientAuthMethod(StrEnum):
    """Client authentication method at the token and revocation endpoints (RFC 7591 token_endpoint_auth_method).

    NONE is a public client: it holds no secret and identifies itself by client_id alone.
    """

    CLIENT_SECRET_BASIC = "client_secret_basic"  # noqa: S105
    CLIENT_SECRET_POST = "client_secret_post"  # noqa: S105
    NONE = "none"


class PersonalAccessTokenStatus(StrEnum):
    """Display status of a personal access token. Revoked takes precedence over expired."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OAuth2Client(Base, OAuth2ClientMixin):
    __tablename__ = "oauth2_clients"

    id = Column(postgresql.UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    client_type = Column(String(20), nullable=False, default=OAuth2ClientType.EXTERNAL)

    # Override to widen — JWTs can exceed 255 chars
    # (the mixin defines client_id as VARCHAR(48) which is fine)

    def check_client_secret(self, client_secret: str) -> bool:
        if not self.client_secret:
            return False
        return super().check_client_secret(client_secret)

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:  # noqa: ARG002
        """Whether the client may authenticate with ``method``.

        The registered method applies to every endpoint, so a confidential client cannot
        authenticate by client_id alone at the revocation endpoint.
        """
        return self.token_endpoint_auth_method == method


class OAuth2AuthorizationCode(Base, OAuth2AuthorizationCodeMixin):
    __tablename__ = "oauth2_authorization_codes"

    id = Column(postgresql.UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    user_id = Column(postgresql.UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=False)


class OAuth2Token(Base, OAuth2TokenMixin):
    __tablename__ = "oauth2_tokens"

    id = Column(postgresql.UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    user_id = Column(postgresql.UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), nullable=True)

    # Override to allow longer JWTs as access tokens
    access_token = Column(String(2048), unique=True, nullable=False)

    # Set only for personal access tokens; NULL for tokens from the auth-code / MCP flows
    name = Column(String(255), nullable=True)

    # Set on a rotated refresh token: when the first refresh token of its chain was issued, so
    # rotation does not extend the chain's lifetime.
    refresh_token_chain_issued_at = Column(Integer, nullable=True)

    @property
    def refresh_chain_issued_at(self) -> int:
        return self.refresh_token_chain_issued_at or self.issued_at

    def is_refresh_token_active(self) -> bool:
        if self.refresh_token_revoked_at:
            return False
        expires_at = self.refresh_chain_issued_at + settings.REFRESH_TOKEN_EXPIRES_IN
        return expires_at >= time.time()

    @hybrid_property
    def status(self) -> PersonalAccessTokenStatus:
        """Personal access token status, derived from revocation and expiry.

        Instance side reads the app clock; the SQL expression reads the DB clock —
        both are wall-clock "now", evaluated independently.
        """
        if self.access_token_revoked_at:
            return PersonalAccessTokenStatus.REVOKED
        if self.issued_at + self.expires_in < time.time():
            return PersonalAccessTokenStatus.EXPIRED
        return PersonalAccessTokenStatus.ACTIVE

    @status.expression  # type: ignore[no-redef]
    def status(cls):
        return case(
            (cls.access_token_revoked_at > 0, PersonalAccessTokenStatus.REVOKED.value),
            (cls.issued_at + cls.expires_in < func.extract("epoch", func.now()), PersonalAccessTokenStatus.EXPIRED.value),
            else_=PersonalAccessTokenStatus.ACTIVE.value,
        )
