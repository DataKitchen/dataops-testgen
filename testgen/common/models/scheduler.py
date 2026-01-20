from collections.abc import Iterable
from datetime import datetime
from typing import Any, Self
from uuid import UUID, uuid4

import streamlit as st
from cron_converter import Cron
from sqlalchemy import Boolean, Column, String, cast, delete, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.models import Base, get_current_session
from testgen.common.models.entity import ENTITY_HASH_FUNCS
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite

RUN_TESTS_JOB_KEY = "run-tests"
RUN_MONITORS_JOB_KEY = "run-monitors"
RUN_PROFILE_JOB_KEY = "run-profile"


class JobSchedule(Base):
    __tablename__ = "job_schedules"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)

    key: str = Column(String, nullable=False)
    args: list[Any] = Column(postgresql.JSONB, nullable=False, default=[])
    kwargs: dict[str, Any] = Column(postgresql.JSONB, nullable=False, default={})
    cron_expr: str = Column(String, nullable=False)
    cron_tz: str = Column(String, nullable=False)
    active: bool = Column(Boolean, default=True)

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def get(cls, *clauses) -> Self | None:
        query = select(cls).where(*clauses)
        return get_current_session().scalars(query).first()

    @classmethod
    def select_where(cls, *clauses, order_by: str | InstrumentedAttribute | None = None) -> Iterable[Self]:
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
        db_session = get_current_session()
        try:
            db_session.execute(query)
        except ValueError:
            db_session.rollback()
        else:
            db_session.commit()
            cls.clear_cache()

    @classmethod
    def update_active(cls, job_id: str | UUID, active: bool) -> None:
        query = update(cls).where(JobSchedule.id == job_id).values(active=active)
        db_session = get_current_session()
        try:
            db_session.execute(query)
        except ValueError:
            db_session.rollback()
        else:
            db_session.commit()
            cls.clear_cache()

    @classmethod
    def count(cls):
        return get_current_session().query(cls).count()
    
    @classmethod
    def clear_cache(cls) -> None:
        cls.get.clear()

    def get_sample_triggering_timestamps(self, n=3) -> list[datetime]:
        schedule = Cron(cron_string=self.cron_expr).schedule(timezone_str=self.cron_tz)
        return [schedule.next() for _ in range(n)]

    @property
    def cron_tz_str(self) -> str:
        return self.cron_tz.replace("_", " ")
    
    def save(self) -> None:
        db_session = get_current_session()
        db_session.add(self)
        db_session.commit()
        self.__class__.clear_cache()
