from collections.abc import Iterable
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

from cron_converter import Cron
from sqlalchemy import Boolean, Column, String, cast, delete, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.enums import JobKey
from testgen.common.models import Base, get_current_session
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite

RUN_TESTS_JOB_KEY = "run-tests"
RUN_MONITORS_JOB_KEY = "run-monitors"
RUN_PROFILE_JOB_KEY = "run-profile"

SCHEDULABLE_JOB_KEYS: frozenset[JobKey] = frozenset({JobKey.run_profile, JobKey.run_tests})


class JobSchedule(Base):
    __tablename__ = "job_schedules"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)

    key: str = Column(String, nullable=False)
    kwargs: dict[str, Any] = Column(postgresql.JSONB, nullable=False, default={})
    cron_expr: str = Column(String, nullable=False)
    cron_tz: str = Column(String, nullable=False)
    active: bool = Column(Boolean, default=True)

    @classmethod
    def get(cls, *clauses) -> Self | None:
        query = select(cls).where(*clauses)
        return get_current_session().scalars(query).first()

    @classmethod
    def select_where(cls, *clauses, order_by: str | InstrumentedAttribute | None = None) -> Iterable[Self]:
        query = select(cls).where(*clauses)
        if order_by is not None:
            query = query.order_by(order_by)
        return get_current_session().scalars(query).all()

    @classmethod
    def select_runnable(cls, *clauses, order_by: str | InstrumentedAttribute | None = None) -> Iterable[Self]:
        """Schedules the scheduler should dispatch: active rows, and (for test/monitor runs)
        only when the linked test suite has at least one test definition.
        """
        test_job_keys = [RUN_TESTS_JOB_KEY, RUN_MONITORS_JOB_KEY]
        test_definitions_count = (
            select(cls.id)
            .join(TestSuite, TestSuite.id == cast(cls.kwargs["test_suite_id"].astext, postgresql.UUID))
            .join(TestDefinition, TestDefinition.test_suite_id == TestSuite.id)
            .where(cls.key.in_(test_job_keys), cls.active == True)
            .group_by(cls.id, TestSuite.id)
            .having(func.count(TestDefinition.id) > 0)
            .subquery()
        )
        test_runs_query = (
            select(cls)
            .join(test_definitions_count, test_definitions_count.c.id == cls.id)
            .where(*clauses)
        )
        non_test_runs_query = select(cls).where(cls.key.not_in(test_job_keys), cls.active == True, *clauses)
        query = test_runs_query.union_all(non_test_runs_query).order_by(order_by)

        return get_current_session().execute(query)

    @classmethod
    def delete(cls, job_id: str | UUID) -> None:
        query = delete(cls).where(JobSchedule.id == job_id)
        get_current_session().execute(query)

    @classmethod
    def update_active(cls, job_id: str | UUID, active: bool) -> None:
        query = update(cls).where(JobSchedule.id == job_id).values(active=active)
        get_current_session().execute(query)

    @classmethod
    def count(cls):
        return get_current_session().query(cls).count()

    @classmethod
    def list_for_project(
        cls,
        project_code: str,
        *extra_filters,
        key_filter: Iterable[JobKey] | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Self], int]:
        """List schedules for a project with optional key filter and pagination.

        Returns both active and paused rows. Defaults ``key_filter`` to
        ``SCHEDULABLE_JOB_KEYS`` (``run_profile``, ``run_tests``); pass an explicit
        ``key_filter`` to include other kinds.
        """
        session = get_current_session()
        keys = list(key_filter) if key_filter is not None else list(SCHEDULABLE_JOB_KEYS)
        query = select(cls).where(cls.project_code == project_code, cls.key.in_(keys), *extra_filters)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        items = session.scalars(query.order_by(cls.key, cls.id).offset((page - 1) * limit).limit(limit)).all()
        return list(items), total or 0

    @classmethod
    def select_active_by_kwargs(
        cls,
        project_code: str,
        key: str,
        kwargs_match: dict[str, str | list[str]],
    ) -> list[Self]:
        """Find active schedules whose ``kwargs`` JSONB matches the given (key, value) pairs.

        Values may be a single string or a list of strings (which becomes an ``IN`` filter).
        """
        query = select(cls).where(
            cls.project_code == project_code,
            cls.key == key,
            cls.active.is_(True),
        )
        for k, v in kwargs_match.items():
            if isinstance(v, list):
                if not v:
                    return []
                query = query.where(cls.kwargs[k].astext.in_([str(x) for x in v]))
            else:
                query = query.where(cls.kwargs[k].astext == str(v))
        return list(get_current_session().scalars(query).all())
    
    def get_sample_triggering_timestamps(self, n=3) -> list[datetime]:
        schedule = Cron(cron_string=self.cron_expr).schedule(timezone_str=self.cron_tz)
        return [schedule.next() for _ in range(n)]

    @property
    def cron_tz_str(self) -> str:
        return self.cron_tz.replace("_", " ")
    
    def save(self) -> None:
        db_session = get_current_session()
        db_session.add(self)
