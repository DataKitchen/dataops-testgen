"""The record subset condition of the aggregate (CAT) test types.

A test with a subset must produce what the same test without one produces on a table holding only the
subset's records. The DuckDB cases run every in-scope type's measure and source-data lookup both ways.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import duckdb
import pytest
import sqlglot
from sqlglot import exp
from yaml import safe_load

import testgen
from testgen.commands.queries.execute_tests_query import ROW_LEVEL_PARAMS, TestExecutionDef, TestExecutionSQL
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service
from testgen.common.models.connection import Connection
from testgen.common.source_data_service import _build_query_standard

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"
HELP = "Condition selecting the records to test, written like a SQL WHERE clause. Example: status = 'SHIPPED'."
SUBSET = "status = 'SHIPPED' OR status IS NULL"
# A correlated subquery naming the tested table; some databases reject a subquery inside an aggregate
SUBQUERY_SUBSET = "EXISTS (SELECT 1 FROM s.open_statuses o WHERE o.status = src.status)"
# Each subset, and the table holding only the records it selects
SUBSETS = {"condition": (SUBSET, "sub"), "subquery": (SUBQUERY_SUBSET, "sub_open")}


def _load_types() -> dict[str, dict]:
    return {
        test_type["test_type"]: test_type
        for path in sorted(YAML_DIR.glob("*.yaml"))
        if (test_type := safe_load(path.read_text())["test_types"]).get("run_type") == "CAT"
    }


CAT_TYPES = _load_types()
# Table comparison types compare a whole table with a source profile; custom-query types filter in their own query.
IN_SCOPE = sorted(
    name
    for name, test_type in CAT_TYPES.items()
    if not name.startswith("Match_")
    and not any("{CUSTOM_QUERY}" in condition["measure"] for condition in test_type["cat_test_conditions"])
)
# Parameters a measure may read that do not vary by record
RECORD_INDEPENDENT_PARAMS = {
    "BASELINE_AVG", "BASELINE_CT", "BASELINE_SD", "BASELINE_SUM", "BASELINE_UNIQUE_CT", "BASELINE_VALUE",
    "BASELINE_VALUE_CT", "BASELINE_VALUE_LIST", "COLUMN_TYPE", "LOWER_TOLERANCE", "RUN_DATE", "THRESHOLD_VALUE",
    "UPPER_TOLERANCE", "VALUE_LIST_CT", "VALUE_LIST_LITERALS", "VARCHAR_TYPE", "SUBSET_ROW",
}


def _params(test_type: dict) -> list[str]:
    return test_type["default_parm_columns"].split(",")


def test_in_scope_types_are_the_aggregate_column_and_table_types():
    assert len(IN_SCOPE) == 40
    assert {"Required", "Row_Ct", "LOV_All", "Required_No_Placeholder", "Valid_Month"} <= set(IN_SCOPE)


@pytest.mark.parametrize("name", IN_SCOPE)
def test_in_scope_type_takes_an_optional_subset_after_its_other_parameters(name):
    test_type = CAT_TYPES[name]
    position = len(_params(test_type)) - 1
    assert _params(test_type)[position] == "subset_condition"
    assert test_type["default_parm_prompts"].split(",")[position] == "Record Subset Condition"
    assert test_type["default_parm_help"].split("|")[position] == HELP
    assert test_type["default_parm_required"].split(",")[position] == "N"
    if test_type["default_parm_values"] is not None:
        assert test_type["default_parm_values"].endswith(",NULL")


@pytest.mark.parametrize("name", sorted(set(CAT_TYPES) - set(IN_SCOPE) - {"Volume_Trend"}))
def test_out_of_scope_type_takes_no_subset(name):
    assert "subset_condition" not in _params(CAT_TYPES[name])


@pytest.mark.parametrize("name", IN_SCOPE)
def test_measure_reads_records_only_through_the_subset_aware_parameters(name):
    for condition in CAT_TYPES[name]["cat_test_conditions"]:
        measure = condition["measure"]
        assert not re.search(r"COUNT\(\s*(\*|1)\s*\)", measure, re.IGNORECASE), condition["sql_flavor"]
        read = set(re.findall(r"\{(\w+)\}", measure))
        assert read <= RECORD_INDEPENDENT_PARAMS | set(ROW_LEVEL_PARAMS), (condition["sql_flavor"], read)


@pytest.mark.parametrize("name", [name for name in IN_SCOPE if CAT_TYPES[name].get("target_data_lookups")])
def test_lookup_filters_every_read_of_the_table(name):
    for lookup in CAT_TYPES[name]["target_data_lookups"]:
        query = lookup["lookup_query"]
        filters = len(re.findall(r"\{SUBSET_(?:WHERE|AND)\}", query))
        assert filters == query.count("{TABLE_NAME}"), lookup["sql_flavor"]


# --- DuckDB: a subset test on the table measures what the same test measures on the subset's records ---

ROWS = [  # status, amount, code, d
    ("SHIPPED", 1.5, "A", "2024-01-01"),
    ("SHIPPED", 2.25, "B", "2024-01-02"),
    ("SHIPPED", 2.25, "A", "2024-01-04"),
    ("SHIPPED", None, None, "2024-01-05"),
    ("SHIPPED", 4.0, "n/a", None),
    ("SHIPPED", 3.0, "", "2024-01-09"),
    ("SHIPPED", 5.0, "A", "2026-08-01"),
    ("SHIPPED", 2.0, '"q"', "2024-01-07"),
    (None, 2.0, "B", "2024-01-03"),
    ("OPEN", 99.125, "C", "2023-11-20"),
    ("OPEN", 50.0, None, "2024-03-15"),
    ("OPEN", None, None, "2030-01-01"),
    ("OPEN", -7.0, "zz top", "2024-02-29"),
    ("OPEN", 1.5, "C", "2024-01-01"),
]
COLUMNS = {
    "amount": ColumnChars("s", "src", "amount", general_type="N", column_type="decimal(18,4)"),
    "code": ColumnChars("s", "src", "code", general_type="A", column_type="varchar"),
    "d": ColumnChars("s", "src", "d", general_type="D", column_type="date"),
}
DATE_TYPES = {
    "Daily_Record_Ct", "Distinct_Date_Ct", "Future_Date", "Future_Date_1Y", "Max_Date", "Min_Date",
    "Monthly_Rec_Ct", "Recency", "Weekly_Rec_Ct",
}
# Parameters chosen so each type's lookup shows records of the subset
PARAMETERS = {
    "Alpha_Trunc": {"threshold_value": "10"},
    "Constant": {"baseline_value": "2.25"},
    "Distinct_Date_Ct": {"baseline_value": "3"},
    "Future_Date": {"threshold_value": "0"},
    "Future_Date_1Y": {"threshold_value": "0"},
    # Every value occurs in the table; C and zz top occur only outside the subset
    "LOV_All": {"baseline_value": 'A,B,C,n/a,"",zz top,"""q"""'},
    "LOV_Match": {"baseline_value": "A,B,C"},
    "Max_Date": {"baseline_value": "2024-01-03"},
    "Max_Val": {"baseline_value": "2"},
    "Min_Date": {"baseline_value": "2024-01-02"},
    "Min_Val": {"baseline_value": "2"},
    "Outlier_Pct_Above": {"baseline_avg": "2", "baseline_sd": "0.5"},
    "Outlier_Pct_Below": {"baseline_avg": "3", "baseline_sd": "0.5"},
    "Pattern_Match": {"baseline_value": "^[A-Z]$"},
    # The subset's latest date is past the run date, and the table's is later still
    "Recency": {"threshold_value": "-1000"},
    "Required_No_Placeholder": {"baseline_value": 'n/a,""'},
    "Row_Ct": {"threshold_value": "100"},
    "Valid_Month": {"baseline_value": "'A','B'"},
}
RUN_DATE = datetime(2024, 6, 1, 12, tzinfo=UTC)


def _column(name: str) -> str | None:
    test_type = CAT_TYPES[name]
    if test_type["test_scope"] == "table":
        return None
    if name in DATE_TYPES:
        return "d"
    measures = " ".join(condition["measure"] for condition in test_type["cat_test_conditions"])
    return "amount" if "{COLUMN_NUM}" in measures else "code"


def _test_def(name: str, table: str, subset: str | None) -> TestExecutionDef:
    column = _column(name)
    condition = next(c for c in CAT_TYPES[name]["cat_test_conditions"] if c["sql_flavor"] == "duckdb")
    parameters = {
        "baseline_ct": "10", "baseline_unique_ct": "5", "baseline_value": None, "baseline_value_ct": "8",
        "threshold_value": "1", "baseline_sum": "20", "baseline_avg": "5", "baseline_sd": "2",
        "lower_tolerance": "1", "upper_tolerance": "3", **PARAMETERS.get(name, {}),
    }
    test_def = TestExecutionDef(
        id=uuid4(), test_type=name, schema_name="s", table_name=table, column_name=column, lock_refresh="N",
        skip_errors=0, history_calculation=None, custom_query=None, default_parm_columns="",
        prediction=None, run_type="CAT",
        test_scope=CAT_TYPES[name]["test_scope"], template="", measure=condition["measure"],
        test_operator=condition["test_operator"], test_condition=condition["test_condition"],
        subset_condition=subset, groupby_names=None, having_condition=None, window_date_column=None,
        window_days=None, match_schema_name=None, match_table_name=None, match_column_names=None,
        match_subset_condition=None, match_groupby_names=None, match_having_condition=None, **parameters,
    )
    if column:
        test_def.column_type = COLUMNS[column].column_type
        test_def.column_chars = COLUMNS[column]
    return test_def


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect()
    connection.execute("CREATE SCHEMA s")
    connection.execute("CREATE TABLE s.src (status VARCHAR, amount DECIMAL(18,4), code VARCHAR, d DATE)")
    connection.executemany("INSERT INTO s.src VALUES (?, ?, ?, ?)", ROWS)
    connection.execute(f"CREATE TABLE s.sub AS SELECT * FROM s.src WHERE {SUBSET}")
    connection.execute("CREATE TABLE s.open_statuses AS SELECT 'OPEN' AS status")
    connection.execute("CREATE TABLE s.sub_open AS SELECT * FROM s.src WHERE status = 'OPEN'")
    yield connection
    connection.close()


def _execution_sql() -> TestExecutionSQL:
    instance = TestExecutionSQL.__new__(TestExecutionSQL)
    instance.connection = Connection(sql_flavor="duckdb", sql_flavor_code="duckdb", max_query_chars=1_000_000)
    instance.flavor = "duckdb"
    instance.flavor_service = get_flavor_service("duckdb")
    instance.table_group = MagicMock(id=uuid4())
    instance.test_run = MagicMock(test_suite_id=uuid4(), id=uuid4(), version_id=uuid4())
    instance.run_date = RUN_DATE
    return instance


def _measures(con, test_defs: list[TestExecutionDef]) -> list[str]:
    queries, groups = _execution_sql().aggregate_cat_tests(test_defs)
    measures = []
    for (query, _), group in zip(queries, groups, strict=True):
        row = con.execute(query.replace("\\:", ":")).fetchone()
        measures += row[1].split("~^~")[: len(group)]
    return measures


def _same(left: str, right: str) -> bool:
    try:
        return abs(float(left) - float(right)) < 1e-9
    except ValueError:
        return left == right


def test_subset_and_whole_table_tests_share_one_query(con):
    test_defs = [_test_def(name, "src", subset) for name in IN_SCOPE for subset in (SUBSET, SUBQUERY_SUBSET, None)]
    queries, groups = _execution_sql().aggregate_cat_tests(test_defs)
    assert len(queries) == 1
    assert len(groups[0]) == len(test_defs)
    assert len(_measures(con, test_defs)) == len(test_defs)


@pytest.mark.parametrize("subset", SUBSETS)
@pytest.mark.parametrize("name", IN_SCOPE)
def test_subset_measure_matches_the_measure_of_the_subset_records(con, name, subset):
    condition, records = SUBSETS[subset]
    on_table, on_subset_records = _measures(con, [_test_def(name, "src", condition), _test_def(name, records, None)])
    assert _same(on_table, on_subset_records), (on_table, on_subset_records)


@pytest.mark.parametrize(
    ("name", "on_subset", "on_table"),
    [
        ("Required", "1", "3"),
        ("Row_Ct", "9", "14"),
        # An expected value that occurs only outside the subset counts as missing
        ("LOV_All", "2", "0"),
        ("Max_Val", "5", "7"),
        ("Required_No_Placeholder", "3", "5"),
    ],
)
def test_subset_changes_the_measure(con, name, on_subset, on_table):
    with_subset, without = _measures(con, [_test_def(name, "src", SUBSET), _test_def(name, "src", None)])
    assert (with_subset, without) == (on_subset, on_table)


def test_required_no_placeholder_counts_nulls_and_placeholders_once(con):
    (measure,) = _measures(con, [_test_def("Required_No_Placeholder", "src", None)])
    expected = con.execute("SELECT COUNT(*) FROM s.src WHERE code IS NULL OR code IN ('n/a', '')").fetchone()[0]
    assert int(measure) == expected


def test_required_no_placeholder_is_null_on_an_empty_table(con):
    con.execute("CREATE TABLE s.empty AS SELECT * FROM s.src LIMIT 0")
    (measure,) = _measures(con, [_test_def("Required_No_Placeholder", "empty", None)])
    assert measure == "<NULL>"


def _lookup(name: str, table: str, subset: str | None, flavor: str = "duckdb") -> str:
    test_def = _test_def(name, table, subset)
    lookup = next(lk for lk in CAT_TYPES[name]["target_data_lookups"] if lk["sql_flavor"] == flavor)
    definition = SimpleNamespace(
        **{field: getattr(test_def, field) for field in TestExecutionDef.__dataclass_fields__},
    )
    definition.test_type = name
    issue_data = {
        "table_groups_id": uuid4(), "test_type_id": "1", "test_definition_id": uuid4(), "schema_name": "s",
        "table_name": table, "column_names": test_def.column_name, "column_type": test_def.column_type,
        "test_date": "2024-06-01 12:00:00", "input_parameters": "",
    }
    module = "testgen.common.source_data_service"
    with (
        patch(f"{module}._get_lookup_data", return_value=SimpleNamespace(lookup_query=lookup["lookup_query"], sql_flavor=flavor)),
        patch(f"{module}.TestDefinition.get_for_project", return_value=definition),
        patch(f"{module}.DataTable.list_column_chars", return_value=[
            ColumnChars("s", table, chars.column_name, general_type=chars.general_type, column_type=chars.column_type)
            for chars in COLUMNS.values()
        ]),
    ):
        return _build_query_standard(issue_data, limit=100_000)


@pytest.mark.parametrize("subset", SUBSETS)
@pytest.mark.parametrize("name", [name for name in IN_SCOPE if CAT_TYPES[name].get("target_data_lookups")])
def test_subset_lookup_shows_what_the_lookup_shows_on_the_subset_records(con, name, subset):
    condition, records = SUBSETS[subset]
    on_table = con.execute(_lookup(name, "src", condition)).fetchall()
    on_subset_records = con.execute(_lookup(name, records, None)).fetchall()
    assert sorted(map(repr, on_table)) == sorted(map(repr, on_subset_records))


# --- Every flavor: each lookup filters each read of the table at that read's own WHERE ---

# sqlglot's dialect for each flavor; SAP HANA's regular-expression predicates are beyond it
DIALECTS = {
    "bigquery": "bigquery", "databricks": "databricks", "duckdb": "duckdb", "mssql": "tsql", "oracle": "oracle",
    "postgresql": "postgres", "redshift": "redshift", "redshift_spectrum": "redshift",
    "salesforce_data360": "postgres", "snowflake": "snowflake",
}
LOOKUPS = [
    (name, lookup["sql_flavor"])
    for name in IN_SCOPE
    for lookup in CAT_TYPES[name].get("target_data_lookups") or []
    if lookup["sql_flavor"] in DIALECTS
]


def _parse(name: str, flavor: str, subset: str | None) -> exp.Expression:
    return sqlglot.parse_one(_lookup(name, "src", subset, flavor).strip().rstrip(";"), read=DIALECTS[flavor])


@pytest.mark.parametrize(("name", "flavor"), LOOKUPS)
def test_lookup_without_a_subset_is_valid_sql(name, flavor):
    _parse(name, flavor, None)


@pytest.mark.parametrize(("name", "flavor"), LOOKUPS)
def test_lookup_applies_the_subset_to_each_read_of_the_table(name, flavor):
    tree = _parse(name, flavor, "tg_mark = 1")
    reads = [table for table in tree.find_all(exp.Table) if table.name == "src"]
    marks = [column for column in tree.find_all(exp.Column) if column.name == "tg_mark"]
    assert reads and len(marks) == len(reads)
    for mark in marks:
        where = mark.find_ancestor(exp.Where)
        assert where is not None
        # A term ANDed after the query's own OR would bind to only one side of it
        assert not any(isinstance(node, exp.Or) for node in _path(mark, where))
        assert any(table.name == "src" for table in _own_tables(where.parent))


def _path(node: exp.Expression, ancestor: exp.Expression) -> list[exp.Expression]:
    path = []
    while (node := node.parent) is not ancestor:
        path.append(node)
    return path


def _own_tables(select: exp.Expression) -> list[exp.Table]:
    sources = [select.args.get("from_"), *(select.args.get("joins") or [])]
    return [source.this for source in sources if source is not None and isinstance(source.this, exp.Table)]
