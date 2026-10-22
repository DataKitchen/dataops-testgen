from enum import StrEnum


class AuditAction(StrEnum):
    """Recorded actions, named ``<entity>.<verb>``."""

    USER_SIGNED_IN = "user.signed_in"
    USER_SIGNED_OUT = "user.signed_out"


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
