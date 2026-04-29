from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    and_,
    asc,
    func,
    select,
)
from sqlalchemy.dialects import postgresql

from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.hygiene_issue import HygieneIssue
from testgen.common.models.profile_result import ProfileResult


@dataclass
class ColumnProfileSummary(EntityMinimal):
    column_name: str
    table_name: str
    general_type: str | None
    functional_data_type: str | None
    datatype_suggestion: str | None
    pii_flag: str | None
    critical_data_element: bool | None
    record_ct: int | None
    null_value_ct: int | None
    distinct_value_ct: int | None
    filled_value_ct: int | None
    dq_score_profiling: float | None
    dq_score_testing: float | None
    anomaly_count: int


class DataColumnChars(Entity):
    __tablename__ = "data_column_chars"

    id: UUID = Column("column_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("data_table_chars.table_id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    ordinal_position: int | None = Column(Integer)
    general_type: str | None = Column(String)
    column_type: str | None = Column(String)
    db_data_type: str | None = Column(String)
    functional_data_type: str | None = Column(String)
    critical_data_element: bool | None = Column(Boolean)
    excluded_data_element: bool | None = Column(Boolean, nullable=True)
    pii_flag: str | None = Column(String(50), nullable=True)
    drop_date: datetime | None = Column(postgresql.TIMESTAMP)
    last_complete_profile_run_id: UUID | None = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float | None = Column(Float)
    dq_score_testing: float | None = Column(Float)

    _default_order_by = (asc(ordinal_position), asc(column_name))

    # Unmapped columns: description, data_source, source_system, source_process,
    # business_domain, stakeholder_group, transform_level, aggregation_level,
    # data_product, add_date, last_mod_date, test_ct, last_test_date,
    # tests_last_run, tests_7_days_prior, tests_30_days_prior, fails_last_run,
    # fails_7_days_prior, fails_30_days_prior, warnings_last_run,
    # warnings_7_days_prior, warnings_30_days_prior, valid_profile_issue_ct,
    # valid_test_issue_ct

    @classmethod
    def list_for_table_group(
        cls,
        *clauses,
        profiling_run_id: UUID | None = None,
        page: int,
        limit: int,
    ) -> tuple[list[ColumnProfileSummary], int]:
        profile_run_filter = (
            ProfileResult.profile_run_id == profiling_run_id
            if profiling_run_id is not None
            else ProfileResult.profile_run_id == cls.last_complete_profile_run_id
        )

        anomaly_subq = (
            select(
                HygieneIssue.profile_run_id.label("profile_run_id"),
                HygieneIssue.schema_name.label("schema_name"),
                HygieneIssue.table_name.label("table_name"),
                HygieneIssue.column_name.label("column_name"),
                func.count().label("anomaly_count"),
            )
            .where(func.coalesce(HygieneIssue.disposition, "Confirmed") == "Confirmed")
            .group_by(
                HygieneIssue.profile_run_id,
                HygieneIssue.schema_name,
                HygieneIssue.table_name,
                HygieneIssue.column_name,
            )
            .subquery()
        )

        query = (
            select(
                cls.column_name,
                cls.table_name,
                cls.general_type,
                cls.functional_data_type,
                ProfileResult.datatype_suggestion,
                cls.pii_flag,
                cls.critical_data_element,
                ProfileResult.record_ct,
                ProfileResult.null_value_ct,
                ProfileResult.distinct_value_ct,
                ProfileResult.filled_value_ct,
                cls.dq_score_profiling,
                cls.dq_score_testing,
                func.coalesce(anomaly_subq.c.anomaly_count, 0).label("anomaly_count"),
            )
            .outerjoin(
                ProfileResult,
                and_(
                    profile_run_filter,
                    ProfileResult.schema_name == cls.schema_name,
                    ProfileResult.table_name == cls.table_name,
                    ProfileResult.column_name == cls.column_name,
                ),
            )
            .outerjoin(
                anomaly_subq,
                and_(
                    anomaly_subq.c.profile_run_id == ProfileResult.profile_run_id,
                    anomaly_subq.c.schema_name == cls.schema_name,
                    anomaly_subq.c.table_name == cls.table_name,
                    anomaly_subq.c.column_name == cls.column_name,
                ),
            )
            .where(cls.drop_date.is_(None), *clauses)
            .order_by(asc(cls.table_name), asc(cls.ordinal_position), asc(cls.column_name))
        )

        return cls._paginate(query, page=page, limit=limit, data_class=ColumnProfileSummary)
