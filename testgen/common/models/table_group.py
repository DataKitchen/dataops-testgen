from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import BigInteger, Boolean, Column, Float, ForeignKey, Integer, String, asc, func, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.common.models.scheduler import RUN_TESTS_JOB_KEY, JobSchedule
from testgen.common.models.scores import ScoreDefinition
from testgen.common.models.test_suite import TestSuite


@dataclass
class TableGroupMinimal(EntityMinimal):
    id: UUID
    project_code: str
    connection_id: int
    table_groups_name: str
    table_group_schema: str
    profiling_table_set: str
    profiling_include_mask: str
    profiling_exclude_mask: str
    profile_use_sampling: bool
    profiling_delay_days: str


@dataclass
class TableGroupStats(EntityMinimal):
    id: UUID
    table_groups_name: str
    table_group_schema: str
    table_ct: int
    column_ct: int
    approx_record_ct: int
    record_ct: int
    approx_data_point_ct: int
    data_point_ct: int


@dataclass
class TableGroupSummary(EntityMinimal):
    id: UUID
    table_groups_name: str
    table_ct: int
    column_ct: int
    approx_record_ct: int
    record_ct: int
    approx_data_point_ct: int
    data_point_ct: int
    dq_score_profiling: float
    dq_score_testing: float
    latest_profile_id: UUID
    latest_profile_start: datetime
    latest_anomalies_ct: int
    latest_anomalies_definite_ct: int
    latest_anomalies_likely_ct: int
    latest_anomalies_possible_ct: int
    latest_anomalies_dismissed_ct: int


class TableGroup(Entity):
    __tablename__ = "table_groups"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String, ForeignKey("projects.project_code"))
    connection_id: int = Column(BigInteger, ForeignKey("connections.connection_id"))
    monitor_test_suite_id: UUID | None = Column(
        postgresql.UUID(as_uuid=True),
        ForeignKey("test_suites.id"),
        default=None,
    )
    table_groups_name: str = Column(String)
    table_group_schema: str = Column(String)
    profiling_table_set: str = Column(NullIfEmptyString)
    profiling_include_mask: str = Column(NullIfEmptyString)
    profiling_exclude_mask: str = Column(NullIfEmptyString)
    profile_id_column_mask: str = Column(String, default="%id")
    profile_sk_column_mask: str = Column(String, default="%_sk")
    profile_use_sampling: bool = Column(YNString, default="N")
    profile_sample_percent: str = Column(String, default="30")
    profile_sample_min_count: int = Column(BigInteger, default=100000)
    profiling_delay_days: str = Column(String, default="0")
    profile_flag_cdes: bool = Column(Boolean, default=True)
    profile_do_pair_rules: bool = Column(YNString, default="N")
    profile_pair_rule_pct: int = Column(Integer, default=95)
    include_in_dashboard: bool = Column(Boolean, default=True)
    description: str = Column(NullIfEmptyString)
    data_source: str = Column(NullIfEmptyString)
    source_system: str = Column(NullIfEmptyString)
    source_process: str = Column(NullIfEmptyString)
    data_location: str = Column(NullIfEmptyString)
    business_domain: str = Column(NullIfEmptyString)
    stakeholder_group: str = Column(NullIfEmptyString)
    transform_level: str = Column(NullIfEmptyString)
    data_product: str = Column(NullIfEmptyString)
    last_complete_profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    dq_score_profiling: float = Column(Float)
    dq_score_testing: float = Column(Float)

    _default_order_by = (asc(func.lower(table_groups_name)),)
    _minimal_columns = TableGroupMinimal.__annotations__.keys()
    _update_exclude_columns = (
        id,
        project_code,
        connection_id,
        profile_do_pair_rules,
        profile_pair_rule_pct,
        last_complete_profile_run_id,
        dq_score_profiling,
        dq_score_testing,
    )

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, id_: str | UUID) -> TableGroupMinimal | None:
        result = cls._get_columns(id_, cls._minimal_columns)
        return TableGroupMinimal(**result) if result else None

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TableGroupMinimal]:
        results = cls._select_columns_where(cls._minimal_columns, *clauses, order_by=order_by)
        return [TableGroupMinimal(**row) for row in results]
    
    @classmethod
    @st.cache_data(show_spinner=False)
    def select_stats(cls, project_code: str, table_group_id: str | UUID | None = None) -> Iterable[TableGroupStats]:
        query = f"""
        WITH stats AS (
            SELECT table_groups_id,
                COUNT(*) AS table_ct,
                SUM(column_ct) AS column_ct,
                SUM(approx_record_ct) AS approx_record_ct,
                SUM(record_ct) AS record_ct,
                SUM(column_ct * approx_record_ct) AS approx_data_point_ct,
                SUM(column_ct * record_ct) AS data_point_ct
            FROM data_table_chars
            GROUP BY table_groups_id
        )
        SELECT groups.id,
            groups.table_groups_name,
            groups.table_group_schema,
            stats.table_ct,
            stats.column_ct,
            stats.approx_record_ct,
            stats.record_ct,
            stats.approx_data_point_ct,
            stats.data_point_ct
        FROM table_groups AS groups
            LEFT JOIN stats ON (groups.id = stats.table_groups_id)
        WHERE groups.project_code = :project_code
            {"AND groups.id = :table_group_id" if table_group_id else ""}
        ORDER BY LOWER(groups.table_groups_name);
        """
        params = {"project_code": project_code, "table_group_id": table_group_id}
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TableGroupStats(**row) for row in results]

    @classmethod
    @st.cache_data(show_spinner=False)
    def select_summary(cls, project_code: str, for_dashboard: bool = False) -> Iterable[TableGroupSummary]:
        query = f"""
        WITH stats AS (
            SELECT table_groups_id,
                COUNT(*) AS table_ct,
                SUM(column_ct) AS column_ct,
                SUM(approx_record_ct) AS approx_record_ct,
                SUM(record_ct) AS record_ct,
                SUM(column_ct * approx_record_ct) AS approx_data_point_ct,
                SUM(column_ct * record_ct) AS data_point_ct
            FROM data_table_chars
            GROUP BY table_groups_id
        ),
        latest_profile AS (
            SELECT latest_run.table_groups_id,
                latest_run.id,
                latest_run.profiling_starttime,
                latest_run.anomaly_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood = 'Definite' THEN 1
                        ELSE 0
                    END
                ) AS definite_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood = 'Likely' THEN 1
                        ELSE 0
                    END
                ) AS likely_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') = 'Confirmed'
                        AND anomaly_types.issue_likelihood IN ('Possible', 'Potential PII') THEN 1
                        ELSE 0
                    END
                ) AS possible_ct,
                SUM(
                    CASE
                        WHEN COALESCE(latest_anomalies.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                        ELSE 0
                    END
                ) AS dismissed_ct
            FROM table_groups groups
                LEFT JOIN profiling_runs latest_run ON (
                    groups.last_complete_profile_run_id = latest_run.id
                )
                LEFT JOIN profile_anomaly_results latest_anomalies ON (
                    latest_run.id = latest_anomalies.profile_run_id
                )
                LEFT JOIN profile_anomaly_types anomaly_types ON (
                    anomaly_types.id = latest_anomalies.anomaly_id
                )
            GROUP BY latest_run.id
        )
        SELECT groups.id,
            groups.table_groups_name,
            stats.table_ct,
            stats.column_ct,
            stats.approx_record_ct,
            stats.record_ct,
            stats.approx_data_point_ct,
            stats.data_point_ct,
            groups.dq_score_profiling,
            groups.dq_score_testing,
            latest_profile.id AS latest_profile_id,
            latest_profile.profiling_starttime AS latest_profile_start,
            latest_profile.anomaly_ct AS latest_anomalies_ct,
            latest_profile.definite_ct AS latest_anomalies_definite_ct,
            latest_profile.likely_ct AS latest_anomalies_likely_ct,
            latest_profile.possible_ct AS latest_anomalies_possible_ct,
            latest_profile.dismissed_ct AS latest_anomalies_dismissed_ct
        FROM table_groups AS groups
            LEFT JOIN stats ON (groups.id = stats.table_groups_id)
            LEFT JOIN latest_profile ON (groups.id = latest_profile.table_groups_id)
        WHERE groups.project_code = :project_code
            {"AND groups.include_in_dashboard IS TRUE" if for_dashboard else ""};
        """
        params = {"project_code": project_code}
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TableGroupSummary(**row) for row in results]

    @classmethod
    def has_running_process(cls, ids: list[str]) -> bool | None:
        query = """
        SELECT DISTINCT profiling_runs.id
        FROM profiling_runs
        INNER JOIN table_groups
            ON table_groups.id = profiling_runs.table_groups_id
        WHERE table_groups.id IN :table_group_ids
            AND profiling_runs.status = 'Running';
        """
        params = {"table_group_ids": tuple(ids)}
        process_count = get_current_session().execute(text(query), params).rowcount
        if process_count:
            return True

        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id.in_(ids))
        if test_suites:
            return TestSuite.has_running_process([item.id for item in test_suites])

        return False

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id.in_(ids))
        if test_suites:
            return True

        query = "SELECT id FROM profiling_runs WHERE table_groups_id IN :table_group_ids;"
        params = {"table_group_ids": tuple(ids)}
        dependency_count = get_current_session().execute(text(query), params).rowcount
        return dependency_count > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        test_suites = TestSuite.select_minimal_where(TestSuite.table_groups_id.in_(ids))
        if test_suites:
            TestSuite.cascade_delete([item.id for item in test_suites])

        query = """
        DELETE FROM profile_pair_rules ppr
        USING profiling_runs pr, table_groups tg
        WHERE pr.id = ppr.profile_run_id AND tg.id = pr.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM profile_anomaly_results par
        USING table_groups tg
        WHERE tg.id = par.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM profile_results pr
        USING table_groups tg
        WHERE tg.id = pr.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM profiling_runs pr
        USING table_groups tg
        WHERE tg.id = pr.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM data_table_chars dtc
        USING table_groups tg
        WHERE tg.id = dtc.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM data_column_chars dcs
        USING table_groups tg
        WHERE tg.id = dcs.table_groups_id AND tg.id IN :table_group_ids;

        DELETE FROM job_schedules
        WHERE (kwargs->>'table_group_id')::UUID IN :table_group_ids;
        """
        params = {"table_group_ids": tuple(ids)}
        db_session = get_current_session()
        db_session.execute(text(query), params)
        db_session.commit()
        cls.delete_where(cls.id.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_minimal.clear()
        cls.select_minimal_where.clear()
        cls.select_summary.clear()

    def save(
        self,
        add_scorecard_definition: bool = False,
        add_monitor_test_suite: bool = False,
        monitor_schedule_timezone: str = "UTC",
    ) -> None:
        if self.id:
            values = {
                column.key: getattr(self, column.key, None)
                for column in self.__table__.columns
                if column not in self._update_exclude_columns
            }
            query = update(TableGroup).where(TableGroup.id == self.id).values(**values)
            db_session = get_current_session()
            db_session.execute(query)
            db_session.commit()
        else:
            super().save()
            db_session = get_current_session()

            if add_scorecard_definition:
                ScoreDefinition.from_table_group(self).save()

            if add_monitor_test_suite:
                test_suite = TestSuite(
                    project_code=self.project_code,
                    test_suite=f"{self.table_groups_name} Monitor",
                    connection_id=self.connection_id,
                    table_groups_id=self.id,
                    export_to_observability=False,
                    dq_score_exclude=True,
                    view_mode="Monitor",
                )
                test_suite.save()

                schedule_job = JobSchedule(
                    project_code=self.project_code,
                    key=RUN_TESTS_JOB_KEY,
                    cron_expr="0 * * * *",
                    cron_tz=monitor_schedule_timezone,
                    args=[],
                    kwargs={"test_suite_id": test_suite.id},
                )
                db_session.add(schedule_job)

                self.monitor_test_suite_id = test_suite.id
                db_session.execute(
                    update(TableGroup)
                    .where(TableGroup.id == self.id).values(monitor_test_suite_id=test_suite.id)
                )
                db_session.commit()

        TableGroup.clear_cache()
