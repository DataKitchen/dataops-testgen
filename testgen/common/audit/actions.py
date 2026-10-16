from enum import StrEnum


class AuditAction(StrEnum):
    """Recorded actions, named ``<entity>.<verb>``."""

    USER_SIGNED_IN = "user.signed_in"
    USER_SIGNED_OUT = "user.signed_out"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_ADMIN_GRANTED = "user.admin_granted"
    USER_ADMIN_REVOKED = "user.admin_revoked"
    PROJECT_MEMBER_ADDED = "project.member_added"
    PROJECT_MEMBER_REMOVED = "project.member_removed"
    PROJECT_MEMBER_ROLE_CHANGED = "project.member_role_changed"
    ACCESS_TOKEN_CREATED = "access_token.created"  # noqa: S105
    ACCESS_TOKEN_REVOKED = "access_token.revoked"  # noqa: S105
    OAUTH_CLIENT_AUTHORIZED = "oauth_client.authorized"
    OAUTH_CLIENT_ACCESS_REVOKED = "oauth_client.access_revoked"
    SETTING_UPDATED = "setting.updated"


class AuditTargetType(StrEnum):
    """Kinds of affected object, as records name them."""

    USER = "user"
    ACCESS_TOKEN = "access_token"  # noqa: S105
    OAUTH_CLIENT = "oauth_client"
    SETTING = "setting"


CHANGE_ACTIONS = frozenset({
    AuditAction.USER_UPDATED,
    AuditAction.USER_ADMIN_GRANTED,
    AuditAction.USER_ADMIN_REVOKED,
    AuditAction.PROJECT_MEMBER_ROLE_CHANGED,
    AuditAction.SETTING_UPDATED,
})
"""Actions recorded only when a field changed."""


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
