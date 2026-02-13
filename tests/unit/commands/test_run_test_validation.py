from uuid import uuid4

import pytest

from testgen.commands.queries.execute_tests_query import TestExecutionDef
from testgen.commands.run_test_validation import check_identifiers, collect_test_identifiers

pytestmark = pytest.mark.unit


def _make_td(**overrides) -> TestExecutionDef:
    """Build a minimal TestExecutionDef with sensible defaults."""
    defaults = dict(
        id=uuid4(),
        test_type="Alpha",
        schema_name="public",
        table_name="orders",
        column_name="amount",
        skip_errors=0,
        history_calculation="NONE",
        custom_query="",
        run_type="CAT",
        test_scope="column",
        template="",
        measure="",
        test_operator="=",
        test_condition="",
        baseline_ct="",
        baseline_unique_ct="",
        baseline_value="",
        baseline_value_ct="",
        threshold_value="",
        baseline_sum="",
        baseline_avg="",
        baseline_sd="",
        lower_tolerance="",
        upper_tolerance="",
        subset_condition="",
        groupby_names="",
        having_condition="",
        window_date_column="",
        window_days="",
        match_schema_name="",
        match_table_name="",
        match_column_names="",
        match_subset_condition="",
        match_groupby_names="",
        match_having_condition="",
    )
    defaults.update(overrides)
    return TestExecutionDef(**defaults)


# --- collect_test_identifiers ---


def test_collect_custom_type_skipped():
    td = _make_td(test_type="CUSTOM")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert len(identifiers) == 0
    assert len(schemas) == 0
    assert len(errors) == 0


def test_collect_tablegroup_scope_skipped():
    td = _make_td(test_scope="tablegroup")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert len(identifiers) == 0


def test_collect_table_scope_collects_table_only():
    td = _make_td(test_scope="table", column_name="irrelevant")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    # Should have table-level identifier (column=None), not column-level
    assert (td.schema_name.lower(), td.table_name.lower(), None) in identifiers


def test_collect_column_scope_single_column():
    td = _make_td(test_scope="column", column_name="amount")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "amount") in identifiers


def test_collect_column_scope_multi_column():
    """Multi-column scope (not single_column) should split on commas."""
    td = _make_td(test_scope="referential", column_name="col_a,col_b", match_schema_name="", match_table_name="")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "col_a") in identifiers
    assert ("public", "orders", "col_b") in identifiers


def test_collect_quoted_multi_column_parsing():
    """Columns with quoted identifiers should be parsed correctly."""
    td = _make_td(test_scope="referential", column_name='"col,a","col_b"', match_schema_name="", match_table_name="")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "col,a") in identifiers
    assert ("public", "orders", "col_b") in identifiers


def test_collect_groupby_names():
    td = _make_td(groupby_names="region,country")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "region") in identifiers
    assert ("public", "orders", "country") in identifiers


def test_collect_referential_window_date_column():
    td = _make_td(
        test_scope="referential",
        column_name="col_a",
        window_date_column="created_at",
        match_schema_name="public",
        match_table_name="customers",
        match_column_names="cust_id",
    )
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "created_at") in identifiers


def test_collect_referential_match_columns():
    td = _make_td(
        test_scope="referential",
        column_name="order_id",
        match_schema_name="public",
        match_table_name="customers",
        match_column_names="cust_id",
    )
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "customers", "cust_id") in identifiers


def test_collect_referential_match_groupby():
    td = _make_td(
        test_scope="referential",
        column_name="order_id",
        match_schema_name="public",
        match_table_name="customers",
        match_column_names="",
        match_groupby_names="region",
    )
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "customers", "region") in identifiers


def test_collect_referential_missing_match_schema_errors():
    td = _make_td(
        test_scope="referential",
        column_name="order_id",
        match_schema_name="",
        match_table_name="",
        match_column_names="cust_id",
    )
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert td.id in errors
    assert any("match schema" in e for e in errors[td.id])


def test_collect_missing_schema_or_table_errors():
    td = _make_td(schema_name="", table_name="")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert td.id in errors
    assert any("schema, table, or column not defined" in e for e in errors[td.id])


def test_collect_aggregate_type_validates_table_only():
    td = _make_td(test_type="Aggregate_Balance", test_scope="referential",
                   column_name="amount", match_schema_name="public",
                   match_table_name="customers", match_column_names="balance")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    # Table-level check for main table
    assert ("public", "orders", None) in identifiers
    # Match columns should NOT be checked for Aggregate_ types
    assert ("public", "customers", "balance") not in identifiers


def test_collect_target_schemas_populated():
    td1 = _make_td(schema_name="schema_a")
    td2 = _make_td(schema_name="schema_b")
    identifiers, schemas, errors = collect_test_identifiers([td1, td2], '"')
    assert "schema_a" in schemas
    assert "schema_b" in schemas


def test_collect_error_format_starts_with_deactivated():
    td = _make_td(schema_name="", table_name="")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert errors[td.id][0] == "Deactivated"


# --- check_identifiers ---


def test_check_all_identifiers_present():
    test_id = uuid4()
    identifiers = {("public", "orders", "amount"): {test_id}}
    tables = {("public", "orders")}
    columns = {("public", "orders", "amount")}
    errors = check_identifiers(identifiers, tables, columns)
    assert len(errors) == 0


def test_check_missing_table():
    test_id = uuid4()
    identifiers = {("public", "orders", None): {test_id}}
    tables = set()  # No tables exist
    columns = set()
    errors = check_identifiers(identifiers, tables, columns)
    assert test_id in errors
    assert any("Missing table" in e for e in errors[test_id])


def test_check_missing_column():
    test_id = uuid4()
    identifiers = {("public", "orders", "nonexistent"): {test_id}}
    tables = {("public", "orders")}
    columns = {("public", "orders", "amount")}  # different column
    errors = check_identifiers(identifiers, tables, columns)
    assert test_id in errors
    assert any("Missing column" in e for e in errors[test_id])


def test_check_table_only_identifier_passes():
    """Identifier with column=None should only check table existence."""
    test_id = uuid4()
    identifiers = {("public", "orders", None): {test_id}}
    tables = {("public", "orders")}
    columns = set()
    errors = check_identifiers(identifiers, tables, columns)
    assert len(errors) == 0


def test_check_multiple_tests_share_identifier():
    id1, id2 = uuid4(), uuid4()
    identifiers = {("public", "missing_table", None): {id1, id2}}
    tables = set()
    columns = set()
    errors = check_identifiers(identifiers, tables, columns)
    assert id1 in errors
    assert id2 in errors


def test_check_error_format_starts_with_deactivated():
    test_id = uuid4()
    identifiers = {("public", "orders", "bad_col"): {test_id}}
    tables = {("public", "orders")}
    columns = set()
    errors = check_identifiers(identifiers, tables, columns)
    assert errors[test_id][0] == "Deactivated"
