"""ORM model for the stg_functional_table_updates staging table.

Unlike the other staging tables, this one has no per-run delete anywhere in
the codebase — rows accumulate indefinitely. Data retention is the primary
cleanup. PK declared is cosmetic; only WHERE columns are needed for bulk DELETE.
"""

from datetime import datetime

from sqlalchemy import Column, String
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base


class StgFunctionalTableUpdate(Base):
    __tablename__ = "stg_functional_table_updates"

    project_code: str = Column(String(30), primary_key=True, nullable=False)
    run_date: datetime = Column(postgresql.TIMESTAMP, primary_key=True, nullable=False)
    schema_name: str = Column(String(50), primary_key=True)
    table_name: str = Column(String(120), primary_key=True)

    @classmethod
    def delete_older_than(cls, cutoff: datetime, project_code: str) -> int:
        return cls.delete_where(cls.run_date < cutoff, cls.project_code == project_code)
