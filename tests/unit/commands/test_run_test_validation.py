from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.api_core.exceptions import NotFound
from google.cloud.bigquery.dbapi import exceptions as bigquery_dbapi
from sqlalchemy.exc import DatabaseError

from testgen.commands import run_test_validation as run_test_validation_module
from testgen.commands.queries.execute_tests_query import TestExecutionDef
from testgen.commands.run_test_validation import (
    check_column_types,
    check_identifiers,
    check_value_lists,
    collect_test_identifiers,
    get_target_identifiers,
    run_test_validation,
)
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.bigquery_flavor_service import BigqueryFlavorService
from testgen.common.database.flavor.postgresql_flavor_service import PostgresqlFlavorService

pytestmark = pytest.mark.unit


def _make_td(**overrides) -> TestExecutionDef:
    """Build a minimal TestExecutionDef with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "test_type": "Alpha",
        "schema_name": "public",
        "table_name": "orders",
        "column_name": "amount",
        "lock_refresh": "N",
        "skip_errors": 0,
        "history_calculation": "NONE",
        "default_parm_columns": "",
        "custom_query": "",
        "prediction": None,
        "run_type": "CAT",
        "test_scope": "column",
        "template": "",
        "measure": "COUNT(*)",
        "test_operator": "=",
        "test_condition": "",
        "baseline_ct": "",
        "baseline_unique_ct": "",
        "baseline_value": "",
        "baseline_value_ct": "",
        "threshold_value": "",
        "baseline_sum": "",
        "baseline_avg": "",
        "baseline_sd": "",
        "lower_tolerance": "",
        "upper_tolerance": "",
        "subset_condition": "",
        "groupby_names": "",
        "having_condition": "",
        "window_date_column": "",
        "window_days": "",
        "match_schema_name": "",
        "match_table_name": "",
        "match_column_names": "",
        "match_subset_condition": "",
        "match_groupby_names": "",
        "match_having_condition": "",
    }
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


def test_collect_skips_a_managed_test():
    """A managed test reads the app database's catalog, so a table missing from the target is
    what it reports, not a reason to error it before it runs."""
    td = _make_td(test_type="Schema_Conformance", run_type="METADATA", test_scope="table", column_name=None)
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert identifiers == {}
    assert errors == {}


def test_collect_validates_an_unmanaged_metadata_test():
    td = _make_td(test_type="Match_Column_Type", run_type="METADATA", test_scope="column", column_name="amount")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert ("public", "orders", "amount") in identifiers


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


def test_collect_cat_type_without_a_measure_for_the_flavor_errors():
    td = _make_td(measure=None)
    identifiers, _schemas, errors = collect_test_identifiers([td], '"')
    assert errors[td.id] == ["Invalid test: test type not available for this connection type"]
    assert not identifiers


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


def test_collect_errors_carry_no_outcome_prefix():
    td = _make_td(schema_name="", table_name="")
    identifiers, schemas, errors = collect_test_identifiers([td], '"')
    assert errors[td.id] == ["Invalid test: schema, table, or column not defined"]


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


def test_check_errors_carry_no_outcome_prefix():
    test_id = uuid4()
    identifiers = {("public", "orders", "bad_col"): {test_id}}
    tables = {("public", "orders")}
    columns = set()
    errors = check_identifiers(identifiers, tables, columns)
    assert errors[test_id] == ["Missing column: public.orders.bad_col"]


# --- check_column_types ---


def _column(general_type: str | None, db_data_type: str = "text", column_name: str = "amount") -> ColumnChars:
    return ColumnChars(
        schema_name="public",
        table_name="orders",
        column_name=column_name,
        general_type=general_type,
        column_type=db_data_type,
        db_data_type=db_data_type,
    )


def test_check_types_reports_a_column_whose_general_type_changed():
    td = _make_td(test_type="Match_True_Ct", column_general_types=["B"])
    errors = check_column_types([td], [_column("A")], '"')
    assert errors == {
        td.id: ["Column type changed: public.orders.amount is now text. This test applies to Boolean columns."]
    }


@pytest.mark.parametrize(
    ("codes", "label"),
    [
        (["A", "N"], "Alpha or Numeric columns"),
        (["A", "N", "D"], "Alpha, Numeric or Datetime columns"),
    ],
)
def test_check_types_lists_every_general_type_the_test_applies_to(codes, label):
    td = _make_td(column_general_types=codes)
    errors = check_column_types([td], [_column("B", "boolean")], '"')
    assert errors[td.id][0].endswith(f"This test applies to {label}.")


def test_check_types_names_the_type_as_the_target_reports_it():
    td = _make_td(column_general_types=["N"])
    column = _column("A", db_data_type="text")
    column.column_type = "varchar(65535)"
    errors = check_column_types([td], [column], '"')
    assert "is now text." in errors[td.id][0]


def test_check_types_passes_a_declared_general_type():
    td = _make_td(column_general_types=["B", "N"])
    assert check_column_types([td], [_column("N", "integer")], '"') == {}


@pytest.mark.parametrize("general_type", [None, "X"])
def test_check_types_skips_a_column_of_unknown_or_other_type(general_type):
    td = _make_td(column_general_types=["N"])
    assert check_column_types([td], [_column(general_type)], '"') == {}


def test_check_types_skips_a_test_type_that_declares_nothing():
    td = _make_td(column_general_types=None)
    assert check_column_types([td], [_column("A")], '"') == {}


def test_check_types_skips_a_column_absent_from_the_catalog():
    td = _make_td(column_general_types=["N"])
    assert check_column_types([td], [_column("A", column_name="other")], '"') == {}


@pytest.mark.parametrize("test_scope", ["table", "referential", "custom"])
def test_check_types_checks_only_column_scope_tests(test_scope):
    td = _make_td(test_scope=test_scope, column_general_types=["N"])
    assert check_column_types([td], [_column("A")], '"') == {}


def test_check_types_skips_a_test_that_already_failed_validation():
    td = _make_td(column_general_types=["N"])
    td.errors = ["Missing column: public.orders.amount"]
    assert check_column_types([td], [_column("A")], '"') == {}


def test_check_types_matches_names_without_case_or_quotes():
    td = _make_td(schema_name="PUBLIC", table_name="Orders", column_name='"Amount"', column_general_types=["N"])
    errors = check_column_types([td], [_column("A")], '"')
    assert td.id in errors


def test_check_types_prefers_the_column_whose_name_matches_exactly():
    td = _make_td(column_name="Amount", column_general_types=["N"])
    catalog = [_column("A", column_name="AMOUNT"), _column("N", db_data_type="numeric", column_name="Amount")]
    assert check_column_types([td], catalog, '"') == {}


def test_check_types_skips_a_name_that_matches_several_columns_only_without_case():
    """Columns whose names differ only by case cannot be told apart, so neither is checked."""
    td = _make_td(column_name="amount", column_general_types=["N"])
    catalog = [_column("A", column_name="AMOUNT"), _column("A", column_name="Amount")]
    assert check_column_types([td], catalog, '"') == {}


# --- check_value_lists ---


@pytest.mark.parametrize("test_type", ["LOV_Match", "LOV_All"])
def test_check_value_lists_reports_a_non_number_listed_for_a_numeric_column(test_type):
    td = _make_td(test_type=test_type, baseline_value='1,2,"3,4"')
    errors = check_value_lists([td], [_column("N", "integer")], '"')
    assert errors == {td.id: ["List of Expected Values contains a value that is not a number: 3,4."]}


def test_check_value_lists_passes_numbers_listed_for_a_numeric_column():
    td = _make_td(test_type="LOV_All", baseline_value=" 1, 2.50,-3,1e2")
    assert check_value_lists([td], [_column("N", "integer")], '"') == {}


@pytest.mark.parametrize("general_type", ["A", "D", None])
def test_check_value_lists_accepts_any_text_for_other_columns(general_type):
    td = _make_td(test_type="LOV_Match", baseline_value="a,b")
    assert check_value_lists([td], [_column(general_type)], '"') == {}


def test_check_value_lists_skips_a_column_absent_from_the_catalog():
    td = _make_td(test_type="LOV_Match", baseline_value="a,b")
    assert check_value_lists([td], [_column("N", column_name="other")], '"') == {}


def test_check_value_lists_checks_only_value_list_types():
    td = _make_td(test_type="Constant", baseline_value="abc")
    assert check_value_lists([td], [_column("N", "integer")], '"') == {}


def test_check_value_lists_skips_a_test_that_already_failed_validation():
    td = _make_td(test_type="LOV_Match", baseline_value="a", errors=["Missing table: public.orders"])
    assert check_value_lists([td], [_column("N", "integer")], '"') == {}


# --- run_test_validation persistence ---


def _validation_harness(monkeypatch, column_chars=None, td=None, target=(set(), set()), **kwargs):
    """Run validation over one test def (by default, one whose table is absent from the target), capturing writes."""
    sql_generator = MagicMock()
    sql_generator.flavor_service.quote_character = '"'
    sql_generator.get_test_errors.side_effect = lambda tds: [[". ".join(td.errors)] for td in tds if td.errors]

    monkeypatch.setattr(run_test_validation_module, "get_target_identifiers", lambda *_: target)
    written = MagicMock()
    executed = MagicMock()
    monkeypatch.setattr(run_test_validation_module, "write_to_app_db", written)
    monkeypatch.setattr(run_test_validation_module, "execute_db_queries", executed)

    td = td or _make_td()
    valid = run_test_validation(sql_generator, [td], column_chars, **kwargs)
    return td, valid, written, executed


def test_validation_deactivates_failing_definitions_by_default(monkeypatch):
    td, valid, written, executed = _validation_harness(monkeypatch)

    assert valid == []
    assert written.called
    assert executed.called
    assert td.errors == ["Deactivated", "Missing table: public.orders"]


def test_validation_keeps_failing_definitions_active_when_asked(monkeypatch):
    td, valid, written, executed = _validation_harness(monkeypatch, deactivate_invalid=False)

    assert valid == []
    assert written.called
    assert not executed.called
    assert td.errors == ["Missing table: public.orders"]


def test_validation_defers_every_side_effect_when_deferring_persistence(monkeypatch):
    td, _, written, executed = _validation_harness(monkeypatch, defer_persistence=True)

    assert not written.called
    assert not executed.called
    assert td.errors == ["Missing table: public.orders"]


def test_validation_reports_a_column_type_change(monkeypatch):
    present = ({("public", "orders")}, {("public", "orders", "amount")})
    td, valid, written, executed = _validation_harness(
        monkeypatch,
        column_chars=[_column("A")],
        td=_make_td(column_general_types=["N"]),
        target=present,
        deactivate_invalid=False,
    )

    assert valid == []
    assert td.errors == [
        "Column type changed: public.orders.amount is now text. This test applies to Numeric columns."
    ]
    assert not executed.called


def test_validation_passes_a_test_whose_column_fits(monkeypatch):
    present = ({("public", "orders")}, {("public", "orders", "amount")})
    td, valid, written, executed = _validation_harness(
        monkeypatch,
        column_chars=[_column("N", "integer")],
        td=_make_td(column_general_types=["N"]),
        target=present,
    )

    assert valid == [td]
    assert not written.called


def test_validation_reports_a_non_number_in_a_numeric_value_list(monkeypatch):
    present = ({("public", "orders")}, {("public", "orders", "amount")})
    td, valid, _, _ = _validation_harness(
        monkeypatch,
        column_chars=[_column("N", "integer")],
        td=_make_td(test_type="LOV_Match", baseline_value="1,x"),
        target=present,
    )

    assert valid == []
    assert td.errors == ["Deactivated", "List of Expected Values contains a value that is not a number: x."]


# --- get_target_identifiers ---


def _bigquery_error(message: str) -> DatabaseError:
    """A query error shaped the way the BigQuery driver reports an API error through SQLAlchemy."""
    return DatabaseError("SELECT 1", {}, bigquery_dbapi.DatabaseError(NotFound(message)))


QUERY_REQUEST = "POST https://bigquery.googleapis.com/bigquery/v2/projects/proj/queries?prettyPrint=false"
MISSING_DATASET = _bigquery_error(f"{QUERY_REQUEST}: Not found: Dataset proj:absent was not found in location US")


def _target_identifiers(monkeypatch, flavor_service, results: dict):
    """Read target identifiers for every schema in ``results``, each returning its rows or raising its error."""
    sql_generator = MagicMock()
    sql_generator.flavor_service = flavor_service
    sql_generator.get_target_identifiers.side_effect = lambda schema: (schema, None)

    def fetch(schema, _params, use_target_db):
        assert use_target_db
        if isinstance(results[schema], Exception):
            raise results[schema]
        return results[schema]

    monkeypatch.setattr(run_test_validation_module, "fetch_dict_from_db", fetch)
    return get_target_identifiers(sql_generator, set(results))


def test_target_identifiers_skip_a_schema_the_target_reports_missing(monkeypatch):
    tables, columns = _target_identifiers(
        monkeypatch,
        BigqueryFlavorService(),
        {
            "present": [{"schema_name": "present", "table_name": "orders", "column_name": "amount"}],
            "absent": MISSING_DATASET,
        },
    )

    assert tables == {("present", "orders")}
    assert columns == {("present", "orders", "amount")}


def test_target_identifiers_raise_any_other_query_error(monkeypatch):
    denied = DatabaseError("SELECT 1", {}, bigquery_dbapi.DatabaseError(Exception("Access Denied")))

    with pytest.raises(DatabaseError):
        _target_identifiers(monkeypatch, BigqueryFlavorService(), {"present": [], "denied": denied})


def test_target_identifiers_raise_a_missing_schema_error_on_a_flavor_that_reports_none(monkeypatch):
    with pytest.raises(DatabaseError):
        _target_identifiers(monkeypatch, PostgresqlFlavorService(), {"absent": MISSING_DATASET})


@pytest.mark.parametrize(
    "error, expected",
    [
        (MISSING_DATASET, True),
        (_bigquery_error("Not found: Dataset proj:absent was not found in location US\n\nLocation: US\nJob ID: x\n"), True),
        (_bigquery_error(f"{QUERY_REQUEST}: Not found: Project proj"), False),
        (_bigquery_error(f"{QUERY_REQUEST}: Not found: Table proj:ds.orders was not found in location US"), False),
        (DatabaseError("SELECT 1", {}, bigquery_dbapi.DatabaseError("Not found: Dataset proj:absent")), False),
    ],
)
def test_bigquery_recognizes_only_a_missing_dataset(error, expected):
    assert BigqueryFlavorService().is_missing_schema_error(error) is expected
