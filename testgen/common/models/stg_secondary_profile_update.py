"""ORM model for the stg_secondary_profile_updates staging table.

Cleaned per-run by `secondary_profiling_delete.sql`; this model exists for
data retention to age out orphans left by failed/interrupted profiling runs.
The PK declared here is cosmetic — only the WHERE columns are needed for the
bulk DELETE. See `staging` package docs in `run_data_cleanup.py` for context.
"""

from datetime import datetime

from sqlalchemy import Column, String
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base


class StgSecondaryProfileUpdate(Base):
    __tablename__ = "stg_secondary_profile_updates"

    project_code: str = Column(String(30), primary_key=True, nullable=False)
    run_date: datetime = Column(postgresql.TIMESTAMP, primary_key=True, nullable=False)
    schema_name: str = Column(String(50), primary_key=True)
    table_name: str = Column(String(120), primary_key=True)
    column_name: str = Column(String(120), primary_key=True)

    @classmethod
    def delete_older_than(cls, cutoff: datetime, project_code: str) -> int:
        return cls.delete_where(cls.run_date < cutoff, cls.project_code == project_code)
