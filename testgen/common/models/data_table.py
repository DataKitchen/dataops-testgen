from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, ForeignKey, String, asc, func, select
from sqlalchemy.dialects import postgresql

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity
from testgen.common.models.table_group import TableGroup


class DataTable(Entity):
    __tablename__ = "data_table_chars"

    id: UUID = Column("table_id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    table_name: str = Column(String)
    column_ct: int = Column(BigInteger)

    # Unmapped columns: schema_name, functional_table_type, description,
    # critical_data_element, data_source, source_system, source_process,
    # business_domain, stakeholder_group, transform_level, aggregation_level,
    # data_product, add_date, drop_date, last_refresh_date, approx_record_ct,
    # record_ct, last_complete_profile_run_id, last_profile_record_ct,
    # dq_score_profiling, dq_score_testing

    @classmethod
    def select_table_names(
        cls, table_groups_id: UUID, project_codes: list[str] | None = None, limit: int = 100, offset: int = 0,
    ) -> list[str]:
        query = select(cls.table_name).where(cls.table_groups_id == table_groups_id)
        if project_codes is not None:
            query = query.join(TableGroup, cls.table_groups_id == TableGroup.id).where(
                TableGroup.project_code.in_(project_codes)
            )
        query = query.order_by(asc(func.lower(cls.table_name))).offset(offset).limit(limit)
        return list(get_current_session().scalars(query).all())

    @classmethod
    def count_tables(cls, table_groups_id: UUID, project_codes: list[str] | None = None) -> int:
        query = select(func.count()).select_from(cls).where(cls.table_groups_id == table_groups_id)
        if project_codes is not None:
            query = query.join(TableGroup, cls.table_groups_id == TableGroup.id).where(
                TableGroup.project_code.in_(project_codes)
            )
        return get_current_session().scalar(query) or 0
