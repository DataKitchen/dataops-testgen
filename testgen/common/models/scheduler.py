from collections.abc import Iterable
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from cron_converter import Cron
from sqlalchemy import Column, String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.models import Base, get_current_session


class JobSchedule(Base):
    __tablename__ = "job_schedules"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)

    key: str = Column(String, nullable=False)
    args: list[Any] = Column(postgresql.JSONB, nullable=False, default=[])
    kwargs: dict[str, Any] = Column(postgresql.JSONB, nullable=False, default={})
    cron_expr: str = Column(String, nullable=False)
    cron_tz: str = Column(String, nullable=False)

    @classmethod
    def select_where(cls, *clauses, order_by: str | InstrumentedAttribute | None = None) -> Iterable[Self]:
        query = select(cls).where(*clauses).order_by(order_by)
        return get_current_session().execute(query)

    @classmethod
    def count(cls):
        return get_current_session().query(cls).count()

    def get_sample_triggering_timestamps(self, n=3) -> list[datetime]:
        schedule = Cron(cron_string=self.cron_expr).schedule(timezone_str=self.cron_tz)
        return [schedule.next() for _ in range(n)]

    @property
    def cron_tz_str(self) -> str:
        return self.cron_tz.replace("_", " ")
