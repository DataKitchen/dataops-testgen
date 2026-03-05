import logging
import re
from uuid import UUID

from testgen.commands.queries.execute_tests_query import TestExecutionDef, TestExecutionSQL
from testgen.common import execute_db_queries, fetch_dict_from_db
from testgen.common.database.database_service import write_to_app_db

LOG = logging.getLogger("testgen")


def collect_test_identifiers(
    test_defs: list[TestExecutionDef],
    quote_char: str,
) -> tuple[dict[tuple[str, str, str | None], set[UUID]], set[str], dict[UUID, list[str]]]:
    """Collect identifiers (schema, table, column) that need validation from test definitions.

    Returns:
        identifiers_to_check: {(schema, table, column|None): {test_ids}}
        target_schemas: set of schemas to query
        errors: {test_id: [error_messages]}
    """
    identifiers_to_check: dict[tuple[str, str, str | None], set[UUID]] = {}
    target_schemas: set[str] = set()
    errors: dict[UUID, list[str]] = {}

    def add_identifiers(test_id: UUID, schema: str, table: str, columns: str | None = None, single_column: bool = False) -> None:
        target_schemas.add(schema)
        if columns:
            if single_column:
                identifiers = [(schema.lower(), table.lower(), columns.strip(f" {quote_char}").lower())]
            else:
                column_names = re.split(rf",(?=(?:[^\{quote_char}]*\{quote_char}[^\{quote_char}]*\{quote_char})*[^\{quote_char}]*$)", columns)
                column_names = [col.strip(f" {quote_char}") for col in column_names]
                identifiers = [(schema.lower(), table.lower(), col.lower()) for col in column_names if col]
        else:
            identifiers = [(schema.lower(), table.lower(), None)]

        for key in identifiers:
            if not identifiers_to_check.get(key):
                identifiers_to_check[key] = set()
            identifiers_to_check[key].add(test_id)

    def add_error(test_id: UUID, error: str) -> None:
        if test_id not in errors:
            errors[test_id] = ["Deactivated"]
        errors[test_id].append(error)

    for td in test_defs:
        # No validation needed for custom query or table group tests
        if td.test_type == "CUSTOM" or td.test_scope == "tablegroup":
            continue

        if td.schema_name and td.table_name and (td.column_name or td.test_scope in ["table", "custom"]):
            if td.test_scope in ["table", "custom"] or td.test_type.startswith("Aggregate_"):
                # Validate only table for these test types - column is meaningless or uses aggregation functions
                add_identifiers(td.id, td.schema_name, td.table_name)
            else:
                add_identifiers(td.id, td.schema_name, td.table_name, td.column_name, single_column=td.test_scope == "column")

            if td.groupby_names:
                add_identifiers(td.id, td.schema_name, td.table_name, td.groupby_names)

            if td.test_scope == "referential":
                if td.window_date_column:
                    add_identifiers(td.id, td.schema_name, td.table_name, td.window_date_column)

                if td.match_column_names or td.match_groupby_names:
                    if td.match_schema_name and td.match_table_name:
                        if td.match_column_names and not td.test_type.startswith("Aggregate_"):
                            add_identifiers(td.id, td.match_schema_name, td.match_table_name, td.match_column_names)
                        if td.match_groupby_names:
                            add_identifiers(td.id, td.match_schema_name, td.match_table_name, td.match_groupby_names)
                    else:
                        add_error(td.id, "Invalid test: match schema, table, or column not defined")
        else:
            add_error(td.id, "Invalid test: schema, table, or column not defined")

    return identifiers_to_check, target_schemas, errors


def check_identifiers(
    identifiers_to_check: dict[tuple[str, str, str | None], set[UUID]],
    target_tables: set[tuple[str, str]],
    target_columns: set[tuple[str, str, str]],
) -> dict[UUID, list[str]]:
    """Check collected identifiers against actual target tables/columns.

    Returns {test_id: [error_messages]} for identifiers that don't exist.
    """
    errors: dict[UUID, list[str]] = {}

    for identifier, test_ids in identifiers_to_check.items():
        table = (identifier[0], identifier[1])
        if table not in target_tables:
            error = f"Missing table: {'.'.join(table)}"
        elif identifier[2] and identifier not in target_columns:
            error = f"Missing column: {'.'.join(identifier)}"
        else:
            continue

        for test_id in test_ids:
            if test_id not in errors:
                errors[test_id] = ["Deactivated"]
            errors[test_id].append(error)

    return errors


def run_test_validation(sql_generator: TestExecutionSQL, test_defs: list[TestExecutionDef]) -> list[TestExecutionDef]:
    quote = sql_generator.flavor_service.quote_character

    identifiers_to_check, target_schemas, collection_errors = collect_test_identifiers(test_defs, quote)

    # Apply collection errors to test defs
    test_defs_by_id: dict[UUID, TestExecutionDef] = {td.id: td for td in test_defs}
    for test_id, error_list in collection_errors.items():
        test_defs_by_id[test_id].errors = error_list

    if target_schemas:
        LOG.info("Getting tables and columns in target schemas for validation")
        target_identifiers = fetch_dict_from_db(
            *sql_generator.get_target_identifiers(target_schemas),
            use_target_db=True,
        )
        if not target_identifiers:
            LOG.info("No tables or columns present in target schemas")

        # Normalize identifiers before validating
        target_tables = {(item["schema_name"].lower(), item["table_name"].lower()) for item in target_identifiers}
        target_columns = {
            (item["schema_name"].lower(), item["table_name"].lower(), item["column_name"].lower())
            for item in target_identifiers
        }

        check_errors = check_identifiers(identifiers_to_check, target_tables, target_columns)
        for test_id, error_list in check_errors.items():
            if not test_defs_by_id[test_id].errors:
                test_defs_by_id[test_id].errors = error_list
            else:
                # Skip "Deactivated" prefix since it's already there from collection_errors or we add it
                test_defs_by_id[test_id].errors.extend(error_list[1:] if test_defs_by_id[test_id].errors else error_list)

    error_results = sql_generator.get_test_errors(test_defs_by_id.values())
    if error_results:
        LOG.warning(f"Tests in test suite failed validation: {len(error_results)}")
        LOG.info("Writing test validation errors to test results")
        write_to_app_db(error_results, sql_generator.result_columns, sql_generator.test_results_table)

        LOG.info("Disabling tests in test suite that failed validation")
        execute_db_queries([sql_generator.disable_invalid_test_definitions()])
    else:
        LOG.info("No tests in test suite failed validation")

    return [td for td in test_defs if not td.errors]
