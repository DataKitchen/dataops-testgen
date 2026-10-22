import dataclasses
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm.attributes import flag_modified

from testgen.common import contract_document
from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    get_flavor_service,
    replace_params,
)
from testgen.common.enums import MANAGED_TEST_TYPES, RegenerationGroup, SuiteType
from testgen.common.generation_set_service import (
    CONTRACT_GENERATION_SET,
    MONITOR_GENERATION_SET,
    resolve_generation_sets,
)
from testgen.common.job_context import job_context
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.utils import to_sql_timestamp

LOG = logging.getLogger("testgen")

MonitorTestType = Literal["Freshness_Trend", "Volume_Trend", "Schema_Drift"]
MonitorGenerationMode = Literal["upsert", "insert", "delete"]


@dataclasses.dataclass
class ContractGenerationResult:
    """What a contract generation did.

    ``term_count`` is the number of terms, Schema Conformance tests aside, that the generated tables
    hold afterwards. ``tables_declared`` lists the tables the generation covered,
    ``tables_not_in_catalog`` those of them the data catalog holds no columns for, and
    ``tables_not_profiled`` those of them with no results in the profiling run the generation read --
    every table when there is no profiling run to read. A table not profiled is generated from the data catalog
    alone, with no Contract-set terms. ``groups`` lists what the generation regenerated, in
    ``RegenerationGroup`` order; it leaves out tests when no table was profiled.
    """

    term_count: int
    tables_declared: list[str]
    tables_not_in_catalog: list[str]
    tables_not_profiled: list[str]
    groups: list[RegenerationGroup] = dataclasses.field(default_factory=lambda: list(RegenerationGroup))


TESTS_NEED_PROFILING = "The table group has not been profiled. Run profiling to regenerate tests."


class TestsNeedProfilingError(ValueError):
    """Tests alone were chosen for a regeneration on a table group with no profiling run."""

    def __init__(self) -> None:
        super().__init__(TESTS_NEED_PROFILING)


def parse_regeneration_groups(values: Iterable[str], has_profiling_run: bool) -> list[RegenerationGroup]:
    """The regeneration groups ``values`` names, in ``RegenerationGroup`` order.

    Raises ``ValueError`` for an unknown value, naming the accepted ones, and for no value at all;
    ``TestsNeedProfilingError`` for tests alone when the table group has no profiling run to generate
    them from.
    """
    accepted = ", ".join(f"`{group}`" for group in RegenerationGroup)
    requested = set()
    for value in values:
        try:
            requested.add(RegenerationGroup(value))
        except ValueError:
            raise ValueError(f"Unknown regeneration group `{value}`. Accepted values: {accepted}.") from None
    if not requested:
        raise ValueError(f"Select at least one regeneration group: {accepted}.")
    if requested == {RegenerationGroup.TESTS} and not has_profiling_run:
        raise TestsNeedProfilingError
    return [group for group in RegenerationGroup if group in requested]


def unprofiled_regeneration_note(table_group_name: str, groups: list[RegenerationGroup]) -> str | None:
    """What a regeneration of ``groups`` skips on a table group that has not been profiled, or None
    when it skips nothing."""
    skipped = [
        text for group, text in (
            (RegenerationGroup.TESTS, "no tests are regenerated besides schema conformance"),
            (RegenerationGroup.PROFILING, "the values profiling observed are not refreshed"),
        ) if group in groups
    ]
    if not skipped:
        return None
    return f"Table group `{table_group_name}` has not been profiled, so {' and '.join(skipped)}."


@dataclasses.dataclass
class TestTypeParams:
    test_type: str
    selection_criteria: str | None
    generation_template: str | None
    default_parm_columns: str | None
    default_parm_values: str | None
    exact_measures: list[str] | None


# Generate tests for a regular non-monitor test suite - don't use for monitors
def run_test_generation(
    test_suite_id: str | UUID,
    generation_sets: list[str] | None = None,
    test_types: list[str] | None = None,
    profile_run_id: UUID | None = None,
    table_names: list[str] | None = None,
    regenerate: list[str] | None = None,
) -> ContractGenerationResult | None:
    """Generate tests for a test suite or a contract. ``regenerate`` names the regeneration groups
    of a contract, all of them when omitted, and is refused for any other suite. Returns a
    contract's ``ContractGenerationResult``, and None for a regular suite."""
    if test_suite_id is None:
        raise ValueError("Test Suite ID was not specified")

    LOG.info(f"Starting test generation for test suite {test_suite_id}")

    LOG.info("Retrieving connection, table group, and test suite parameters")
    test_suite = TestSuite.get(test_suite_id)
    if test_suite.suite_type == SuiteType.MONITOR:
        raise ValueError("Cannot run regular test generation for monitor suite")
    if regenerate is not None and test_suite.suite_type != SuiteType.CONTRACT:
        raise ValueError("Regeneration groups apply to contracts only.")

    resolved_sets = resolve_generation_sets(test_suite, generation_sets)
    LOG.info(f"Generating tests for generation sets: {', '.join(resolved_sets)}")

    table_group = TableGroup.get(test_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)

    success = False
    result = None
    try:
        if test_suite.suite_type == SuiteType.CONTRACT:
            result = run_contract_generation(
                test_suite.id,
                table_names=table_names,
                profile_run_id=profile_run_id,
                groups=list(RegenerationGroup) if regenerate is None else regenerate,
            )
        else:
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
    return result


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


def resolve_generation_profile_run(table_group: TableGroup, finishing_run_id: UUID | None = None) -> UUID | None:
    """The profiling run test generation reads for ``table_group``, or ``None`` when it has none.

    The newest run with complete results on or before the table group's as-of date, which lags
    today by its ``profiling_delay_days``. ``finishing_run_id`` names a run that has just finished
    but is not marked complete yet, and is eligible alongside the completed ones.
    """
    return ProfilingRun.latest_readable_id(
        table_group.id, _generation_as_of_date(table_group, datetime.now(UTC)), finishing_run_id=finishing_run_id
    )


def _generation_as_of_date(table_group: TableGroup, run_date: datetime) -> datetime:
    if delay_days := table_group.profiling_delay_days:
        return run_date - timedelta(days=delay_days)
    return run_date


def _contract_context(test_suite_id: str | UUID) -> tuple[TestSuite, TableGroup, Connection]:
    test_suite = TestSuite.get(test_suite_id)
    if test_suite is None or test_suite.suite_type != SuiteType.CONTRACT:
        raise ValueError("Cannot run contract generation for a suite that is not a contract")
    table_group = TableGroup.get(test_suite.table_groups_id)
    return test_suite, table_group, Connection.get(table_group.connection_id)


def reconcile_contract_conformance(test_suite_id: str | UUID) -> None:
    """Give each table a contract's draft declares one Schema Conformance test, and remove the test
    of a table it no longer declares.

    Also stamps a term id on every term of the draft that lacks one. Needs no profiling run and
    leaves the metadata document untouched.
    """
    test_suite, table_group, connection = _contract_context(test_suite_id)
    generation = TestGeneration(connection, table_group, test_suite, [])
    generation.conformance_run()
    TestDefinition.assign_missing_term_ids(generation.version_id)


def _term_count(version_id: UUID, table_names: list[str]) -> int:
    return get_current_session().scalar(
        select(func.count()).select_from(TestDefinition).where(
            TestDefinition.version_id == version_id,
            TestDefinition.table_name.in_(table_names),
            TestDefinition.test_type.not_in(MANAGED_TEST_TYPES),
        )
    ) or 0


def run_contract_generation(
    test_suite_id: str | UUID,
    table_names: list[str] | None = None,
    profile_run_id: UUID | None = None,
    *,
    refresh_identity: bool = True,
    groups: Iterable[str] = tuple(RegenerationGroup),
) -> ContractGenerationResult:
    """Generate a contract's draft: its metadata document from the data catalog and, when the
    table group has been profiled, its terms.

    ``groups`` names what to regenerate. Raises ``ValueError`` for an empty or unknown choice, and
    ``TestsNeedProfilingError`` for tests alone with no profiling run. The fields of a group left
    out are not refreshed. Creates the draft when there is none, then:

    1. when ``table_names`` is omitted and the draft declares no tables, declares every table in
       the data catalog;
    2. with governance, and unless ``refresh_identity`` is false, refreshes the contract's
       description and tags from the table group; then declares the catalog columns of
       ``table_names`` -- or of every declared table -- refreshes their types, and refreshes the
       fields of profiling and governance when they are selected;
    3. with tests and a completed profiling run, generates the Contract set's terms for those of the
       tables the run profiled;
    4. gives each table the draft declares its Schema Conformance test, whatever ``table_names``
       or ``groups`` holds, and removes the test of a table it no longer declares;
    5. with profiling and a completed profiling run, refreshes the values profiling observed on
       each column.

    Which columns get terms, profiled values and a primary key follows the data catalog's
    excluded flag, whether or not governance refreshes the document's marker.

    Generation deletes the unlocked generated terms of the tables it covers that it did not
    produce again, so it never covers a table the run has no results for: without a profiling
    run, steps 3 and 5 are skipped entirely, and a declared table missing from the run keeps its
    terms. ``profile_run_id`` names a run that has just finished
    but is not marked complete yet. Returns a ``ContractGenerationResult`` describing the generation.

    Generation reaches the database on its own connection and commits each statement itself,
    so the document is committed before the terms are generated. A failure past that point
    leaves the document generated with the terms missing; generating again resolves it.
    """
    test_suite, table_group, connection = _contract_context(test_suite_id)
    session = get_current_session()
    run_id = resolve_generation_profile_run(table_group, finishing_run_id=profile_run_id)
    selected = parse_regeneration_groups(groups, has_profiling_run=run_id is not None)
    profiling = RegenerationGroup.PROFILING in selected

    version_id, _ = TestDefinition.resolve_write_target(test_suite.id)
    draft = SuiteVersion.get(version_id)
    document = draft.metadata_document if draft.metadata_document is not None else {}
    if table_names is None:
        table_names = contract_document.declared_tables(document) or contract_document.catalog_table_names(
            table_group.id
        )
    if refresh_identity and RegenerationGroup.GOVERNANCE in selected:
        contract_document.refresh_identity(document, table_group)
    column_counts = contract_document.refresh_tables(
        document, table_group, table_names, profiling=profiling, governance=RegenerationGroup.GOVERNANCE in selected
    )
    draft.metadata_document = document
    flag_modified(draft, "metadata_document")
    session.commit()

    profiled = contract_document.profiled_table_names(run_id, table_names) if run_id is not None else []
    if RegenerationGroup.TESTS not in selected:
        LOG.info("Tests are not selected for regeneration, so no contract terms are generated")
    elif profiled:
        LOG.info(f"Generating contract terms for {len(profiled)} declared tables")
        TestGeneration(
            connection, table_group, test_suite, [CONTRACT_GENERATION_SET], profile_run_id=run_id,
            table_names=profiled,
        ).run()
    else:
        LOG.info("No profiling results for the tables, so no contract terms are generated")
    reconcile_contract_conformance(test_suite.id)

    if profiling and run_id is not None:
        # The document was committed before generation; reload it so a write committed meanwhile
        # is not overwritten by the copy held in memory.
        session.refresh(draft)
        contract_document.fill_profiled_values(draft.metadata_document, table_group.id, run_id, table_names)
        flag_modified(draft, "metadata_document")
        session.flush()

    return ContractGenerationResult(
        term_count=_term_count(version_id, table_names),
        tables_declared=list(table_names),
        tables_not_in_catalog=[name for name in table_names if not column_counts.get(name)],
        tables_not_profiled=[name for name in table_names if name not in profiled],
        groups=[group for group in selected if group != RegenerationGroup.TESTS or profiled],
    )


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
        self.as_of_date = _generation_as_of_date(table_group, self.run_date)

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
                "SELECTION_CRITERIA": ProfileResult.apply_exact_measures(
                    test_type.selection_criteria, test_type.exact_measures
                ),
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
