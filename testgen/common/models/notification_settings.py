import enum
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Generic, Self, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, and_, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import JSON_TYPE
from testgen.common.models.entity import Entity
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

SENTINEL_TYPE = type("Sentinel", (object,), {})

SENTINEL = SENTINEL_TYPE()

TriggerT = TypeVar("TriggerT", bound=Enum)

_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def is_valid_email(value: str) -> bool:
    """Return whether ``value`` is a well-formed email address.

    Single source of truth for recipient validation, shared by the model's
    ``validate()`` and the MCP layer's batch recipient check.
    """
    return bool(_EMAIL_REGEX.match(value))


class TestRunNotificationTrigger(enum.Enum):
    always = "always"
    on_failures = "on_failures"
    on_warnings = "on_warnings"
    on_changes = "on_changes"


class ProfilingRunNotificationTrigger(enum.Enum):
    always = "always"
    on_changes = "on_changes"


class MonitorNotificationTrigger(enum.Enum):
    on_anomalies = "on_anomalies"


class NotificationEvent(enum.Enum):
    test_run = "test_run"
    profiling_run = "profiling_run"
    score_drop = "score_drop"
    monitor_run = "monitor_run"


class NotificationSettingsValidationError(Exception):
    """Validation Exception. Messaging should be suitable for the users."""
    pass


@dataclass
class NotificationSummary:
    """Row shape for paginated ``NotificationSettings.list_for_*`` queries.

    Field order matches the SELECT projection in the ``list_for_*`` methods.
    ``settings`` keeps the raw JSONB blob so event-specific values (``trigger``,
    ``total_threshold``, ``cde_threshold``, ``table_name``) can be read by the
    consumer's format helpers without forking the dataclass per event type.
    """

    id: UUID
    project_code: str
    event: NotificationEvent
    enabled: bool
    recipients: list[str]
    test_suite_id: UUID | None
    table_group_id: UUID | None
    score_definition_id: UUID | None
    settings: dict


class NotificationSettings(Entity):
    __tablename__ = "notification_settings"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)

    event: NotificationEvent = Column(Enum(NotificationEvent))
    enabled: bool = Column(Boolean, default=True)
    recipients: list[str] = Column(postgresql.JSONB, nullable=False, default=[])

    test_suite_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    table_group_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("table_groups.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )
    score_definition_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("score_definitions.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )

    settings: JSON_TYPE = Column(postgresql.JSONB, nullable=False, default={})

    __mapper_args__: ClassVar = {
        "polymorphic_on": event,
        "polymorphic_identity": "base",
    }

    @classmethod
    def _scope_subquery(cls, entity, rel_col, id_value) -> ColumnElement[bool]:
        """Where-clause: rows scoped to ``entity.id == id_value`` plus project-wide rows
        (``rel_col IS NULL``) for the same project. Used by both the streaming
        ``select()`` and the paginated ``list_for_*`` methods.
        """
        return and_(
            cls.project_code.in_(select(entity.project_code).where(entity.id == id_value)),
            or_(rel_col == id_value, rel_col.is_(None)),
        )

    @classmethod
    def _base_select_query(
            cls,
            *,
            enabled: bool | SENTINEL_TYPE = SENTINEL,
            event: NotificationEvent | SENTINEL_TYPE = SENTINEL,
            project_code: str | SENTINEL_TYPE = SENTINEL,
            test_suite_id: UUID | SENTINEL_TYPE | None = SENTINEL,
            table_group_id: UUID | SENTINEL_TYPE | None = SENTINEL,
            score_definition_id: UUID | SENTINEL_TYPE | None = SENTINEL,
    ) -> Select:
        fk_count = len([None for fk in (test_suite_id, table_group_id, score_definition_id) if fk is not SENTINEL])
        if fk_count > 1:
            raise ValueError("Only one foreign key can be used at a time.")
        elif fk_count == 1 and (project_code is not SENTINEL):
            raise ValueError("Filtering by project_code or event is not allowed when filtering by a foreign key.")

        query = select(cls)
        if enabled is not SENTINEL:
            query = query.where(cls.enabled == enabled)
        if event is not SENTINEL:
            query = query.where(cls.event == event)
        if project_code is not SENTINEL:
            query = query.where(cls.project_code == project_code)

        if test_suite_id is not SENTINEL:
            query = query.where(cls._scope_subquery(TestSuite, cls.test_suite_id, test_suite_id))
        elif table_group_id is not SENTINEL:
            query = query.where(cls._scope_subquery(TableGroup, cls.table_group_id, table_group_id))
        elif score_definition_id is not SENTINEL:
            query = query.where(cls._scope_subquery(ScoreDefinition, cls.score_definition_id, score_definition_id))

        return query

    @classmethod
    def select(
            cls,
            *,
            enabled: bool | SENTINEL_TYPE = SENTINEL,
            event: NotificationEvent | SENTINEL_TYPE = SENTINEL,
            project_code: str | SENTINEL_TYPE = SENTINEL,
            test_suite_id: UUID | SENTINEL_TYPE | None = SENTINEL,
            table_group_id: UUID | SENTINEL_TYPE | None = SENTINEL,
            score_definition_id: UUID | SENTINEL_TYPE | None = SENTINEL,
    ) -> Iterable[Self]:
        query = cls._base_select_query(
            enabled=enabled,
            event=event,
            project_code=project_code,
            test_suite_id=test_suite_id,
            table_group_id=table_group_id,
            score_definition_id=score_definition_id,
        ).order_by(
            cls.project_code, cls.event, cls.test_suite_id, cls.table_group_id, cls.score_definition_id, cls.id,
        )
        return get_current_session().scalars(query)

    @classmethod
    def _list_query(cls, scope_clause) -> Select:
        """Projection + ORDER BY shared by every ``list_for_*`` classmethod.

        ``scope_clause`` is the WHERE expression that narrows to a project or a parent
        entity (and its project-wide siblings). Caller-supplied filters arrive as
        ``*clauses`` in each ``list_for_*`` wrapper and are appended here.
        """
        return (
            select(
                cls.id.label("id"),
                cls.project_code.label("project_code"),
                cls.event.label("event"),
                cls.enabled.label("enabled"),
                cls.recipients.label("recipients"),
                cls.test_suite_id.label("test_suite_id"),
                cls.table_group_id.label("table_group_id"),
                cls.score_definition_id.label("score_definition_id"),
                cls.settings.label("settings"),
            )
            .where(scope_clause)
            .order_by(
                cls.project_code, cls.event, cls.test_suite_id,
                cls.table_group_id, cls.score_definition_id, cls.id,
            )
        )

    @classmethod
    def list_for_projects(
        cls,
        project_codes: Iterable[str],
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[NotificationSummary], int]:
        """Paginated notifications across one or more projects."""
        query = cls._list_query(cls.project_code.in_(list(project_codes)))
        if clauses:
            query = query.where(*clauses)
        return cls._paginate(query, page=page, limit=limit, data_class=NotificationSummary)

    @classmethod
    def list_for_test_suite(
        cls,
        test_suite_id: UUID,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[NotificationSummary], int]:
        """Paginated notifications whose ``test_suite_id`` exactly matches ``test_suite_id``.

        Use ``list_for_projects`` to also surface project-wide notifications (rows
        with ``test_suite_id IS NULL``) — they're a different display concern from
        narrowing to a specific suite.
        """
        query = cls._list_query(cls.test_suite_id == test_suite_id)
        if clauses:
            query = query.where(*clauses)
        return cls._paginate(query, page=page, limit=limit, data_class=NotificationSummary)

    @classmethod
    def list_for_table_group(
        cls,
        table_group_id: UUID,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[NotificationSummary], int]:
        """Paginated notifications whose ``table_group_id`` exactly matches ``table_group_id``.

        Use ``list_for_projects`` to also surface project-wide notifications (rows
        with ``table_group_id IS NULL``).
        """
        query = cls._list_query(cls.table_group_id == table_group_id)
        if clauses:
            query = query.where(*clauses)
        return cls._paginate(query, page=page, limit=limit, data_class=NotificationSummary)

    @classmethod
    def list_for_score_definition(
        cls,
        score_definition_id: UUID,
        *clauses,
        page: int = 1,
        limit: int = 50,
    ) -> tuple[list[NotificationSummary], int]:
        """Paginated notifications whose ``score_definition_id`` exactly matches ``score_definition_id``.

        Use ``list_for_projects`` to also surface project-wide notifications (rows
        with ``score_definition_id IS NULL``).
        """
        query = cls._list_query(cls.score_definition_id == score_definition_id)
        if clauses:
            query = query.where(*clauses)
        return cls._paginate(query, page=page, limit=limit, data_class=NotificationSummary)

    def _validate_settings(self):
        pass

    def validate(self):
        if len(self.recipients) < 1:
            raise NotificationSettingsValidationError("At least one recipient must be defined.")
        for addr in self.recipients:
            if not is_valid_email(addr):
                raise NotificationSettingsValidationError(f"Invalid email address: {addr}.")
        self._validate_settings()

    def save(self) -> None:
        self.validate()
        super().save()


class RunNotificationSettings(NotificationSettings, Generic[TriggerT]):
    __abstract__ = True
    trigger_enum: ClassVar[type[TriggerT]]

    @property
    def trigger(self) -> TriggerT | None:
        return self.trigger_enum(self.settings["trigger"]) if "trigger" in self.settings else None

    @trigger.setter
    def trigger(self, trigger: TriggerT) -> None:
        self.settings = {"trigger": trigger.value}

    def _validate_settings(self):
        if not isinstance(self.trigger, self.trigger_enum):
            raise NotificationSettingsValidationError("Invalid notification trigger.")


class TestRunNotificationSettings(RunNotificationSettings[TestRunNotificationTrigger]):

    __mapper_args__: ClassVar = {
        "polymorphic_identity": NotificationEvent.test_run,
    }
    trigger_enum = TestRunNotificationTrigger

    @classmethod
    def create(
            cls,
            project_code: str,
            test_suite_id: UUID | None,
            recipients: list[str],
            trigger: TestRunNotificationTrigger,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.test_run,
            project_code=project_code,
            test_suite_id=test_suite_id,
            recipients=recipients,
            settings={"trigger": trigger.value}
        )
        ns.save()
        return ns


class ProfilingRunNotificationSettings(RunNotificationSettings[ProfilingRunNotificationTrigger]):

    __mapper_args__: ClassVar = {
        "polymorphic_identity": NotificationEvent.profiling_run,
    }
    trigger_enum = ProfilingRunNotificationTrigger

    @classmethod
    def create(
            cls,
            project_code: str,
            table_group_id: UUID | None,
            recipients: list[str],
            trigger: ProfilingRunNotificationTrigger,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.profiling_run,
            project_code=project_code,
            table_group_id=table_group_id,
            recipients=recipients,
            settings={"trigger": trigger.value}
        )
        ns.save()
        return ns


class ScoreDropNotificationSettings(NotificationSettings):

    __mapper_args__: ClassVar = {
        "polymorphic_identity": NotificationEvent.score_drop,
    }

    @staticmethod
    def _value_to_threshold(value: Decimal | float | None):
        return str(Decimal(value).quantize(Decimal("0.1"))) if value is not None else None

    @property
    def total_score_threshold(self) -> Decimal | None:
        return Decimal(self.settings["total_threshold"]) if self.settings.get("total_threshold") else None

    @total_score_threshold.setter
    def total_score_threshold(self, value: Decimal | float | None) -> None:
        self.settings = {**self.settings, "total_threshold": self._value_to_threshold(value)}

    @property
    def cde_score_threshold(self) -> Decimal | None:
        return Decimal(self.settings["cde_threshold"]) if self.settings.get("cde_threshold") else None

    @cde_score_threshold.setter
    def cde_score_threshold(self, value: Decimal | float | None) -> None:
        self.settings = {**self.settings, "cde_threshold": self._value_to_threshold(value)}

    def _validate_settings(self):
        if not (self.total_score_threshold or self.cde_score_threshold):
            raise NotificationSettingsValidationError("At least one score threshold must be set.")
        for score, label in ((self.total_score_threshold, "Total"), (self.cde_score_threshold, "CDE")):
            if score is not None and not 0 <= score <= 100:
                raise NotificationSettingsValidationError(f"The {label} score threshold must be between 0 and 100")

    @classmethod
    def create(
            cls,
            project_code: str,
            score_definition_id: UUID | None,
            recipients: list[str],
            total_score_threshold: float | Decimal | None,
            cde_score_threshold: float | Decimal | None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.score_drop,
            project_code=project_code,
            score_definition_id=score_definition_id,
            recipients=recipients,
            settings={
                "total_threshold": cls._value_to_threshold(total_score_threshold),
                "cde_threshold": cls._value_to_threshold(cde_score_threshold),
            },
        )
        ns.save()
        return ns


class MonitorNotificationSettings(RunNotificationSettings[TestRunNotificationTrigger]):

    __mapper_args__: ClassVar = {
        "polymorphic_identity": NotificationEvent.monitor_run,
    }
    trigger_enum = MonitorNotificationTrigger

    @property
    def table_name(self) -> str | None:
        return self.settings["table_name"] if self.settings.get("table_name") else None

    @table_name.setter
    def table_name(self, value: str | None) -> None:
        self.settings = {**self.settings, "table_name": value}

    @classmethod
    def create(
            cls,
            project_code: str,
            table_group_id: UUID,
            test_suite_id: UUID,
            recipients: list[str],
            trigger: TestRunNotificationTrigger,
            table_name: str | None = None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.monitor_run,
            project_code=project_code,
            table_group_id=table_group_id,
            test_suite_id=test_suite_id,
            recipients=recipients,
            settings={"trigger": trigger.value, "table_name": table_name},
        )
        ns.save()
        return ns
