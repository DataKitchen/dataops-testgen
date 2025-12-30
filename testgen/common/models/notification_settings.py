import enum
import re
from collections.abc import Iterable
from decimal import Decimal
from typing import ClassVar, Generic, Self, TypeVar
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, and_, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import JSON_TYPE
from testgen.common.models.entity import Entity
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite

SENTINEL_TYPE = type("Sentinel", (object,), {})

SENTINEL = SENTINEL_TYPE()

TriggerT = TypeVar("TriggerT", bound=Enum)


class TestRunNotificationTrigger(enum.Enum):
    always = "always"
    on_failures = "on_failures"
    on_warnings = "on_warnings"
    on_changes = "on_changes"


class ProfilingRunNotificationTrigger(enum.Enum):
    always = "always"
    on_changes = "on_changes"


class NotificationEvent(enum.Enum):
    test_run = "test_run"
    profiling_run = "profiling_run"
    score_drop = "score_drop"


class NotificationSettingsValidationError(Exception):
    """Validation Exception. Messaging should be suitable for the users."""
    pass


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
    def _base_select_query(
            cls,
            *,
            enabled: bool | SENTINEL_TYPE = SENTINEL,
            event: NotificationEvent | SENTINEL_TYPE = SENTINEL,
            project_code: str | SENTINEL_TYPE = SENTINEL,
            test_suite_id: UUID | None | SENTINEL_TYPE = SENTINEL,
            table_group_id: UUID | None | SENTINEL_TYPE = SENTINEL,
            score_definition_id: UUID | None | SENTINEL_TYPE = SENTINEL,
    ) -> Select:
        fk_count = len([None for fk in (test_suite_id, table_group_id, score_definition_id) if fk is not SENTINEL])
        if fk_count > 1:
            raise ValueError("Only one foreign key can be used at a time.")
        elif fk_count == 1 and (project_code is not SENTINEL or event is not SENTINEL):
            raise ValueError("Filtering by project_code or event is not allowed when filtering by a foreign key.")

        query = select(cls)
        if enabled is not SENTINEL:
            query = query.where(cls.enabled == enabled)
        if event is not SENTINEL:
            query = query.where(cls.event == event)
        if project_code is not SENTINEL:
            query = query.where(cls.project_code == project_code)

        def _subquery_clauses(entity, rel_col, id_value):
            return and_(
                cls.project_code.in_(select(entity.project_code).where(entity.id == id_value)),
                or_(rel_col == id_value, rel_col.is_(None)),
            )

        if test_suite_id is not SENTINEL:
            query = query.where(_subquery_clauses(TestSuite, cls.test_suite_id, test_suite_id))
        elif table_group_id is not SENTINEL:
            query = query.where(_subquery_clauses(TableGroup, cls.table_group_id, table_group_id))
        elif score_definition_id is not SENTINEL:
            query = query.where(_subquery_clauses(ScoreDefinition, cls.score_definition_id, score_definition_id))

        return query

    @classmethod
    def select(
            cls,
            *,
            enabled: bool | SENTINEL_TYPE = SENTINEL,
            event: NotificationEvent | SENTINEL_TYPE = SENTINEL,
            project_code: str | SENTINEL_TYPE = SENTINEL,
            test_suite_id: UUID | None | SENTINEL_TYPE = SENTINEL,
            table_group_id: UUID | None | SENTINEL_TYPE = SENTINEL,
            score_definition_id: UUID | None | SENTINEL_TYPE = SENTINEL,
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

    def _validate_settings(self):
        pass

    def validate(self):
        if len(self.recipients) < 1:
            raise NotificationSettingsValidationError("At least one recipient must be defined.")
        for addr in self.recipients:
            if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", addr):
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
