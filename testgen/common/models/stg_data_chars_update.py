"""ORM model for the stg_data_chars_updates staging table.

Each refresh stages under its own `refresh_id` and deletes that key when it
finishes, via `data_chars_staging_delete.sql`; this model exists for data
retention to age out orphans left by failed/interrupted profiling runs.
Has no project_code column — project scope is enforced via a subquery on
table_groups. PK declared is cosmetic; only WHERE columns are needed for
bulk DELETE.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, String, select
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base
from testgen.common.models.table_group import TableGroup


class StgDataCharsUpdate(Base):
    __tablename__ = "stg_data_chars_updates"

    refresh_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)
    run_date: datetime = Column(postgresql.TIMESTAMP, primary_key=True, nullable=False)
    schema_name: str = Column(String(120), primary_key=True)
    table_name: str = Column(String(120), primary_key=True)
    column_name: str = Column(String(120), primary_key=True)

    @classmethod
    def delete_older_than(cls, cutoff: datetime, project_code: str) -> int:
        project_table_groups = select(TableGroup.id).where(TableGroup.project_code == project_code)
        return cls.delete_where(cls.run_date < cutoff, cls.table_groups_id.in_(project_table_groups))
