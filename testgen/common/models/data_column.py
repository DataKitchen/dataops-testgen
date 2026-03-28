from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, ForeignKey, String, asc
from sqlalchemy.dialects import postgresql

from testgen.common.models.entity import Entity


class DataColumnChars(Entity):
    __tablename__ = "data_column_chars"

    id: UUID = Column("column_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    excluded_data_element: bool | None = Column(Boolean, nullable=True)
    pii_flag: str | None = Column(String(50), nullable=True)

    _default_order_by = (asc(id),)

    # Unmapped columns: table_id, ordinal_position, general_type, column_type,
    # db_data_type, functional_data_type, description, critical_data_element,
    # data_source, source_system, source_process, business_domain,
    # stakeholder_group, transform_level, aggregation_level, data_product,
    # add_date, last_mod_date, drop_date, test_ct, last_test_date,
    # tests_last_run, tests_7_days_prior, tests_30_days_prior,
    # fails_last_run, fails_7_days_prior, fails_30_days_prior,
    # warnings_last_run, warnings_7_days_prior, warnings_30_days_prior,
    # last_complete_profile_run_id, valid_profile_issue_ct,
    # valid_test_issue_ct, dq_score_profiling, dq_score_testing
