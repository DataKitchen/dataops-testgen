import enum
from collections import defaultdict
from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, Integer, String, desc, func, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import aliased

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity


class TestResultStatus(enum.Enum):
    Error = "Error"
    Log = "Log"
    Passed = "Passed"
    Warning = "Warning"
    Failed = "Failed"


TestResultDiffType = tuple[TestResultStatus, TestResultStatus, list[UUID]]


class TestResult(Entity):
    __tablename__ = "test_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4)

    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_runs.id"), nullable=False)

    test_definition_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_definitions.id"), nullable=False)
    test_type: str = Column(String, ForeignKey("test_types.test_type"), nullable=False)
    auto_gen: bool = Column(Boolean)

    schema_name: str = Column(String, nullable=False)
    table_name: str = Column(String)
    column_names: str = Column(String)

    status: TestResultStatus = Column("result_status", Enum(TestResultStatus))
    message: str = Column("result_message", String)

    test_time: datetime = Column(postgresql.TIMESTAMP)
    result_code: int = Column(Integer)
    disposition: str = Column(String)
    result_measure: str = Column(String)
    threshold_value: str = Column(String)

    # Unmapped columns: result_id, skip_errors, input_parameters, severity,
    # result_signal, test_description, table_groups_id, dq_prevalence,
    # dq_record_ct, observability_status

    @classmethod
    def select_results(
        cls,
        test_run_id: UUID,
        status: TestResultStatus | None = None,
        table_name: str | None = None,
        test_type: str | None = None,
        limit: int = 50,
    ) -> list[Self]:
        clauses = [
            cls.test_run_id == test_run_id,
            func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
        ]
        if status:
            clauses.append(cls.status == status)
        if table_name:
            clauses.append(cls.table_name == table_name)
        if test_type:
            clauses.append(cls.test_type == test_type)
        query = select(cls).where(*clauses).order_by(cls.status, cls.table_name, cls.column_names).limit(limit)
        return get_current_session().scalars(query).all()

    @classmethod
    def select_failures(
        cls,
        test_run_id: UUID,
        group_by: str = "test_type",
    ) -> list[tuple]:
        allowed = {"test_type", "table_name", "column_names"}
        if group_by not in allowed:
            raise ValueError(f"group_by must be one of {allowed}")

        where = [
            cls.test_run_id == test_run_id,
            cls.status.in_([TestResultStatus.Failed, TestResultStatus.Warning]),
            func.coalesce(cls.disposition, "Confirmed") == "Confirmed",
        ]

        # Column grouping includes table_name for context → (table, column, count)
        if group_by == "column_names":
            group_cols = (cls.table_name, cls.column_names)
        else:
            group_cols = (getattr(cls, group_by),)

        query = (
            select(*group_cols, func.count().label("failure_count"))
            .where(*where)
            .group_by(*group_cols)
            .order_by(func.count().desc())
        )
        return get_current_session().execute(query).all()

    @classmethod
    def select_history(
        cls,
        test_definition_id: UUID,
        limit: int = 20,
    ) -> list[Self]:
        query = (
            select(cls)
            .where(cls.test_definition_id == test_definition_id)
            .order_by(desc(cls.test_time))
            .limit(limit)
        )
        return get_current_session().scalars(query).all()

    @classmethod
    def diff(cls, test_run_id_a: UUID, test_run_id_b: UUID) -> list[TestResultDiffType]:
        alias_a = aliased(cls)
        alias_b = aliased(cls)
        query = select(
            alias_a.status, alias_b.status, alias_b.test_definition_id,
        ).join(
            alias_b,
            alias_a.test_definition_id == alias_b.test_definition_id,
            full=True,
        ).where(
            or_(alias_a.test_run_id == test_run_id_a, alias_a.test_run_id.is_(None)),
            or_(alias_b.test_run_id == test_run_id_b, alias_b.test_run_id.is_(None)),
            alias_a.status != alias_b.status,
        )

        diff = defaultdict(list)
        for run_a_status, run_b_status, result_id in get_current_session().execute(query):
            diff[(run_a_status, run_b_status)].append(result_id)

        return [(*statuses, id_list) for statuses, id_list in diff.items()]
