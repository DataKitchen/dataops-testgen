from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal, NamedTuple, Self, TypedDict
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import BigInteger, Column, Float, Integer, String, desc, func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import case

from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.common.models.job_execution import JobExecution, JobStatus
from testgen.common.models.project import Project
from testgen.common.models.table_group import TableGroup
from testgen.utils import is_uuid4

ProfilingRunStatus = Literal["Running", "Complete", "Error", "Cancelled"]
ProgressKey = Literal["data_chars", "col_profiling", "freq_analysis", "hygiene_issues"]
ProgressStatus = Literal["Pending", "Running", "Completed", "Warning"]

class ProgressStep(TypedDict):
    key: ProgressKey
    status: ProgressStatus
    label: str
    detail: str
    error: str

@dataclass
class ProfilingRunMinimal(EntityMinimal):
    id: UUID
    project_code: str
    table_groups_id: UUID
    table_groups_name: str
    table_group_schema: str
    profiling_starttime: datetime
    dq_score_profiling: float
    is_latest_run: bool


@dataclass
class ProfilingRunSummary(EntityMinimal):
    job_execution_id: UUID
    profiling_run_id: UUID | None
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    progress: list[ProgressStep]
    table_groups_name: str | None
    table_group_schema: str | None
    process_id: int | None
    log_message: str | None
    table_ct: int | None
    column_ct: int | None
    record_ct: int | None
    data_point_ct: int | None
    anomaly_ct: int | None
    anomalies_definite_ct: int | None
    anomalies_likely_ct: int | None
    anomalies_possible_ct: int | None
    anomalies_dismissed_ct: int | None
    dq_score_profiling: float | None
    total_count: int

    STATUS_LABEL: ClassVar[dict[str, str]] = {
        JobStatus.COMPLETED: "Completed",
        JobStatus.CANCELED: "Canceled",
        JobStatus.CANCEL_REQUESTED: "Canceling",
        JobStatus.PENDING: "Pending",
        JobStatus.CLAIMED: "Starting",
        JobStatus.RUNNING: "Running",
        JobStatus.ERROR: "Error",
    }

    @property
    def status_label(self) -> str:
        return self.STATUS_LABEL.get(self.status, self.status)


class LatestProfilingRun(NamedTuple):
    id: str
    run_time: datetime


class ProfilingRun(Entity):
    __tablename__ = "profiling_runs"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String, nullable=False)
    connection_id: str = Column(BigInteger, nullable=False)
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), nullable=False)
    profiling_starttime: datetime = Column(postgresql.TIMESTAMP)
    profiling_endtime: datetime = Column(postgresql.TIMESTAMP)
    status: ProfilingRunStatus = Column(String, default="Running")
    progress: list[ProgressStep] = Column(postgresql.JSONB, default=[])
    log_message: str = Column(String)
    table_ct: int = Column(BigInteger)
    column_ct: int = Column(BigInteger)
    record_ct: int = Column(BigInteger)
    data_point_ct: int = Column(BigInteger)
    anomaly_ct: int = Column(BigInteger)
    anomaly_table_ct: int = Column(BigInteger)
    anomaly_column_ct: int = Column(BigInteger)
    dq_affected_data_points: int = Column(BigInteger)
    dq_total_data_points: int = Column(BigInteger)
    dq_score_profiling: float = Column(Float)
    process_id: int = Column(Integer)
    job_execution_id: UUID | None = Column(postgresql.UUID(as_uuid=True), nullable=True)

    _default_order_by = (desc(profiling_starttime),)
    _minimal_columns = (
        id,
        project_code,
        table_groups_id,
        TableGroup.table_groups_name,
        TableGroup.table_group_schema,
        profiling_starttime,
        dq_score_profiling,
        case(
            (id == TableGroup.last_complete_profile_run_id, True),
            else_=False,
        ).label("is_latest_run"),
    )

    @classmethod
    def get_by_id_or_job(cls, identifier: UUID) -> Self | None:
        """Look up a profiling run by its own ID or by job_execution_id."""
        query = select(cls).where((cls.id == identifier) | (cls.job_execution_id == identifier))
        return get_current_session().scalars(query).first()

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, run_id: str | UUID) -> ProfilingRunMinimal | None:
        if not is_uuid4(run_id):
            return None

        query = (
            select(*cls._minimal_columns)
            .join(TableGroup, cls.table_groups_id == TableGroup.id)
            .where((cls.id == run_id) | (cls.job_execution_id == run_id))
        )
        result = get_current_session().execute(query).mappings().first()
        return ProfilingRunMinimal(**result) if result else None

    @classmethod
    def get_latest_run(cls, project_code: str) -> LatestProfilingRun | None:
        query = (
            select(ProfilingRun.id, JobExecution.started_at.label("run_time"))
            .join(JobExecution, ProfilingRun.job_execution_id == JobExecution.id)
            .where(ProfilingRun.project_code == project_code, JobExecution.status == JobStatus.COMPLETED)
            .order_by(desc(JobExecution.started_at))
            .limit(1)
        )
        result = get_current_session().execute(query).mappings().first()
        if result:
            return LatestProfilingRun(str(result["id"]), result["run_time"])
        return None

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[ProfilingRunMinimal]:
        query = (
            select(*cls._minimal_columns)
            .join(TableGroup, cls.table_groups_id == TableGroup.id)
            .where(*clauses)
            .order_by(*order_by)
        )
        results = get_current_session().execute(query).mappings().all()
        return [ProfilingRunMinimal(**row) for row in results]

    @classmethod
    def select_summary(
        cls,
        project_code: str,
        table_group_id: str | UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ProfilingRunSummary], int]:
        if table_group_id and not is_uuid4(table_group_id):
            return [], 0

        query = f"""
        WITH profile_anomalies AS (
            SELECT profile_anomaly_results.profile_run_id,
                SUM(CASE WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood = 'Definite' THEN 1 ELSE 0 END) AS definite_ct,
                SUM(CASE WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood = 'Likely' THEN 1 ELSE 0 END) AS likely_ct,
                SUM(CASE WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                    AND profile_anomaly_types.issue_likelihood IN ('Possible', 'Potential PII')
                    THEN 1 ELSE 0 END) AS possible_ct,
                SUM(CASE WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed')
                    IN ('Dismissed', 'Inactive') THEN 1 ELSE 0 END) AS dismissed_ct
            FROM profile_anomaly_results
                LEFT JOIN profile_anomaly_types
                    ON profile_anomaly_types.id = profile_anomaly_results.anomaly_id
            GROUP BY profile_anomaly_results.profile_run_id
        )
        SELECT
            je.id AS job_execution_id,
            pr.id AS profiling_run_id,
            je.status,
            je.created_at,
            je.started_at,
            je.completed_at,
            je.error_message,
            COALESCE(pr.progress, '[]'::jsonb) AS progress,
            tg.table_groups_name,
            tg.table_group_schema,
            pr.process_id,
            pr.log_message,
            pr.table_ct,
            pr.column_ct,
            pr.record_ct,
            pr.data_point_ct,
            pr.anomaly_ct,
            pa.definite_ct AS anomalies_definite_ct,
            pa.likely_ct AS anomalies_likely_ct,
            pa.possible_ct AS anomalies_possible_ct,
            pa.dismissed_ct AS anomalies_dismissed_ct,
            pr.dq_score_profiling,
            COUNT(*) OVER() AS total_count
        FROM job_executions je
            LEFT JOIN profiling_runs pr ON pr.job_execution_id = je.id
            LEFT JOIN table_groups tg ON tg.id = pr.table_groups_id
            LEFT JOIN profile_anomalies pa ON pa.profile_run_id = pr.id
        WHERE je.job_key = 'run-profile'
            AND je.project_code = :project_code
            {" AND tg.id = :table_group_id" if table_group_id else ""}
        ORDER BY je.created_at DESC
        LIMIT :limit OFFSET :offset;
        """
        params = {
            "project_code": project_code,
            "table_group_id": table_group_id,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        items = [ProfilingRunSummary(**row) for row in results]
        total = items[0].total_count if items else 0
        return items, total

    _ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.CLAIMED, JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED)

    @classmethod
    def has_active_job_for(cls, entity_cls: type[Entity], *entity_ids: str | int | UUID) -> bool:
        """Check whether any active profiling job exists for the given entity or entities."""
        query = (
            select(func.count(cls.id))
            .join(JobExecution, cls.job_execution_id == JobExecution.id)
            .where(JobExecution.status.in_(cls._ACTIVE_JOB_STATUSES))
        )
        if entity_cls is cls:
            query = query.where(cls.id.in_(entity_ids))
        elif entity_cls is TableGroup:
            query = query.where(cls.table_groups_id.in_(entity_ids))
        elif entity_cls is Connection:
            query = query.where(cls.connection_id.in_(entity_ids))
        elif entity_cls is Project:
            query = query.where(cls.project_code.in_(entity_ids))
        else:
            raise ValueError(f"Unsupported entity: {entity_cls.__name__}")
        return get_current_session().execute(query).scalar() > 0

    @classmethod
    def cancel_run(cls, run_id: str | UUID) -> None:
        query = update(cls).where(cls.id == run_id).values(status="Cancelled", profiling_endtime=datetime.now(UTC))
        db_session = get_current_session()
        db_session.execute(query)

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        query = """
        DELETE FROM profile_pair_rules
        WHERE profile_run_id IN :profiling_run_ids;

        DELETE FROM profile_anomaly_results
        WHERE profile_run_id IN :profiling_run_ids;

        DELETE FROM profile_results
        WHERE profile_run_id IN :profiling_run_ids;

        DELETE FROM job_executions
        WHERE id IN (
            SELECT job_execution_id FROM profiling_runs
            WHERE id IN :profiling_run_ids AND job_execution_id IS NOT NULL
        );
        """
        db_session = get_current_session()
        db_session.execute(text(query), {"profiling_run_ids": tuple(ids)})
        cls.delete_where(cls.id.in_(ids))

    def init_progress(self) -> None:
        self._progress = {
            "data_chars": {"label": "Refreshing data catalog"},
            "col_profiling": {"label": "Profiling columns"},
            "freq_analysis": {"label": "Running frequency analysis"},
            "hygiene_issues": {"label": "Detecting hygiene issues"},
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

    def get_previous(self) -> Self | None:
        query = (
            select(ProfilingRun)
            .join(JobExecution, ProfilingRun.job_execution_id == JobExecution.id)
            .where(
                ProfilingRun.table_groups_id == self.table_groups_id,
                JobExecution.status == JobStatus.COMPLETED,
                JobExecution.started_at < self.profiling_starttime,
            )
            .order_by(desc(JobExecution.started_at))
            .limit(1)
        )
        return get_current_session().scalar(query)
