import enum
from collections import defaultdict
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String, and_, or_, select
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

    # Note: not all table columns are implemented by this entity

    @classmethod
    def diff(cls, test_run_id_a: UUID, test_run_id_b: UUID) -> list[TestResultDiffType]:
        alias_a = aliased(cls)
        alias_b = aliased(cls)
        query = select(
            alias_a.status, alias_b.status, alias_b.test_definition_id,
        ).join(
            alias_b,
            or_(
                and_(
                    alias_a.auto_gen.is_(True),
                    alias_b.auto_gen.is_(True),
                    alias_a.test_suite_id == alias_b.test_suite_id,
                    alias_a.schema_name == alias_b.schema_name,
                    alias_a.table_name.isnot_distinct_from(alias_b.table_name),
                    alias_a.column_names.isnot_distinct_from(alias_b.column_names),
                    alias_a.test_type == alias_b.test_type,
                ),
                and_(
                    alias_a.auto_gen.isnot(True),
                    alias_b.auto_gen.isnot(True),
                    alias_a.test_definition_id == alias_b.test_definition_id,
                ),
            ),
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
