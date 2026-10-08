import enum
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, Column, Enum, ForeignKey, Integer, String, asc, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import InstrumentedAttribute

from testgen.common.enums import SuiteType
from testgen.common.models import get_current_session
from testgen.common.models.custom_types import NullIfEmptyString, YNString
from testgen.common.models.entity import Entity, EntityMinimal
from testgen.common.models.suite_version import SuiteVersion
from testgen.utils import is_uuid4


class SuiteSeverity(StrEnum):
    """A test suite's default severity: the values test execution recognizes."""

    FAIL = "Fail"
    WARNING = "Warning"
    LOG = "Log"


class PredictSensitivity(enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


# Monitor configuration a monitor suite starts with, mirroring the UI's setup form.
MONITOR_SETTING_DEFAULTS: dict[str, Any] = {
    "monitor_lookback": 14,
    "monitor_regenerate_freshness": True,
    "predict_min_lookback": 30,
    "predict_sensitivity": PredictSensitivity.medium.value,
    "predict_exclude_weekends": False,
    "predict_holiday_codes": None,
}


@dataclass
class TestSuiteMinimal(EntityMinimal):
    id: UUID
    project_code: str
    test_suite: str
    connection_id: int
    table_groups_id: UUID
    export_to_observability: str


@dataclass(frozen=True)
class TestDefinitionStats:
    """Aggregate test-definition counts for a test suite."""

    total: int
    locked: int
    counts_by_type: dict[str, int]


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
    latest_run_job_execution_id: UUID | None
    latest_run_start: datetime
    last_run_test_ct: int
    last_run_passed_ct: int
    last_run_warning_ct: int
    last_run_failed_ct: int
    last_run_error_ct: int
    last_run_log_ct: int
    last_run_dismissed_ct: int
    generation_sets: list[str] | None

def _last_run_sql(suites_condition: str = "TRUE") -> str:
    """A query yielding each test suite's last completed run, with its result counts by status.

    Args:
        suites_condition: SQL condition on ``test_suites AS suites`` naming the suites to cover.

    Returns:
        SQL for a CTE body. Its rows carry ``test_suite_id``, the run's ``id``, ``test_starttime``,
        ``started_at`` (from ``job_executions``, zone-aware), ``test_ct`` and the ``*_ct`` counts of
        confirmed results by status, plus ``dismissed_ct``.
    """
    return f"""
            SELECT suites.id AS test_suite_id,
                runs.id,
                runs.test_starttime,
                jobs.started_at,
                runs.test_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed' AND results.result_status = 'Passed'
                ) AS passed_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed' AND results.result_status = 'Warning'
                ) AS warning_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed' AND results.result_status = 'Failed'
                ) AS failed_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed' AND results.result_status = 'Error'
                ) AS error_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') = 'Confirmed' AND results.result_status = 'Log'
                ) AS log_ct,
                COUNT(*) FILTER (
                    WHERE COALESCE(results.disposition, 'Confirmed') IN ('Dismissed', 'Inactive')
                ) AS dismissed_ct
            FROM test_suites AS suites
                JOIN test_runs AS runs ON runs.id = suites.last_complete_test_run_id
                LEFT JOIN job_executions AS jobs ON jobs.id = runs.id
                LEFT JOIN test_results AS results ON results.test_run_id = runs.id
            WHERE {suites_condition}
            GROUP BY suites.id, runs.id, runs.test_starttime, jobs.started_at, runs.test_ct
        """


@dataclass
class TestSuiteListItem:
    id: UUID
    test_suite: str
    project_code: str
    connection_id: int
    table_groups_id: UUID
    table_groups_name: str | None
    test_suite_description: str | None
    test_count: int
    latest_run_id: UUID | None
    latest_run_started_at: datetime | None
    latest_run_test_count: int | None
    latest_run_passed_count: int | None
    latest_run_failed_count: int | None
    latest_run_warning_count: int | None
    latest_run_error_count: int | None
    latest_run_log_count: int | None
    latest_run_dismissed_count: int | None


class TestSuite(Entity):
    __tablename__ = "test_suites"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    project_code: str = Column(String)
    test_suite: str = Column(String)
    connection_id: int = Column(BigInteger, ForeignKey("connections.connection_id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True))
    test_suite_description: str = Column(NullIfEmptyString)
    severity: str = Column(NullIfEmptyString)
    export_to_observability: bool = Column(YNString, default="Y")
    component_key: str = Column(NullIfEmptyString)
    component_type: str = Column(NullIfEmptyString)
    component_name: str = Column(NullIfEmptyString)
    last_complete_test_run_id: UUID = Column(postgresql.UUID(as_uuid=True))
    dq_score_exclude: bool = Column(Boolean, default=False)
    suite_type: SuiteType = Column(
        String(20), nullable=False, default=SuiteType.REGULAR, server_default=text("'regular'")
    )
    monitor_lookback: int | None = Column(Integer)
    monitor_regenerate_freshness: bool = Column(Boolean, default=True)
    predict_sensitivity: PredictSensitivity | None = Column(Enum(PredictSensitivity))
    predict_min_lookback: int | None = Column(Integer)
    predict_exclude_weekends: bool = Column(Boolean, default=False)
    predict_holiday_codes: list[str] | None = Column(postgresql.ARRAY(String))
    generation_sets: list[str] | None = Column(postgresql.ARRAY(String))

    @property
    def holiday_codes_list(self) -> list[str] | None:
        return self.predict_holiday_codes or None

    _default_order_by = (asc(func.lower(test_suite)),)
    _minimal_columns = TestSuiteMinimal.__annotations__.keys()

    @classmethod
    def get_regular(cls, identifier: str | UUID) -> "TestSuite | None":
        """Like get(), but returns None for monitor suites."""
        query = select(cls).where(cls.id == identifier, cls.suite_type == SuiteType.REGULAR)
        return get_current_session().scalars(query).first()


    @classmethod
    def get_minimal(cls, identifier: int) -> TestSuiteMinimal | None:
        result = cls._get_columns(identifier, cls._minimal_columns)
        return TestSuiteMinimal(**result) if result else None

    @classmethod
    def select_minimal_where(
        cls, *clauses, order_by: tuple[str | InstrumentedAttribute] = _default_order_by
    ) -> Iterable[TestSuiteMinimal]:
        results = cls._select_columns_where(cls._minimal_columns, *clauses, order_by=order_by)
        return [TestSuiteMinimal(**row) for row in results]

    @classmethod
    def select_summary(cls, project_code: str, table_group_id: str | UUID | None = None, test_suite_name: str | None = None) -> Iterable[TestSuiteSummary]:
        if table_group_id and not is_uuid4(table_group_id):
            return []

        query = f"""
        WITH last_run AS ({_last_run_sql()}),
        test_defs AS (
            SELECT test_suite_id,
                COUNT(*) AS count
            FROM test_definitions
            WHERE version_id = {SuiteVersion.resolved_for_sql("test_definitions.test_suite_id")}
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
            suites.generation_sets,
            CASE WHEN suites.export_to_observability = 'Y' THEN TRUE ELSE FALSE END AS export_to_observability,
            test_defs.count AS test_ct,
            last_complete_profile_run_id,
            last_run.id AS latest_run_id,
            last_run.id AS latest_run_job_execution_id,
            last_run.test_starttime AS latest_run_start,
            last_run.test_ct AS last_run_test_ct,
            last_run.passed_ct AS last_run_passed_ct,
            last_run.warning_ct AS last_run_warning_ct,
            last_run.failed_ct AS last_run_failed_ct,
            last_run.error_ct AS last_run_error_ct,
            last_run.log_ct AS last_run_log_ct,
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
        WHERE suites.suite_type = 'regular'
            AND suites.project_code = :project_code
            {"AND suites.table_groups_id = :table_group_id" if table_group_id else ""}
            {"AND suites.test_suite ILIKE :test_suite_name" if test_suite_name else ""}
        ORDER BY LOWER(suites.test_suite);
        """
        params = {"project_code": project_code, "table_group_id": table_group_id, "test_suite_name": f"%{test_suite_name}%" if test_suite_name else None}
        db_session = get_current_session()
        results = db_session.execute(text(query), params).mappings().all()
        return [TestSuiteSummary(**row) for row in results]

    @classmethod
    def list_for_project(
        cls, project_code: str, *clauses, page: int = 1, limit: int = 20
    ) -> tuple[list[TestSuiteListItem], int]:
        """Paginated regular test suites of a project, each with its test count and last completed run.

        Returns the page of items and the total across pages.
        """
        query = (
            select(cls.id)
            .where(cls.project_code == project_code, cls.suite_type == SuiteType.REGULAR, *clauses)
            .order_by(func.lower(cls.test_suite), cls.id)
        )
        rows, total = cls._paginate(query, page=page, limit=limit)
        if not rows:
            return [], total

        ids = [row["id"] for row in rows]
        query = f"""
        WITH last_run AS ({_last_run_sql("suites.id IN :ids")}),
        test_defs AS (
            SELECT td.test_suite_id, COUNT(*) AS test_count
            FROM test_definitions AS td
            WHERE td.test_suite_id IN :ids
                AND td.version_id = {SuiteVersion.resolved_for_sql("td.test_suite_id")}
            GROUP BY td.test_suite_id
        )
        SELECT
            suites.id,
            suites.test_suite,
            suites.project_code,
            suites.connection_id,
            suites.table_groups_id,
            groups.table_groups_name,
            suites.test_suite_description,
            COALESCE(test_defs.test_count, 0) AS test_count,
            last_run.id AS latest_run_id,
            last_run.started_at AS latest_run_started_at,
            last_run.test_ct AS latest_run_test_count,
            last_run.passed_ct AS latest_run_passed_count,
            last_run.failed_ct AS latest_run_failed_count,
            last_run.warning_ct AS latest_run_warning_count,
            last_run.error_ct AS latest_run_error_count,
            last_run.log_ct AS latest_run_log_count,
            last_run.dismissed_ct AS latest_run_dismissed_count
        FROM test_suites AS suites
            LEFT JOIN table_groups AS groups ON groups.id = suites.table_groups_id
            LEFT JOIN test_defs ON test_defs.test_suite_id = suites.id
            LEFT JOIN last_run ON last_run.test_suite_id = suites.id
        WHERE suites.id IN :ids;
        """
        results = get_current_session().execute(
            text(query), {"ids": tuple(str(id_) for id_ in ids)}
        ).mappings().all()
        by_id = {row["id"]: TestSuiteListItem(**row) for row in results}
        return [by_id[id_] for id_ in ids], total

    @classmethod
    def test_definition_stats(cls, test_suite_id: str | UUID) -> "TestDefinitionStats":
        """Aggregate test-definition counts for a suite: total, locked, and per-test-type.

        The per-type bucket uses the user-facing ``test_name_short`` label from
        ``test_types``, falling back to the raw ``test_type`` code when the lookup
        row is missing (defensive — every shipping test type has a short name).
        """
        query = f"""
        SELECT
            COALESCE(tt.test_name_short, td.test_type) AS type_label,
            COUNT(*) AS total,
            SUM(CASE WHEN COALESCE(td.lock_refresh, 'N') = 'Y' THEN 1 ELSE 0 END) AS locked
        FROM test_definitions td
            LEFT JOIN test_types tt ON tt.test_type = td.test_type
        WHERE td.test_suite_id = :test_suite_id
            AND td.version_id = {SuiteVersion.resolved_for_sql("td.test_suite_id")}
        GROUP BY type_label
        ORDER BY type_label;
        """
        rows = (
            get_current_session()
            .execute(text(query), {"test_suite_id": str(test_suite_id)})
            .mappings()
            .all()
        )
        counts_by_type = {row["type_label"]: int(row["total"]) for row in rows}
        total = sum(counts_by_type.values())
        locked = sum(int(row["locked"]) for row in rows)
        return TestDefinitionStats(total=total, locked=locked, counts_by_type=counts_by_type)

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
        DELETE FROM job_executions
        WHERE id IN (
            SELECT id FROM test_runs
            WHERE test_suite_id IN :test_suite_ids
        );

        DELETE FROM test_runs
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM test_results
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM test_definitions
        WHERE test_suite_id IN :test_suite_ids;

        DELETE FROM job_schedules
        WHERE (kwargs->>'test_suite_id')::UUID IN :test_suite_ids;
        """
        db_session = get_current_session()
        db_session.execute(text(query), {"test_suite_ids": tuple(ids)})
        cls.delete_where(cls.id.in_(ids))
