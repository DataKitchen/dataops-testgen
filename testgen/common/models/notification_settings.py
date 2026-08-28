import enum
import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Generic, Self, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, and_, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import relationship
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import JSON_TYPE
from testgen.common.models.entity import Entity
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.notifications import messages

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

    Rows come out of ``_paginate`` as keyword unpacks (``data_class(**row)``), so the
    dataclass field order does not need to match the SELECT projection.
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
    notification_destination_id: UUID | None = None


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
    notification_destination_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("notification_destinations.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )

    destination = relationship(
        "NotificationDestination",
        lazy="joined",
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
                cls.notification_destination_id.label("notification_destination_id"),
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
    def paginate_for_projects(
        cls,
        project_codes: Iterable[str],
        *clauses,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Self], int]:
        """Paginated notification instances (full ORM rows) across one or more projects.

        ``list_for_projects`` returns ``NotificationSummary`` dataclasses for the
        MCP surface that renders flat markdown; this method returns polymorphic
        ORM instances for callers that need ``isinstance`` dispatch and full
        access to relationships (``destination``, per-event trigger enums, etc.).
        """
        query = (
            select(cls)
            .where(cls.project_code.in_(list(project_codes)))
            .order_by(
                cls.project_code, cls.event, cls.test_suite_id,
                cls.table_group_id, cls.score_definition_id, cls.id,
            )
        )
        if clauses:
            query = query.where(*clauses)
        rows, total = cls._paginate(query, page=page, limit=limit)
        # Without a ``data_class``, ``_paginate`` returns ``RowMapping`` objects.
        # An entity ``select(cls)`` produces exactly one value per row -- the ORM
        # instance -- so take that value. Note ``row[0]`` does NOT work here:
        # ``RowMapping`` is keyed by column name, so an integer subscript raises
        # ``KeyError``.
        return [next(iter(row.values())) for row in rows], total

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
        addresses_inline = bool(self.recipients)
        names_destination = self.notification_destination_id is not None
        if addresses_inline and names_destination:
            raise NotificationSettingsValidationError(messages.ADDRESSING_BOTH)
        if not addresses_inline and not names_destination:
            raise NotificationSettingsValidationError(messages.ADDRESSING_NEITHER)
        if addresses_inline:
            for addr in self.recipients:
                if not is_valid_email(addr):
                    raise NotificationSettingsValidationError(messages.invalid_email(addr))
        else:
            from testgen.common.models.notification_destinations import NotificationDestination
            destination = NotificationDestination.get(self.notification_destination_id)
            if destination is None or destination.project_code != self.project_code:
                raise NotificationSettingsValidationError(messages.DESTINATION_NOT_FOUND)
        self._validate_settings()

    def save(self) -> None:
        self.validate()
        super().save()
        # After an FK write, the eager-loaded ``destination`` relationship still
        # holds the old target -- SQLAlchemy does not sync ``notification_destination_id ->
        # destination``. Expire it so the next read pulls the fresh row, which
        # ``lazy="joined"`` then reloads on the next attribute access.
        # Without this, delivery_target / delivery_target_description /
        # serializers report the previous destination for the whole request.
        get_current_session().expire(self, ["destination"])

    @property
    def delivery_target(self):
        """Object with a ``deliver(context, template)`` method for this rule's addressing.

        Returns the linked ``NotificationDestination`` when the rule names one, or an
        ``InlineRecipientList`` wrapping ``self.recipients`` otherwise. The send path
        calls ``self.delivery_target.deliver(...)`` and never branches on addressing.
        """
        from testgen.common.models.notification_destinations import InlineRecipientList
        if self.notification_destination_id is not None:
            return self.destination
        return InlineRecipientList(self.recipients)

    @property
    def delivery_target_description(self) -> str:
        """Short human-readable label for this rule's delivery target, for log messages."""
        if self.notification_destination_id is not None:
            dest = self.destination
            return f"destination='{dest.name}' ({dest.destination_type})" if dest else f"destination={self.notification_destination_id} (missing)"
        return f"inline recipients={len(self.recipients)}"


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
            raise NotificationSettingsValidationError(messages.INVALID_TRIGGER)


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
            recipients: list[str] | None = None,
            trigger: TestRunNotificationTrigger | None = None,
            *,
            notification_destination_id: UUID | None = None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.test_run,
            project_code=project_code,
            test_suite_id=test_suite_id,
            recipients=list(recipients or []),
            notification_destination_id=notification_destination_id,
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
            recipients: list[str] | None = None,
            trigger: ProfilingRunNotificationTrigger | None = None,
            *,
            notification_destination_id: UUID | None = None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.profiling_run,
            project_code=project_code,
            table_group_id=table_group_id,
            recipients=list(recipients or []),
            notification_destination_id=notification_destination_id,
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
            raise NotificationSettingsValidationError(messages.SCORE_THRESHOLD_MISSING)
        for score, label in ((self.total_score_threshold, "Total"), (self.cde_score_threshold, "CDE")):
            if score is not None and not 0 <= score <= 100:
                raise NotificationSettingsValidationError(messages.score_threshold_out_of_range(label))

    @classmethod
    def create(
            cls,
            project_code: str,
            score_definition_id: UUID | None,
            recipients: list[str] | None = None,
            total_score_threshold: float | Decimal | None = None,
            cde_score_threshold: float | Decimal | None = None,
            *,
            notification_destination_id: UUID | None = None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.score_drop,
            project_code=project_code,
            score_definition_id=score_definition_id,
            recipients=list(recipients or []),
            notification_destination_id=notification_destination_id,
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
            recipients: list[str] | None = None,
            trigger: TestRunNotificationTrigger | None = None,
            table_name: str | None = None,
            *,
            notification_destination_id: UUID | None = None,
    ) -> Self:
        ns = cls(
            event=NotificationEvent.monitor_run,
            project_code=project_code,
            table_group_id=table_group_id,
            test_suite_id=test_suite_id,
            recipients=list(recipients or []),
            notification_destination_id=notification_destination_id,
            settings={"trigger": trigger.value, "table_name": table_name},
        )
        ns.save()
        return ns


# Import at module bottom so the string reference `"NotificationDestination"` on
# the `destination` relationship above resolves at mapper-configuration time.
# The circular import is safe: notification_destinations only pulls names that
# are already defined earlier in this module.
from testgen.common.models import notification_destinations  # noqa: F401
