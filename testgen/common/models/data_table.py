from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    String,
    and_,
    asc,
    case,
    func,
    select,
)
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.entity import Entity
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup


@dataclass
class TableColumnSummary:
    column_name: str
    general_type: str | None
    functional_data_type: str | None
    db_data_type: str | None
    has_nulls: bool | None


@dataclass
class TableProfilingOverview:
    id: UUID
    table_groups_id: UUID
    schema_name: str | None
    table_name: str
    record_ct: int | None
    column_ct: int | None
    dq_score_profiling: float | None
    dq_score_testing: float | None
    cde_count: int
    hygiene_issue_count: int
    latest_profile_id: UUID | None
    latest_profile_started_at: datetime | None
    latest_profile_job_execution_id: UUID | None
    columns: list[TableColumnSummary] = field(default_factory=list)


class DataTable(Entity):
    __tablename__ = "data_table_chars"

    id: UUID = Column("table_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str | None = Column(String)
    table_name: str = Column(String)
    column_ct: int | None = Column(BigInteger)
    record_ct: int | None = Column(BigInteger)
    approx_record_ct: int | None = Column(BigInteger)
    critical_data_element: bool | None = Column(Boolean)
    drop_date: datetime | None = Column(postgresql.TIMESTAMP)
    last_complete_profile_run_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float | None = Column(Float)
    dq_score_testing: float | None = Column(Float)

    # Unmapped columns: functional_table_type, description, data_source,
    # source_system, source_process, business_domain, stakeholder_group,
    # transform_level, aggregation_level, data_product, add_date,
    # last_refresh_date, last_profile_record_ct

    @classmethod
    def select_table_names(
        cls, table_groups_id: UUID, project_codes: list[str] | None = None, limit: int | None = 100, offset: int = 0,
    ) -> list[str]:
        query = select(cls.table_name).where(cls.table_groups_id == table_groups_id)
        if project_codes is not None:
            query = query.join(TableGroup, cls.table_groups_id == TableGroup.id).where(
                TableGroup.project_code.in_(project_codes)
            )
        query = query.order_by(asc(func.lower(cls.table_name))).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return list(get_current_session().scalars(query).all())

    @classmethod
    def count_tables(cls, table_groups_id: UUID, project_codes: list[str] | None = None) -> int:
        query = select(func.count()).select_from(cls).where(cls.table_groups_id == table_groups_id)
        if project_codes is not None:
            query = query.join(TableGroup, cls.table_groups_id == TableGroup.id).where(
                TableGroup.project_code.in_(project_codes)
            )
        return get_current_session().scalar(query) or 0

    @classmethod
    def get_profiling_overview(
        cls, table_groups_id: UUID, table_name: str,
    ) -> TableProfilingOverview | None:
        session = get_current_session()

        header_query = (
            select(
                cls.id,
                cls.table_groups_id,
                cls.schema_name,
                cls.table_name,
                cls.record_ct,
                cls.column_ct,
                cls.dq_score_profiling,
                cls.dq_score_testing,
                cls.last_complete_profile_run_id.label("latest_profile_id"),
                JobExecution.started_at.label("latest_profile_started_at"),
                JobExecution.id.label("latest_profile_job_execution_id"),
            )
            .outerjoin(ProfilingRun, ProfilingRun.id == cls.last_complete_profile_run_id)
            .outerjoin(JobExecution, JobExecution.id == ProfilingRun.job_execution_id)
            .where(
                cls.table_groups_id == table_groups_id,
                cls.table_name == table_name,
                cls.drop_date.is_(None),
            )
        )
        header = session.execute(header_query).mappings().first()
        if not header:
            return None

        columns_query = (
            select(
                DataColumnChars.column_name,
                DataColumnChars.general_type,
                DataColumnChars.functional_data_type,
                DataColumnChars.db_data_type,
                case(
                    (ProfileResult.null_value_ct.is_(None), None),
                    (ProfileResult.null_value_ct > 0, True),
                    else_=False,
                ).label("has_nulls"),
            )
            .outerjoin(
                ProfileResult,
                and_(
                    ProfileResult.profile_run_id == DataColumnChars.last_complete_profile_run_id,
                    ProfileResult.schema_name == DataColumnChars.schema_name,
                    ProfileResult.table_name == DataColumnChars.table_name,
                    ProfileResult.column_name == DataColumnChars.column_name,
                ),
            )
            .where(
                DataColumnChars.table_id == header["id"],
                DataColumnChars.drop_date.is_(None),
            )
            .order_by(asc(DataColumnChars.ordinal_position), asc(DataColumnChars.column_name))
        )
        columns = [TableColumnSummary(**row) for row in session.execute(columns_query).mappings().all()]

        cde_count = session.scalar(
            select(func.count())
            .select_from(DataColumnChars)
            .where(
                DataColumnChars.table_id == header["id"],
                DataColumnChars.critical_data_element.is_(True),
                DataColumnChars.drop_date.is_(None),
            )
        ) or 0

        hygiene_issue_count = 0
        if header["latest_profile_id"]:
            hygiene_issue_count = session.scalar(
                select(func.count())
                .select_from(HygieneIssue)
                .where(
                    HygieneIssue.profile_run_id == header["latest_profile_id"],
                    HygieneIssue.table_name == table_name,
                    func.coalesce(HygieneIssue.disposition, "Confirmed") == "Confirmed",
                )
            ) or 0

        return TableProfilingOverview(
            **header,
            cde_count=cde_count,
            hygiene_issue_count=hygiene_issue_count,
            columns=columns,
        )
