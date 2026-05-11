"""ORM model for the stg_test_definition_updates staging table.

Cleaned per-run by `delete_staging_test_definitions.sql`; this model exists
for data retention to age out orphans left by failed/interrupted prediction
runs. Has no project_code column — project scope is enforced via a subquery
on test_suites. PK declared is cosmetic; only WHERE columns are needed for
bulk DELETE.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, select
from sqlalchemy.dialects import postgresql

from testgen.common.models import Base
from testgen.common.models.test_suite import TestSuite


class StgTestDefinitionUpdate(Base):
    __tablename__ = "stg_test_definition_updates"

    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)
    test_definition_id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False)
    run_date: datetime = Column(postgresql.TIMESTAMP, primary_key=True, nullable=False)

    @classmethod
    def delete_older_than(cls, cutoff: datetime, project_code: str) -> int:
        project_test_suites = select(TestSuite.id).where(TestSuite.project_code == project_code)
        return cls.delete_where(cls.run_date < cutoff, cls.test_suite_id.in_(project_test_suites))
