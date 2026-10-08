import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text

from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    get_flavor_service,
    replace_params,
)
from testgen.common.enums import SuiteType
from testgen.common.generation_set_service import MONITOR_GENERATION_SET, resolve_generation_sets
from testgen.common.job_context import job_context
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import MANAGED_TEST_TYPES, TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.utils import to_sql_timestamp

LOG = logging.getLogger("testgen")

MonitorTestType = Literal["Freshness_Trend", "Volume_Trend", "Schema_Drift"]
MonitorGenerationMode = Literal["upsert", "insert", "delete"]


@dataclasses.dataclass
class TestTypeParams:
    test_type: str
    selection_criteria: str | None
    generation_template: str | None
    default_parm_columns: str | None
    default_parm_values: str | None


# Generate tests for a regular non-monitor test suite - don't use for monitors
def run_test_generation(
    test_suite_id: str | UUID,
    generation_sets: list[str] | None = None,
    test_types: list[str] | None = None,
    profile_run_id: UUID | None = None,
    table_names: list[str] | None = None,
) -> None:
    if test_suite_id is None:
        raise ValueError("Test Suite ID was not specified")

    LOG.info(f"Starting test generation for test suite {test_suite_id}")

    LOG.info("Retrieving connection, table group, and test suite parameters")
    test_suite = TestSuite.get(test_suite_id)
    if test_suite.suite_type == SuiteType.MONITOR:
        raise ValueError("Cannot run regular test generation for monitor suite")

    resolved_sets = resolve_generation_sets(test_suite, generation_sets)
    LOG.info(f"Generating tests for generation sets: {', '.join(resolved_sets)}")

    table_group = TableGroup.get(test_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)

    success = False
    try:
        TestGeneration(
            connection, table_group, test_suite, resolved_sets, test_types, profile_run_id,
            table_names=table_names,
        ).run()
        success = True
    except Exception:
        LOG.exception("Test generation encountered an error.")
        raise
    finally:
        MixpanelService().send_event(
            "generate-tests",
            source=job_context.get().source.upper(),
            sql_flavor=connection.sql_flavor,
            generation_sets=resolved_sets,
        )
        if success:
            test_suite.generation_sets = resolved_sets


def run_monitor_generation(
    monitor_suite_id: str | UUID,
    monitors: list[MonitorTestType],
    mode: MonitorGenerationMode = "upsert",
    table_names: list[str] | None = None,
    profile_run_id: UUID | None = None,
    *,
    in_session: bool = False,
) -> None:
    """
    Modes:
    - "upsert": Add tests for new tables + update tests for existing tables + no deletion
    - "insert": Only add tests for new tables
    - "delete": Only delete tests for dropped tables

    With ``in_session``, the generation statements run in the current database session
    instead of each committing on its own connection, so they see the session's
    uncommitted rows and roll back with it.
    """
    if monitor_suite_id is None:
        raise ValueError("Monitor Suite ID was not specified")

    LOG.info(f"Starting monitor generation for {monitor_suite_id} (Mode = {mode}, Monitors = {monitors})")

    monitor_suite = TestSuite.get(monitor_suite_id)
    if monitor_suite.suite_type != SuiteType.MONITOR:
        raise ValueError("Cannot run monitor generation for regular test suite")
    table_group = TableGroup.get(monitor_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)

    TestGeneration(
        connection, table_group, monitor_suite, [MONITOR_GENERATION_SET], monitors, profile_run_id
    ).monitor_run(mode, table_names=table_names, in_session=in_session)


def _execute_in_session(queries: list[tuple[str, dict | None]]) -> None:
    session = get_current_session()
    for query, params in queries:
        session.execute(text(query), params)


def run_conformance_generation(test_suite_id: str | UUID, table_names: list[str] | None = None) -> None:
    """Reconcile a contract draft's Schema Conformance tests with the tables it declares.

    Adds a test for each declared table the table group's catalog holds and has no test yet,
    and deletes the tests of tables the draft no longer declares. ``table_names`` limits the
    additions to those tables; the deletions always cover the whole draft.
    """
    test_suite = TestSuite.get(test_suite_id)
    if test_suite.suite_type != SuiteType.CONTRACT:
        raise ValueError("Cannot run conformance generation for a suite that is not a contract")
    table_group = TableGroup.get(test_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)

    TestGeneration(connection, table_group, test_suite, [], table_names=table_names).conformance_run()


class TestGeneration:

    def __init__(
        self,
        connection: Connection,
        table_group: TableGroup,
        test_suite: TestSuite,
        generation_sets: list[str],
        test_types_filter: list[MonitorTestType] | None = None,
        profile_run_id: UUID | None = None,
        table_names: list[str] | None = None,
    ):
        self.connection = connection
        self.table_group = table_group
        self.test_suite = test_suite
        self.generation_sets = generation_sets
        self.test_types_filter = test_types_filter
        self.table_names = table_names
        self.flavor = connection.sql_flavor
        self.flavor_service = get_flavor_service(self.flavor)

        self.run_date = datetime.now(UTC)
        self.as_of_date = self.run_date
        if delay_days := self.table_group.profiling_delay_days:
            self.as_of_date = self.run_date - timedelta(days=delay_days)

        # A run that has just finished cannot be identified any other way at this point: its
        # job execution is still 'running' (marked complete only after the handler returns),
        # and last_complete_profile_run_id is not set until the score rollup job runs later.
        self.profile_run_id = ProfilingRun.latest_readable_id(
            table_group.id, self.as_of_date, finishing_run_id=profile_run_id
        )
        if self.profile_run_id is None:
            # A NULL run id joins to zero rows in every template, so generation runs to
            # completion and reports success without creating anything.
            LOG.warning(
                f"No profiling run with complete results on or before "
                f"{self.as_of_date.date()} for table group {table_group.id}. "
                "Test generation will not create any test definitions."
            )

    def run(self) -> None:
        TestDefinition.assert_version_writable(self.version_id)

        generation_queries = self._get_generation_queries()
        if not generation_queries:
            LOG.warning(
                "No active test types in the selected generation sets; nothing generated and "
                "nothing removed."
            )
            return

        LOG.info("Running test generation queries")
        execute_db_queries([
            *generation_queries,
            self._get_query("delete_stale_autogen_tests.sql"),
            self._get_query("delete_overridden_autogen_tests.sql"),
        ])

    def monitor_run(
        self, mode: MonitorGenerationMode, table_names: list[str] | None = None, *, in_session: bool = False
    ) -> None:
        execute = _execute_in_session if in_session else execute_db_queries
        if mode == "delete":
            execute([self._get_query("delete_stale_monitors.sql")])
            return

        extra_params = {"INSERT_ONLY": mode == "insert"}
        if table_names:
            table_list = ", ".join(f"'{table}'" for table in table_names)
            extra_params["TABLE_FILTER"] = f"AND table_name IN ({table_list})"

        LOG.info("Running monitor generation queries")
        execute(self._get_generation_queries(extra_params=extra_params))

    def conformance_run(self) -> None:
        TestDefinition.assert_version_writable(self.version_id)
        LOG.info("Running conformance generation queries")
        execute_db_queries([
            self._get_query("gen_Schema_Conformance.sql"),
            self._get_query("delete_undeclared_conformance.sql"),
        ])

    def _get_generation_queries(self, extra_params: dict | None = None) -> list[tuple[str, dict]]:
        test_types = fetch_dict_from_db(*self._get_query("get_test_types.sql", extra_params=extra_params))
        test_types = [TestTypeParams(**item) for item in test_types]

        if self.test_types_filter:
            test_types = [tt for tt in test_types if tt.test_type in self.test_types_filter]

        selection_queries = [
            self._get_query("gen_selection_tests.sql", test_type=tt, extra_params=extra_params)
            for tt in test_types 
            if tt.selection_criteria and tt.selection_criteria != "TEMPLATE"
        ]

        template_queries = []
        for tt in test_types:
            if template_file := tt.generation_template:
                # Try flavor-specific template first, then fall back to generic
                for directory in [f"flavors/{self.flavor}/gen_query_tests", "gen_query_tests", "gen_funny_cat_tests"]:
                    try:
                        template_queries.append(self._get_query(template_file, directory, extra_params=extra_params))
                        break
                    except (ValueError, ModuleNotFoundError):
                        continue
                else:
                    LOG.warning(f"Template file '{template_file}' not found for test type '{tt.test_type}'")
    
        return [*selection_queries, *template_queries]        

    @cached_property
    def version_id(self) -> UUID:
        """The suite version this run's writes are scoped to."""
        return get_current_session().scalar(select(SuiteVersion.resolved_for(self.test_suite.id)))

    def _get_params(self, test_type: TestTypeParams | None = None) -> dict:
        params = {}
        if test_type:
            params.update({
                "TEST_TYPE": test_type.test_type,
                # Replace these first since they may contain other params
                "SELECTION_CRITERIA": test_type.selection_criteria,
                "DEFAULT_PARM_COLUMNS": test_type.default_parm_columns,
                "DEFAULT_PARM_COLUMNS_UPDATE": ",".join([
                    f"{column} = EXCLUDED.{column.strip()}"
                    for column in test_type.default_parm_columns.split(",")
                ]) if test_type.default_parm_columns else "",
                "DEFAULT_PARM_VALUES": test_type.default_parm_values,
            })
        params.update({
            "TABLE_GROUPS_ID": self.table_group.id,
            "TEST_SUITE_ID": self.test_suite.id,
            "VERSION_ID": self.version_id,
            "DATA_SCHEMA": self.table_group.table_group_schema,
            "GENERATION_SETS": self.generation_sets,
            "TEST_TYPES_FILTER": self.test_types_filter,
            "MANAGED_TEST_TYPES": sorted(MANAGED_TEST_TYPES),
            "PROFILE_RUN_ID": self.profile_run_id,
            "RUN_DATE": to_sql_timestamp(self.run_date),
            "AS_OF_DATE": to_sql_timestamp(self.as_of_date),
            "SQL_FLAVOR": self.flavor,
            "QUOTE": self.flavor_service.quote_character,
            "INSERT_ONLY": False,
            "TABLE_NAMES": self.table_names,
            "TABLE_FILTER": "AND table_name = ANY(:TABLE_NAMES)" if self.table_names is not None else "",
        })
        return params
    
    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "generation",
        test_type: TestTypeParams | None = None,
        extra_params: dict | None = None,
    ) -> tuple[str, dict | None]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = self._get_params(test_type)
        if extra_params:
            params.update(extra_params)
        query = replace_params(query, params)
        return query, params
