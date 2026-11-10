"""Tests for ``run_test_execution``'s run-scoped referential retargeting and catalog column matching."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.row import RowMapping

from testgen.commands.queries.execute_tests_query import TestExecutionDef
from testgen.commands.run_test_execution import (
    _run_tests,
    attach_column_chars,
    resolve_query_variables,
    restore_result_identity,
    retarget_match_schema,
    retarget_read_location,
)
from testgen.common.database.column_chars import ColumnChars

pytestmark = pytest.mark.unit


def _td(**overrides) -> TestExecutionDef:
    defaults = {
        "id": uuid4(), "test_type": "Combo_Match", "schema_name": "staging_a",
        "table_name": "orders", "column_name": "customer_id", "lock_refresh": "N",
        "skip_errors": 0, "history_calculation": "NONE", "custom_query": "", "prediction": None,
        "default_parm_columns": "",
        "run_type": "CAT", "test_scope": "referential", "template": "", "measure": "COUNT(*)",
        "test_operator": ">=", "test_condition": "0",
        "baseline_ct": "", "baseline_unique_ct": "", "baseline_value": "", "baseline_value_ct": "",
        "threshold_value": "", "baseline_sum": "", "baseline_avg": "", "baseline_sd": "",
        "lower_tolerance": "", "upper_tolerance": "", "subset_condition": "", "groupby_names": "",
        "having_condition": "", "window_date_column": "", "window_days": "",
        "match_schema_name": "", "match_table_name": "", "match_column_names": "",
        "match_subset_condition": "", "match_groupby_names": "", "match_having_condition": "",
    }
    defaults.update(overrides)
    return TestExecutionDef(**defaults)


def test_retargets_the_match_schema_of_a_referential_test():
    test_def = _td(match_schema_name="staging_a", match_table_name="order_totals")

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.match_schema_name == "reference_2026_09_11"


def test_leaves_the_table_group_schema_alone():
    """The match schema override reaches referential targets only. Reading the table group's own
    tables from elsewhere is a separate override, applied by ``retarget_read_location``."""
    test_defs = [_td(schema_name="staging_a"), _td(schema_name="staging_a", table_name="customers")]

    retarget_match_schema(test_defs, "reference_2026_09_11")

    assert [td.schema_name for td in test_defs] == ["staging_a"] * 2


@pytest.mark.parametrize("empty", ["", None])
def test_leaves_an_unset_match_schema_unset(empty):
    """An absent match schema means no referential target. Filling one in would turn a test
    validation reports as incomplete into one that silently compares against the wrong table."""
    test_def = _td(match_schema_name=empty)

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.match_schema_name == empty


def test_leaves_the_stored_definition_fields_it_does_not_own():
    test_def = _td(match_schema_name="staging_a", table_name="orders", match_table_name="totals")

    retarget_match_schema([test_def], "reference_2026_09_11")

    assert test_def.table_name == "orders"
    assert test_def.match_table_name == "totals"


def test_reads_another_schema_without_changing_what_a_result_reports():
    test_def = _td(schema_name="staging_a", table_name="orders")

    retarget_read_location([test_def], schema_name="build123")

    assert test_def.source_schema == "build123"
    assert test_def.schema_name == "staging_a"
    assert test_def.table_name == "orders"


def test_maps_a_table_name_by_exact_name_and_by_pattern():
    exact, patterned = _td(table_name="orders"), _td(table_name="customers")

    retarget_read_location([exact, patterned], table_names={"orders": "build_orders", "*": "build_*"})

    assert (exact.source_table, patterned.source_table) == ("build_orders", "build_customers")
    assert (exact.table_name, patterned.table_name) == ("orders", "customers")


def test_a_schema_override_does_not_retarget_a_referential_second_table():
    """Each override is given on its own. A build table compared against its production
    counterpart needs the second table left where it is."""
    test_def = _td(match_schema_name="reference", match_table_name="orders", table_name="orders")

    retarget_read_location([test_def], schema_name="build123", table_names={"*": "build_*"})

    assert test_def.match_schema_name == "reference"
    assert test_def.match_table_name == "orders"


def test_maps_a_referential_second_table_on_its_own():
    """Retargeted in place, like the match schema, so validation checks the table the run reads
    and the result's input parameters record it."""
    test_def = _td(table_name="orders", match_table_name="orders")

    retarget_read_location([test_def], match_table_names={"*": "prod_*"})

    assert test_def.match_table_name == "prod_orders"
    assert test_def.source_table == "orders"


@pytest.mark.parametrize("empty", ["", None])
def test_gives_no_second_table_to_a_test_that_has_none(empty):
    test_def = _td(match_table_name=empty)

    retarget_read_location([test_def], match_table_names={"*": "prod_*"})

    assert test_def.match_table_name == empty


def test_without_overrides_a_test_reads_where_it_is_defined():
    test_def = _td(schema_name="staging_a", table_name="orders", match_table_name="totals")

    retarget_read_location([test_def])

    assert (test_def.source_schema, test_def.source_table) == ("staging_a", "orders")
    assert test_def.match_table_name == "totals"


def _column(name: str) -> ColumnChars:
    return ColumnChars("staging_a", "orders", name, general_type="N", column_type="bigint")


def test_a_test_finds_its_column_and_key_whatever_their_case():
    td = _td(test_type="Match_Keyed_Hash_Num", test_scope="column", column_name='"Amount"', groupby_names="ORDER_ID")

    attach_column_chars([td], [_column("amount"), _column("order_id")], '"')

    assert td.column_chars.column_name == "amount"
    assert td.column_type == "bigint"
    assert td.key_column_chars.column_name == "order_id"


def test_an_exact_name_wins_and_an_ambiguous_case_insensitive_name_matches_nothing():
    exact, ambiguous = _td(column_name="Amount"), _td(column_name="AMOUNT")

    attach_column_chars([exact, ambiguous], [_column("amount"), _column("Amount")], '"')

    assert exact.column_chars.column_name == "Amount"
    assert ambiguous.column_chars is None
    assert ambiguous.column_type is None


QUERY_COLUMNS = ("test_type", "test_definition_id", "schema_name", "table_name", "result_code")


def _returned_rows(*rows: tuple) -> list:
    """Rows shaped as ``fetch_from_db_threaded`` returns them: immutable mappings keyed by column.

    Built by running a real query rather than by hand, because the shape is the thing under test:
    a list of lists would accept both integer indexing and assignment, and the production rows
    accept neither.
    """
    selects = " UNION ALL ".join(
        "SELECT "
        + ", ".join(f"{value!r} AS {column}" for column, value in zip(QUERY_COLUMNS, row, strict=True))
        for row in rows
    )
    with create_engine("sqlite://").connect() as connection:
        return list(connection.execute(text(selects)).mappings())


def _written(row) -> list:
    """The values ``write_to_app_db`` would copy for a row, in column order.

    It reads a mapping by name and anything else positionally, so a restored row and an
    untouched one are compared the same way the writer sees them.
    """
    return [row[column] for column in QUERY_COLUMNS] if isinstance(row, RowMapping) else list(row)


def test_a_result_reports_the_schema_and_table_its_definition_carries():
    """A template renders the read location into both its FROM and the names it selects back,
    so the identity is restored before the rows are written."""
    td = _td(schema_name="staging_a", table_name="orders", read_schema_name="build123")
    rows = _returned_rows(("Dupe_Rows", str(td.id), "build123", "build_orders", "0"))

    restored = restore_result_identity(rows, QUERY_COLUMNS, [td])

    assert _written(restored[0])[2:4] == ["staging_a", "orders"]


def test_the_restored_row_keeps_every_other_value_in_the_written_order():
    td = _td(schema_name="staging_a", table_name="orders", read_table_name="build_orders")
    rows = _returned_rows(("Dupe_Rows", str(td.id), "staging_a", "build_orders", "0"))

    restored = restore_result_identity(rows, QUERY_COLUMNS, [td])

    assert _written(restored[0]) == ["Dupe_Rows", str(td.id), "staging_a", "orders", "0"]


def test_a_result_of_a_test_that_read_where_it_is_defined_is_returned_as_it_came():
    """Only a retargeted test needs restoring, so an ordinary run's rows are not rebuilt."""
    td = _td(schema_name="staging_a", table_name="orders")
    rows = _returned_rows(("Dupe_Rows", str(td.id), "staging_a", "orders", "0"))

    assert restore_result_identity(rows, QUERY_COLUMNS, [td]) is rows


def test_a_result_from_an_unknown_definition_is_left_alone():
    retargeted = _td(read_schema_name="build123")
    rows = _returned_rows(("Dupe_Rows", str(uuid4()), "build123", "build_orders", "0"))

    restored = restore_result_identity(rows, QUERY_COLUMNS, [retargeted])

    assert _written(restored[0])[2:4] == ["build123", "build_orders"]


# --- custom query variables ---


def test_a_declared_variable_takes_the_run_s_value():
    test_def = _td(custom_query="WHERE d > '{END_DATE:2026-10-10}'")

    resolve_query_variables([test_def], {"END_DATE": "2026-10-17"})

    assert test_def.custom_query == "WHERE d > '2026-10-17'"


def test_a_variable_the_run_leaves_out_takes_its_default():
    test_def = _td(custom_query="WHERE d > '{END_DATE:2026-10-10}'")

    resolve_query_variables([test_def], {"OTHER": "x"})

    assert test_def.custom_query == "WHERE d > '2026-10-10'"


def test_a_run_with_no_values_still_resolves_defaults():
    """Runs from the UI and the scheduler pass nothing, and their queries still have to run."""
    test_def = _td(custom_query="WHERE d > '{END_DATE:2026-10-10}'")

    resolve_query_variables([test_def])

    assert test_def.custom_query == "WHERE d > '2026-10-10'"


def test_a_parameter_is_left_for_the_parameter_dictionary():
    test_def = _td(custom_query="SELECT * FROM {DATA_SCHEMA}.orders")

    resolve_query_variables([test_def], {"END_DATE": "2026-10-17"})

    assert test_def.custom_query == "SELECT * FROM {DATA_SCHEMA}.orders"


def test_a_test_with_no_custom_query_is_left_alone():
    test_def = _td(custom_query="")

    resolve_query_variables([test_def], {"END_DATE": "2026-10-17"})

    assert test_def.custom_query == ""


def test_the_write_path_restores_identity_before_writing():
    """The restore is wired into the write path, not merely available to it. Without the call a
    run reading elsewhere files every result under the table it happened to read, and the
    function's own tests still pass."""
    td = _td(
        schema_name="staging_a",
        table_name="orders",
        read_schema_name="build123",
        read_table_name="build_orders",
    )
    rows = _returned_rows(("Dupe_Rows", str(td.id), "build123", "build_orders", "0"))

    sql_generator = MagicMock()
    sql_generator.template_result_columns = {"QUERY": QUERY_COLUMNS}
    sql_generator.test_results_table = "test_results"
    sql_generator.connection.effective_max_threads = 1

    with (
        patch(
            "testgen.commands.run_test_execution.fetch_from_db_threaded",
            return_value=(rows, None, {}),
        ),
        patch("testgen.commands.run_test_execution.write_to_app_db") as write_to_app_db,
        patch("testgen.commands.run_test_execution.get_current_session"),
    ):
        _run_tests(sql_generator, "QUERY", [td])

    written_rows, written_columns, _table = write_to_app_db.call_args.args
    assert written_columns == QUERY_COLUMNS
    assert _written(written_rows[0]) == ["Dupe_Rows", str(td.id), "staging_a", "orders", "0"]
