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
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    CONNECTION_CREATED = "connection.created"
    CONNECTION_UPDATED = "connection.updated"
    CONNECTION_DELETED = "connection.deleted"
    TABLE_GROUP_CREATED = "table_group.created"
    TABLE_GROUP_UPDATED = "table_group.updated"
    TABLE_GROUP_DELETED = "table_group.deleted"
    TEST_SUITE_CREATED = "test_suite.created"
    TEST_SUITE_UPDATED = "test_suite.updated"
    TEST_SUITE_DELETED = "test_suite.deleted"
    MONITOR_SUITE_CREATED = "monitor_suite.created"
    MONITOR_SUITE_UPDATED = "monitor_suite.updated"
    MONITOR_SUITE_PAUSED = "monitor_suite.paused"
    MONITOR_SUITE_RESUMED = "monitor_suite.resumed"
    MONITOR_SUITE_DELETED = "monitor_suite.deleted"
    SCHEDULE_CREATED = "schedule.created"
    SCHEDULE_UPDATED = "schedule.updated"
    SCHEDULE_PAUSED = "schedule.paused"
    SCHEDULE_RESUMED = "schedule.resumed"
    SCHEDULE_DELETED = "schedule.deleted"
    NOTIFICATION_CREATED = "notification.created"
    NOTIFICATION_UPDATED = "notification.updated"
    NOTIFICATION_PAUSED = "notification.paused"
    NOTIFICATION_RESUMED = "notification.resumed"
    NOTIFICATION_DELETED = "notification.deleted"
    NOTIFICATION_DESTINATION_CREATED = "notification_destination.created"
    NOTIFICATION_DESTINATION_UPDATED = "notification_destination.updated"
    NOTIFICATION_DESTINATION_DELETED = "notification_destination.deleted"
    SCORECARD_CREATED = "scorecard.created"
    SCORECARD_UPDATED = "scorecard.updated"
    SCORECARD_DELETED = "scorecard.deleted"
    PROFILING_RUN_LAUNCHED = "profiling_run.launched"
    PROFILING_RUN_PAUSED = "profiling_run.paused"
    PROFILING_RUN_RESUMED = "profiling_run.resumed"
    PROFILING_RUN_CANCELED = "profiling_run.canceled"
    PROFILING_RUN_DELETED = "profiling_run.deleted"
    TEST_RUN_LAUNCHED = "test_run.launched"
    TEST_RUN_CANCELED = "test_run.canceled"
    TEST_RUN_DELETED = "test_run.deleted"


class AuditTargetType(StrEnum):
    """Kinds of affected object, as records name them."""

    USER = "user"
    PROJECT = "project"
    ACCESS_TOKEN = "access_token"  # noqa: S105
    OAUTH_CLIENT = "oauth_client"
    SETTING = "setting"
    PROJECT_INFO = "project.info"
    PROJECT_OBSERVABILITY = "project.observability"
    PROJECT_RETENTION = "project.retention"
    CONNECTION = "connection"
    TABLE_GROUP = "table_group"
    TEST_SUITE = "test_suite"
    MONITOR_SUITE = "monitor_suite"
    SCHEDULE = "schedule"
    NOTIFICATION = "notification"
    NOTIFICATION_DESTINATION = "notification_destination"
    SCORECARD = "scorecard"
    PROFILING_RUN = "profiling_run"
    TEST_RUN = "test_run"


CHANGE_ACTIONS = frozenset({
    AuditAction.USER_UPDATED,
    AuditAction.USER_ADMIN_GRANTED,
    AuditAction.USER_ADMIN_REVOKED,
    AuditAction.PROJECT_MEMBER_ROLE_CHANGED,
    AuditAction.SETTING_UPDATED,
    AuditAction.PROJECT_UPDATED,
    AuditAction.CONNECTION_UPDATED,
    AuditAction.TABLE_GROUP_UPDATED,
    AuditAction.TEST_SUITE_UPDATED,
    AuditAction.MONITOR_SUITE_UPDATED,
    AuditAction.SCHEDULE_UPDATED,
    AuditAction.NOTIFICATION_UPDATED,
    AuditAction.NOTIFICATION_DESTINATION_UPDATED,
    AuditAction.SCORECARD_UPDATED,
})
"""Actions recorded only when a field changed."""


class Outcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
