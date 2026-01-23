import dataclasses
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from testgen import settings
from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    get_flavor_service,
    replace_params,
)
from testgen.common.mixpanel_service import MixpanelService
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.utils import to_sql_timestamp

LOG = logging.getLogger("testgen")

GenerationSet = Literal["Standard", "Monitor"]
MonitorTestType = Literal["Freshness_Trend", "Volume_Trend", "Schema_Drift"]

@dataclasses.dataclass
class TestTypeParams:
    test_type: str
    selection_criteria: str | None
    generation_template: str | None
    default_parm_columns: str | None
    default_parm_values: str | None


def run_test_generation(
    test_suite_id: str | UUID,
    generation_set: GenerationSet = "Standard",
    test_types: list[MonitorTestType] | None = None,
) -> str:
    if test_suite_id is None:
        raise ValueError("Test Suite ID was not specified")

    LOG.info(f"Starting test generation for test suite {test_suite_id}")

    LOG.info("Retrieving connection, table group, and test suite parameters")
    test_suite = TestSuite.get(test_suite_id)
    table_group = TableGroup.get(test_suite.table_groups_id)
    connection = Connection.get(table_group.connection_id)

    if test_suite.is_monitor:
        generation_set = "Monitor"

    success = False
    try:
        TestGeneration(connection, table_group, test_suite, generation_set, test_types).run()
        success = True
    except Exception:
        LOG.exception("Test generation encountered an error.")
    finally:
        MixpanelService().send_event(
            "generate-tests",
            source=settings.ANALYTICS_JOB_SOURCE,
            sql_flavor=connection.sql_flavor,
            generation_set=generation_set,
        )

    return "Test generation completed." if success else "Test generation encountered an error. Check log for details."


class TestGeneration:

    def __init__(
        self,
        connection: Connection,
        table_group: TableGroup,
        test_suite: TestSuite,
        generation_set: str,
        test_types_filter: list[MonitorTestType] | None = None,
    ):
        self.connection = connection
        self.table_group = table_group
        self.test_suite = test_suite
        self.generation_set = generation_set
        self.test_types_filter = test_types_filter
        self.flavor = connection.sql_flavor
        self.flavor_service = get_flavor_service(self.flavor)

    def run(self) -> None:
        self.run_date = datetime.now(UTC)
        self.as_of_date = self.run_date
        if (delay_days := int(self.table_group.profiling_delay_days)):
            self.as_of_date = self.run_date - timedelta(days=delay_days)

        LOG.info("Retrieving active test types")
        test_types = fetch_dict_from_db(*self.get_test_types())
        test_types = [TestTypeParams(**item) for item in test_types]

        if self.test_types_filter:
            test_types = [tt for tt in test_types if tt.test_type in self.test_types_filter]

        selection_test_types = [tt for tt in test_types if tt.selection_criteria and tt.selection_criteria != "TEMPLATE"]
        template_test_types = [tt for tt in test_types if tt.generation_template]

        LOG.info("Running test generation queries")
        execute_db_queries([
            *self.generate_selection_test_types(selection_test_types),
            *self.generate_template_test_types(template_test_types),
            self.delete_old_tests(),
        ])

    def get_test_types(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("get_test_types.sql")

    def generate_selection_test_types(self, test_types: list[TestTypeParams]) -> list[tuple[str, dict]]:
        # Runs on App database
        return [self._get_query("gen_selection_tests.sql", test_type=tt) for tt in test_types]

    def generate_template_test_types(self, test_types: list[TestTypeParams]) -> list[tuple[str, dict]]:
        # Runs on App database
        queries = []
        for tt in test_types:
            template_file = tt.generation_template
            # Try flavor-specific template first, then fall back to generic
            for directory in [f"flavors/{self.flavor}/gen_query_tests", "gen_query_tests", "gen_funny_cat_tests"]:
                try:
                    queries.append(self._get_query(template_file, directory))
                    break
                except (ValueError, ModuleNotFoundError):
                    continue
            else:
                LOG.warning(f"Template file '{template_file}' not found for test type '{tt.test_type}'")
        return queries

    def delete_old_tests(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("delete_old_tests.sql")

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
            "DATA_SCHEMA": self.table_group.table_group_schema,
            "GENERATION_SET": self.generation_set,
            "TEST_TYPES_FILTER": self.test_types_filter,
            "RUN_DATE": to_sql_timestamp(self.run_date),
            "AS_OF_DATE": to_sql_timestamp(self.as_of_date),
            "SQL_FLAVOR": self.flavor,
            "QUOTE": self.flavor_service.quote_character,
        })
        return params
    
    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "generation",
        test_type: TestTypeParams | None = None,
    ) -> tuple[str, dict | None]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = self._get_params(test_type)
        query = replace_params(query, params)
        return query, params
