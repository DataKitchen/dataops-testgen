from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NamedTuple, Self, TypedDict
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, String, Text, desc, func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import case

from testgen.common.models import get_current_session
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.test_result import TestResultStatus
from testgen.common.models.test_suite import TestSuite
from testgen.utils import is_uuid4

TestRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]
ProgressKey = Literal["data_chars", "validation", "QUERY", "CAT", "METADATA"]
ProgressStatus = Literal["Pending", "Running", "Completed", "Warning"]

class ProgressStep(TypedDict):
    key: ProgressKey
    status: ProgressStatus
    label: str
    detail: str
    error: str


@dataclass
class TestRunMinimal(EntityMinimal):
    id: UUID
    project_code: str
    table_groups_id: UUID
    test_suite_id: UUID
    test_suite: str
    test_starttime: datetime
    dq_score_test_run: float
    is_latest_run: bool


@dataclass
class TestRunSummary(EntityMinimal):
    test_run_id: UUID
    test_starttime: datetime
    test_endtime: datetime
    table_groups_name: str
    test_suite: str
    project_name: str
    status: TestRunStatus
    progress: list[ProgressStep]
    process_id: int
    log_message: str
    test_ct: int
    passed_ct: int
    warning_ct: int
    failed_ct: int
    error_ct: int
    log_ct: int
    dismissed_ct: int
    dq_score_testing: float

class LatestTestRun(NamedTuple):
    id: str
    run_time: datetime


class TestRun(Entity):
    __tablename__ = "test_runs"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, nullable=False, default=uuid4)
    test_suite_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("test_suites.id"), nullable=False)
    test_starttime: datetime = Column(postgresql.TIMESTAMP)
    test_endtime: datetime = Column(postgresql.TIMESTAMP)
    status: TestRunStatus = Column(String, default="Running")
    progress: list[ProgressStep] = Column(postgresql.JSONB, default=[])
    log_message: str = Column(Text)
    test_ct: int = Column(Integer)
    passed_ct: int = Column(Integer)
    failed_ct: int = Column(Integer)
    warning_ct: int = Column(Integer)
    error_ct: int = Column(Integer)
    log_ct: int = Column(Integer)
    table_ct: int = Column(Integer)
    column_ct: int = Column(Integer)
    column_failed_ct: int = Column(Integer)
    column_warning_ct: int = Column(Integer)
    dq_affected_data_points: int = Column(BigInteger)
    dq_total_data_points: int = Column(BigInteger)
    dq_score_test_run: float = Column(Float)
    process_id: int = Column(Integer)

    _default_order_by = (desc(test_starttime),)
    _minimal_columns = (
        id,
        TestSuite.project_code,
        TestSuite.table_groups_id,
        TestSuite.id.label("test_suite_id"),
        TestSuite.test_suite,
        test_starttime,
        dq_score_test_run,
        case(
            (id == TestSuite.last_complete_test_run_id, True),
            else_=False,
        ).label("is_latest_run"),
    )

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, run_id: str | UUID) -> TestRunMinimal | None:
        if not is_uuid4(run_id):
            return None

        query = select(cls._minimal_columns).join(TestSuite).where(cls.id == run_id)
        result = get_current_session().execute(query).first()
        return TestRunMinimal(**result) if result else None

    @classmethod
    def get_latest_run(cls, project_code: str) -> LatestTestRun | None:
        query = (
            select(TestRun.id, TestRun.test_starttime)
            .join(TestSuite)
            .where(TestSuite.project_code == project_code, TestRun.status == "Complete")
            .order_by(desc(TestRun.test_starttime))
            .limit(1)
        )
        result = get_current_session().execute(query).first()
        if result:
            return LatestTestRun(str(result["id"]), result["test_starttime"])
        return None

    def get_previous(self) -> Self | None:
        query = (
            select(TestRun)
            .join(TestSuite)
            .where(
                TestRun.test_suite_id == self.test_suite_id,
                TestRun.status == "Complete",
                TestRun.test_starttime < self.test_starttime,
            )
            .order_by(desc(TestRun.test_starttime))
            .limit(1)
        )
        return get_current_session().scalar(query)

    @property
    def ct_by_status(self):
        return {
            TestResultStatus.Error: self.error_ct,
            TestResultStatus.Failed: self.failed_ct,
            TestResultStatus.Warning: self.warning_ct,
            TestResultStatus.Log: self.log_ct,
            TestResultStatus.Passed: self.passed_ct,
        }

    @classmethod
    @st.cache_data(show_spinner=False)
    def select_summary(
        cls,
        project_code: str | None = None,
        table_group_id: str | None = None,
        test_suite_id: str | None = None,
        test_run_ids: list[str] | None = None,
    ) -> Iterable[TestRunSummary]:
        if (
            (table_group_id and not is_uuid4(table_group_id))
            or (test_suite_id and not is_uuid4(test_suite_id))
            or (test_run_ids and not all(is_uuid4(run_id) for run_id in test_run_ids))
        ):
            return []

        query = f"""
        WITH run_results AS (
            SELECT test_run_id,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                        AND result_status = 'Passed' THEN 1
                        ELSE 0
                    END
                ) AS passed_ct,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                        AND result_status = 'Warning' THEN 1
                        ELSE 0
                    END
                ) AS warning_ct,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                        AND result_status = 'Failed' THEN 1
                        ELSE 0
                    END
                ) AS failed_ct,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                        AND result_status = 'Error' THEN 1
                        ELSE 0
                    END
                ) AS error_ct,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') = 'Confirmed'
                        AND result_status = 'Log' THEN 1
                        ELSE 0
                    END
                ) AS log_ct,
                SUM(
                    CASE
                        WHEN COALESCE(disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                        ELSE 0
                    END
                ) AS dismissed_ct
            FROM test_results
            GROUP BY test_run_id
        )
        SELECT test_runs.id AS test_run_id,
            test_runs.test_starttime,
            test_runs.test_endtime,
            table_groups.table_groups_name,
            test_suites.test_suite,
            projects.project_name,
            test_runs.status,
            test_runs.progress,
            test_runs.process_id,
            test_runs.log_message,
            test_runs.test_ct,
            run_results.passed_ct,
            run_results.warning_ct,
            run_results.failed_ct,
            run_results.error_ct,
            run_results.log_ct,
            run_results.dismissed_ct,
            test_runs.dq_score_test_run AS dq_score_testing
        FROM test_runs
            LEFT JOIN run_results ON (test_runs.id = run_results.test_run_id)
            INNER JOIN test_suites ON (test_runs.test_suite_id = test_suites.id)
            INNER JOIN table_groups ON (test_suites.table_groups_id = table_groups.id)
            INNER JOIN projects ON (test_suites.project_code = projects.project_code)
        WHERE TRUE
            {" AND test_suites.project_code = :project_code" if project_code else ""}
            {" AND test_suites.table_groups_id = :table_group_id" if table_group_id else ""}
            {" AND test_suites.id = :test_suite_id" if test_suite_id else ""}
            {" AND test_runs.id IN :test_run_ids" if test_run_ids else ""}
        ORDER BY test_runs.test_starttime DESC;
        """
        params = {
            "project_code": project_code,
            "table_group_id": table_group_id,
            "test_suite_id": test_suite_id,
            "test_run_ids": tuple(test_run_ids or []),
        }
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TestRunSummary(**row) for row in results]

    @classmethod
    def has_running_process(cls, ids: list[str]) -> bool:
        query = select(func.count(cls.id)).where(cls.id.in_(ids), cls.status == "Running")
        process_count = get_current_session().execute(query).scalar()
        return process_count > 0

    @classmethod
    def cancel_all_running(cls) -> list[UUID]:
        query = (
            update(cls)
            .where(cls.status == "Running")
            .values(status="Cancelled", test_endtime=datetime.now(UTC))
            .returning(cls.id)
        )
        db_session = get_current_session()
        rows = db_session.execute(query)
        db_session.commit()
        cls.clear_cache()
        return [r.id for r in rows]

    @classmethod
    def cancel_run(cls, run_id: str | UUID) -> None:
        query = update(cls).where(cls.id == run_id).values(status="Cancelled", test_endtime=datetime.now(UTC))
        db_session = get_current_session()
        db_session.execute(query)
        db_session.commit()
        cls.clear_cache()

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        query = """
        DELETE FROM test_results
        WHERE test_run_id IN :test_run_ids;
        """
        db_session = get_current_session()
        db_session.execute(text(query), {"test_run_ids": tuple(ids)})
        db_session.commit()
        cls.delete_where(cls.id.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_minimal.clear()
        cls.select_summary.clear()

    def init_progress(self) -> None:
        self._progress = {
            "data_chars": {"label": "Refreshing data catalog"},
            "validation": {"label": "Validating test definitions"},
            "QUERY": {"label": "Running query tests"},
            "CAT": {"label": "Running aggregated tests"},
            "METADATA": {"label": "Running metadata tests"},
        }
        for key in self._progress:
            self._progress[key].update({"key": key, "status": "Pending"})

    def set_progress(self, key: ProgressKey, status: ProgressStatus, detail: str | None = None, error: str | None = None) -> None:
        self._progress[key]["status"] = status
        if detail:
            self._progress[key]["detail"] = detail
        if error:
            self._progress[key]["error"] = error

        self.progress = list(self._progress.values())
        flag_modified(self, "progress")
