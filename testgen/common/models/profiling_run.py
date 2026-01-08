from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, NamedTuple, Self, TypedDict
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import BigInteger, Column, Float, Integer, String, desc, func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.sql.expression import case

from testgen.common.models import get_current_session
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
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
    id: UUID
    profiling_starttime: datetime
    profiling_endtime: datetime
    table_groups_name: str
    status: ProfilingRunStatus
    progress: list[ProgressStep]
    process_id: int
    log_message: str
    table_group_schema: str
    table_ct: int
    column_ct: int
    record_ct: int
    data_point_ct: int
    anomaly_ct: int
    anomalies_definite_ct: int
    anomalies_likely_ct: int
    anomalies_possible_ct: int
    anomalies_dismissed_ct: int
    dq_score_profiling: float


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
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, run_id: str | UUID) -> ProfilingRunMinimal | None:
        if not is_uuid4(run_id):
            return None

        query = (
            select(cls._minimal_columns).join(TableGroup, cls.table_groups_id == TableGroup.id).where(cls.id == run_id)
        )
        result = get_current_session().execute(query).first()
        return ProfilingRunMinimal(**result) if result else None

    @classmethod
    def get_latest_run(cls, project_code: str) -> LatestProfilingRun | None:
        query = (
            select(ProfilingRun.id, ProfilingRun.profiling_starttime)
            .where(ProfilingRun.project_code == project_code, ProfilingRun.status == "Complete")
            .order_by(desc(ProfilingRun.profiling_starttime))
            .limit(1)
        )
        result = get_current_session().execute(query).first()
        if result:
            return LatestProfilingRun(str(result["id"]), result["profiling_starttime"])
        return None

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[ProfilingRunMinimal]:
        query = (
            select(cls._minimal_columns)
            .join(TableGroup, cls.table_groups_id == TableGroup.id)
            .where(*clauses)
            .order_by(*order_by)
        )
        results = get_current_session().execute(query).all()
        return [ProfilingRunMinimal(**row) for row in results]

    @classmethod
    @st.cache_data(show_spinner=False)
    def select_summary(
        cls,
        project_code: str,
        table_group_id: str | UUID | None = None,
        profiling_run_ids: list[str|UUID] | None = None,
    ) -> Iterable[ProfilingRunSummary]:
        if (table_group_id and not is_uuid4(table_group_id)) or (
            profiling_run_ids and not all(is_uuid4(run_id) for run_id in profiling_run_ids)
        ):
            return []

        query = f"""
        WITH profile_anomalies AS (
            SELECT profile_anomaly_results.profile_run_id,
                SUM(
                    CASE
                        WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                        AND profile_anomaly_types.issue_likelihood = 'Definite' THEN 1
                        ELSE 0
                    END
                ) AS definite_ct,
                SUM(
                    CASE
                        WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                        AND profile_anomaly_types.issue_likelihood = 'Likely' THEN 1
                        ELSE 0
                    END
                ) AS likely_ct,
                SUM(
                    CASE
                        WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') = 'Confirmed'
                        AND profile_anomaly_types.issue_likelihood IN ('Possible', 'Potential PII') THEN 1
                        ELSE 0
                    END
                ) AS possible_ct,
                SUM(
                    CASE
                        WHEN COALESCE(profile_anomaly_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                        ELSE 0
                    END
                ) AS dismissed_ct
            FROM profile_anomaly_results
                LEFT JOIN profile_anomaly_types ON (
                    profile_anomaly_types.id = profile_anomaly_results.anomaly_id
                )
            GROUP BY profile_anomaly_results.profile_run_id
        )
        SELECT profiling_runs.id,
            profiling_runs.profiling_starttime,
            profiling_runs.profiling_endtime,
            table_groups.table_groups_name,
            profiling_runs.status,
            profiling_runs.progress,
            profiling_runs.process_id,
            profiling_runs.log_message,
            table_groups.table_group_schema,
            profiling_runs.table_ct,
            profiling_runs.column_ct,
            profiling_runs.record_ct,
            profiling_runs.data_point_ct,
            profiling_runs.anomaly_ct,
            profile_anomalies.definite_ct AS anomalies_definite_ct,
            profile_anomalies.likely_ct AS anomalies_likely_ct,
            profile_anomalies.possible_ct AS anomalies_possible_ct,
            profile_anomalies.dismissed_ct AS anomalies_dismissed_ct,
            profiling_runs.dq_score_profiling
        FROM profiling_runs
            LEFT JOIN table_groups ON (profiling_runs.table_groups_id = table_groups.id)
            LEFT JOIN profile_anomalies ON (profiling_runs.id = profile_anomalies.profile_run_id)
        WHERE profiling_runs.project_code = :project_code
            {"AND profiling_runs.table_groups_id = :table_group_id" if table_group_id else ""}
            {"AND profiling_runs.id IN :profiling_run_ids" if profiling_run_ids else ""}
        ORDER BY profiling_starttime DESC;
        """
        params = {
            "project_code": project_code,
            "table_group_id": table_group_id,
            "profiling_run_ids": tuple(profiling_run_ids or []),
        }
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [ProfilingRunSummary(**row) for row in results]

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
            .values(status="Cancelled", profiling_endtime=datetime.now(UTC))
            .returning(cls.id)
        )
        db_session = get_current_session()
        rows = db_session.execute(query)
        db_session.commit()
        cls.clear_cache()
        return [r.id for r in rows]

    @classmethod
    def cancel_run(cls, run_id: str | UUID) -> None:
        query = update(cls).where(cls.id == run_id).values(status="Cancelled", profiling_endtime=datetime.now(UTC))
        db_session = get_current_session()
        db_session.execute(query)
        db_session.commit()
        cls.clear_cache()

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        query = """
        DELETE FROM profile_pair_rules
        WHERE profile_run_id IN :profiling_run_ids;

        DELETE FROM profile_anomaly_results
        WHERE profile_run_id IN :profiling_run_ids;

        DELETE FROM profile_results
        WHERE profile_run_id IN :profiling_run_ids;
        """
        db_session = get_current_session()
        db_session.execute(text(query), {"profiling_run_ids": tuple(ids)})
        db_session.commit()
        cls.delete_where(cls.id.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_minimal.clear()
        cls.select_minimal_where.clear()
        cls.select_summary.clear()

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
            .where(
                ProfilingRun.table_groups_id == self.table_groups_id,
                ProfilingRun.status == "Complete",
                ProfilingRun.profiling_starttime < self.profiling_starttime,
            )
            .order_by(desc(ProfilingRun.profiling_starttime))
            .limit(1)
        )
        return get_current_session().scalar(query)
