from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import streamlit as st
from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, String, asc, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString
from testgen.common.models.entity import ENTITY_HASH_FUNCS, Entity, EntityMinimal
from testgen.utils import is_uuid4


@dataclass
class TestSuiteMinimal(EntityMinimal):
    id: UUID
    project_code: str
    test_suite: str
    connection_id: int
    table_groups_id: UUID
    export_to_observability: str


@dataclass
class TestSuiteSummary(EntityMinimal):
    id: UUID
    project_code: str
    test_suite: str
    connection_name: str
    table_groups_id: UUID
    table_groups_name: str
    test_suite_description: str
    export_to_observability: bool
    test_ct: int
    last_complete_profile_run_id: UUID
    latest_run_id: UUID
    latest_run_start: datetime
    last_run_test_ct: int
    last_run_passed_ct: int
    last_run_warning_ct: int
    last_run_failed_ct: int
    last_run_error_ct: int
    last_run_dismissed_ct: int


class TestSuite(Entity):
    __tablename__ = "test_suites"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)
    test_suite: str = Column(String)
    connection_id: int = Column(BigInteger, ForeignKey("connections.connection_id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    test_suite_description: str = Column(NullIfEmptyString)
    test_action: str = Column(String)
    severity: str = Column(NullIfEmptyString)
    export_to_observability: bool = Column(YNString, default="Y")
    test_suite_schema: str = Column(NullIfEmptyString)
    component_key: str = Column(NullIfEmptyString)
    component_type: str = Column(NullIfEmptyString)
    component_name: str = Column(NullIfEmptyString)
    last_complete_test_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    dq_score_exclude: bool = Column(Boolean, default=False)

    _default_order_by = (asc(test_suite),)
    _minimal_columns = TestSuiteMinimal.__annotations__.keys()

    @classmethod
    @st.cache_data(show_spinner=False)
    def get_minimal(cls, identifier: int) -> TestSuiteMinimal | None:
        result = cls._get_columns(identifier, cls._minimal_columns)
        return TestSuiteMinimal(**result) if result else None

    @classmethod
    @st.cache_data(show_spinner=False, hash_funcs=ENTITY_HASH_FUNCS)
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestSuiteMinimal]:
        results = cls._select_columns_where(cls._minimal_columns, *clauses, order_by=order_by)
        return [TestSuiteMinimal(**row) for row in results]

    @classmethod
    @st.cache_data(show_spinner=False)
    def select_summary(cls, project_code: str, table_group_id: str | UUID | None = None) -> Iterable[TestSuiteSummary]:
        if table_group_id and not is_uuid4(table_group_id):
            return []

        query = f"""
        WITH last_run AS (
            SELECT test_runs.test_suite_id,
                test_runs.id,
                test_runs.test_starttime,
                test_runs.test_ct,
                SUM(
                    CASE
                        WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                        AND test_results.result_status = 'Passed' THEN 1
                        ELSE 0
                    END
                ) AS passed_ct,
                SUM(
                    CASE
                        WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                        AND test_results.result_status = 'Warning' THEN 1
                        ELSE 0
                    END
                ) AS warning_ct,
                SUM(
                    CASE
                        WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                        AND test_results.result_status = 'Failed' THEN 1
                        ELSE 0
                    END
                ) AS failed_ct,
                SUM(
                    CASE
                        WHEN COALESCE(test_results.disposition, 'Confirmed') = 'Confirmed'
                        AND test_results.result_status = 'Error' THEN 1
                        ELSE 0
                    END
                ) AS error_ct,
                SUM(
                    CASE
                        WHEN COALESCE(test_results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive') THEN 1
                        ELSE 0
                    END
                ) AS dismissed_ct
            FROM test_suites
                LEFT JOIN test_runs ON (
                    test_suites.last_complete_test_run_id = test_runs.id
                )
                LEFT JOIN test_results ON (
                    test_runs.id = test_results.test_run_id
                )
            GROUP BY test_runs.id
        ),
        test_defs AS (
            SELECT test_suite_id,
                COUNT(*) AS count
            FROM test_definitions
            GROUP BY test_suite_id
        )
        SELECT
            suites.id,
            suites.project_code,
            suites.test_suite,
            connections.connection_name,
            suites.table_groups_id,
            groups.table_groups_name,
            suites.test_suite_description,
            CASE WHEN suites.export_to_observability = 'Y' THEN TRUE ELSE FALSE END AS export_to_observability,
            test_defs.count AS test_ct,
            last_complete_profile_run_id,
            last_run.id AS latest_run_id,
            last_run.test_starttime AS latest_run_start,
            last_run.test_ct AS last_run_test_ct,
            last_run.passed_ct AS last_run_passed_ct,
            last_run.warning_ct AS last_run_warning_ct,
            last_run.failed_ct AS last_run_failed_ct,
            last_run.error_ct AS last_run_error_ct,
            last_run.dismissed_ct AS last_run_dismissed_ct
        FROM test_suites AS suites
        LEFT JOIN last_run
            ON (suites.id = last_run.test_suite_id)
        LEFT JOIN test_defs
            ON (suites.id = test_defs.test_suite_id)
        LEFT JOIN connections AS connections
            ON (connections.connection_id = suites.connection_id)
        LEFT JOIN table_groups AS groups
            ON (groups.id = suites.table_groups_id)
        WHERE suites.project_code = :project_code
            {"AND suites.table_groups_id = :table_group_id" if table_group_id else ""}
        ORDER BY suites.test_suite;
        """
        params = {"project_code": project_code, "table_group_id": table_group_id}
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TestSuiteSummary(**row) for row in results]

    @classmethod
    def has_running_process(cls, ids: list[str]) -> bool:
        query = """
        SELECT DISTINCT test_suite_id
        FROM test_runs
        WHERE test_suite_id IN :test_suite_ids
            AND status = 'Running';
        """
        params = {"test_suite_ids": tuple(ids)}
        process_count = get_current_session().execute(text(query), params).rowcount
        return process_count > 0

    @classmethod
    def is_in_use(cls, ids: list[str]) -> bool:
        query = """
        SELECT DISTINCT test_suite_id FROM test_definitions WHERE test_suite_id IN :test_suite_ids
        UNION
        SELECT DISTINCT test_suite_id FROM test_results WHERE test_suite_id IN :test_suite_ids;
        """
        params = {"test_suite_ids": tuple(ids)}
        dependency_count = get_current_session().execute(text(query), params).rowcount
        return dependency_count > 0

    @classmethod
    def cascade_delete(cls, ids: list[str]) -> None:
        query = """
        DELETE FROM working_agg_cat_results
        WHERE test_run_id IN (
            SELECT id FROM test_runs
            WHERE test_suite_id IN :test_suite_ids
        );

        DELETE FROM working_agg_cat_tests
        WHERE test_run_id IN (
            SELECT id FROM test_runs
            WHERE test_suite_id IN :test_suite_ids
        );

        DELETE FROM test_runs
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM test_results
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM test_definitions
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM job_schedules js
        USING test_suites ts
        WHERE js.kwargs->>'project_key' = ts.project_code
            AND js.kwargs->>'test_suite_key' = ts.test_suite
            AND ts.id IN :test_suite_ids;
        """
        db_session = get_current_session()
        db_session.execute(text(query), {"test_suite_ids": tuple(ids)})
        db_session.commit()
        cls.delete_where(cls.id.in_(ids))

    @classmethod
    def clear_cache(cls) -> bool:
        super().clear_cache()
        cls.get_minimal.clear()
        cls.select_minimal_where.clear()
        cls.select_summary.clear()
