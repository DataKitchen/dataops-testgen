"""ORM model for the stg_functional_table_updates staging table.

Each profiling run stages under its own `profile_run_id` and deletes that key
when it finishes, via `delete_staging_functional_tables.sql`; this model exists
for data retention to age out orphans left by failed/interrupted profiling runs.
PK declared is cosmetic; only WHERE columns are needed for bulk DELETE.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, String
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base


class StgFunctionalTableUpdate(Base):
    __tablename__ = "stg_functional_table_updates"

    project_code: str = Column(String(30), primary_key=True, nullable=False)
    run_date: datetime = Column(postgresql.TIMESTAMP, primary_key=True, nullable=False)
    schema_name: str = Column(String(50), primary_key=True)
    table_name: str = Column(String(120), primary_key=True)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True)

    @classmethod
    def delete_older_than(cls, cutoff: datetime, project_code: str) -> int:
        return cls.delete_where(cls.run_date < cutoff, cls.project_code == project_code)
