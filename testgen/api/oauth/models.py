import time

from authlib.integrations.sqla_oauth2 import (
    OAuth2AuthorizationCodeMixin,
    OAuth2ClientMixin,
    OAuth2TokenMixin,
)
from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base


class OAuth2Client(Base, OAuth2ClientMixin):
    __tablename__ = "oauth2_clients"

    id = Column(postgresql.UUID(as_uuid=True), primary_key=True, server_default="gen_random_uuid()")
    user_id = Column(postgresql.UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)

    # Override to widen — JWTs can exceed 255 chars
    # (the mixin defines client_id as VARCHAR(48) which is fine)


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

    def is_refresh_token_active(self) -> bool:
        if self.is_revoked():
            return False
        expires_at = self.issued_at + self.expires_in * 2
        return expires_at >= time.time()
