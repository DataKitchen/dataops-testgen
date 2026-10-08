"""Each general type's per-column profiling query emits only the measures that apply to it.

Rows are written by column name, so a measure a type does not take is simply absent from its
query rather than padded with a NULL placeholder to share one column list.
"""

import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock
from uuid import uuid4

import duckdb
import pytest

import testgen
from testgen.commands.queries.profiling_query import ProfilingSQL, TableSampling
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service
from testgen.common.database.flavor.flavor_service import SQLFlavor
from testgen.common.models.profile_result import PercentileMethod

pytestmark = pytest.mark.unit

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"
FLAVORS = get_args(SQLFlavor)
GENERAL_TYPES = ("A", "N", "D", "B", "X", "T")

PLACEHOLDER = re.compile(r"^\s*NULL AS \w+,?\s*$", re.MULTILINE)
DANGLING_COMMA = re.compile(r",\s*(?:FROM\b|CROSS JOIN\b|\))", re.IGNORECASE)
# The percentile query: a derived table, the innermost "(SELECT" that closes as ") pctile", or a
# "percentiles" CTE, which closes at the first line that starts with ")".
PERCENTILE_SUBQUERY = re.compile(
    r"\(SELECT(?:(?!\(SELECT).)*?\)\s*pctile|\bpercentiles AS \(.*?^\)", re.DOTALL | re.MULTILINE
)
# A percentile aggregated in the column's main read, one line per percentile.
INLINE_PERCENTILE = re.compile(r"^.*\bAS percentile_\d+,?$", re.MULTILINE)
# The sampling clauses the flavors use. Placeholders are rendered by then, so this matches the SQL.
SAMPLING_CLAUSE = re.compile(r"\bSAMPLE\b|\bTABLESAMPLE\b|\bRAND(?:OM)?\s*\(", re.IGNORECASE)


def _percentile_methods(flavor: str) -> tuple[bool, ...]:
    """The percentile methods a flavor renders, as ``use_approx_percentile`` values: exact when the
    template has an exact branch, approximate when the service declares the function. Data 360 has
    no exact percentile and renders approximately whatever it is asked."""
    template = (TEMPLATE_ROOT / "flavors" / flavor / "profiling" / "project_profiling_query.sql").read_text()
    methods = []
    if "is_N_exact_pctile" in template:
        methods.append(False)
    if get_flavor_service(flavor).supports_approx_percentile:
        methods.append(True)
    assert methods, f"{flavor}: no percentile branch to render"
    return tuple(methods)


def _percentile_sql(query: str) -> str:
    """The SQL that computes the percentiles: the percentile derived table or CTE, or the percentile
    expressions where the flavor aggregates them in the column's main read."""
    if derived := PERCENTILE_SUBQUERY.search(query):
        return derived.group(0)
    inline = "\n".join(INLINE_PERCENTILE.findall(query))
    assert inline, "no percentiles in the query"
    return inline


def _profiling_sql(flavor: str) -> ProfilingSQL:
    connection = MagicMock(sql_flavor=flavor, sql_flavor_code=flavor, connection_id=1)
    table_group = MagicMock(
        project_code="P",
        id=uuid4(),
        table_group_schema="s",
        profile_id_column_mask="%id",
        profile_sk_column_mask="%sk",
    )
    profiling_run = MagicMock(id=uuid4(), profiling_starttime=datetime(2026, 1, 1, tzinfo=UTC))
    return ProfilingSQL(connection, table_group, profiling_run)


def _column(general_type: str, is_decimal: bool = False) -> ColumnChars:
    return ColumnChars(
        schema_name="s",
        table_name="t",
        column_name="c",
        ordinal_position=1,
        general_type=general_type,
        column_type="x",
        db_data_type="x",
        is_decimal=is_decimal,
        record_ct=1000,
    )


def _render(flavor: str, general_type: str, sampled: bool, is_decimal: bool = False, approx: bool = False) -> str:
    sampling = TableSampling(table_name="t", sample_count=300, sample_ratio=1000 / 300, sample_percent=30.0) if sampled else None
    query, _ = _profiling_sql(flavor).run_column_profiling(
        _column(general_type, is_decimal), sampling, use_approx_percentile=approx
    )
    return query


def _aliases(query: str) -> set[str]:
    return set(re.findall(r"\bAS\s+([a-z_0-9]+)\b", query, re.IGNORECASE))


def test_no_flavor_pads_its_query_with_null_placeholders():
    templates = list(TEMPLATE_ROOT.glob("flavors/*/profiling/project_profiling_query.sql"))
    assert len(templates) == len(FLAVORS)
    padded = [path.parts[-3] for path in templates if PLACEHOLDER.search(path.read_text())]
    assert padded == []


@pytest.mark.parametrize("sampled", [False, True])
@pytest.mark.parametrize("general_type", GENERAL_TYPES)
@pytest.mark.parametrize("flavor", FLAVORS)
def test_every_type_renders_a_well_formed_select(flavor, general_type, sampled):
    for approx in _percentile_methods(flavor):
        query = _render(flavor, general_type, sampled, approx=approx)
        assert "-- TG-" not in query
        assert not PLACEHOLDER.search(query)
        assert not DANGLING_COMMA.search(query), DANGLING_COMMA.search(query).group(0)
        assert query.count("(") == query.count(")")


@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_percentile_label_names_the_function_the_query_renders(flavor):
    for approx in _percentile_methods(flavor):
        pctile = _percentile_sql(_render(flavor, "N", sampled=False, approx=approx))
        label = _profiling_sql(flavor).profiled_row_values(_column("N"), approx)["percentile_method"]
        assert label == (PercentileMethod.APPROXIMATE if "APPROX" in pctile.upper() else PercentileMethod.EXACT)


@pytest.mark.parametrize("general_type", GENERAL_TYPES)
@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_query_projects_nothing_the_run_supplies(flavor, general_type):
    for approx in _percentile_methods(flavor):
        supplied = _profiling_sql(flavor).profiled_row_values(_column(general_type), approx)
        assert _aliases(_render(flavor, general_type, sampled=False, approx=approx)).isdisjoint(supplied)


@pytest.mark.parametrize("flavor", [flavor for flavor in FLAVORS if len(_percentile_methods(flavor)) == 2])
def test_the_two_percentile_methods_render_different_functions(flavor):
    exact = _percentile_sql(_render(flavor, "N", sampled=False, approx=False))
    approx = _percentile_sql(_render(flavor, "N", sampled=False, approx=True))
    assert exact != approx
    assert "APPROX" in approx.upper()


@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_type_emits_only_its_own_measures(flavor):
    alpha = _aliases(_render(flavor, "A", sampled=False))
    numeric = _aliases(_render(flavor, "N", sampled=False))
    date = _aliases(_render(flavor, "D", sampled=False))
    boolean = _aliases(_render(flavor, "B", sampled=False))

    assert {"numeric_ct", "distinct_std_value_ct", "min_length"} <= alpha
    assert {"min_value", "min_date", "boolean_true_ct", "fractional_sum"}.isdisjoint(alpha)

    assert {"min_value", "percentile_50", "min_length"} <= numeric
    assert {"numeric_ct", "min_date", "boolean_true_ct", "fractional_sum"}.isdisjoint(numeric)
    assert "fractional_sum" in _aliases(_render(flavor, "N", sampled=False, is_decimal=True))

    assert {"min_date", "future_date_ct", "min_length"} <= date
    assert {"numeric_ct", "min_value", "boolean_true_ct"}.isdisjoint(date)

    assert "boolean_true_ct" in boolean
    assert {"numeric_ct", "min_value", "min_date", "min_length"}.isdisjoint(boolean)


@pytest.mark.parametrize("sampled", [False, True])
@pytest.mark.parametrize("flavor", FLAVORS)
def test_a_text_column_reports_the_value_count_of_each_sample_read(flavor, sampled):
    assert {"sample_value_ct", "sample_pattern_value_ct"} <= _aliases(_render(flavor, "A", sampled=sampled))


# A CTE's name and body, up to the parenthesis that closes it at the start of a line.
CTE = re.compile(r"(\w+) AS \((.*?)\n\)", re.DOTALL)


@pytest.mark.parametrize("general_type", ["N", "D", "B", "T"])
@pytest.mark.parametrize("flavor", FLAVORS)
def test_every_non_text_type_counts_its_values(flavor, general_type):
    assert {"record_ct", "value_ct", "null_value_ct", "distinct_value_ct"} <= _aliases(
        _render(flavor, general_type, sampled=False)
    )


@pytest.mark.parametrize(
    ("flavor", "column_type", "counted_directly"),
    [
        ("postgresql", "interval", True),
        ("postgresql", "json", False),
        ("databricks", "binary", True),
        ("databricks", "map<string,int>", False),
        ("redshift", "binary varying", True),
    ],
)
def test_an_x_column_is_counted_directly_when_the_engine_compares_its_type(flavor, column_type, counted_directly):
    column = replace(_column("X"), column_type=column_type)
    query, _ = _profiling_sql(flavor).run_column_profiling(column, None)
    quote = get_flavor_service(flavor).quote_character
    assert (f"COUNT(DISTINCT {quote}c{quote}) AS distinct_value_ct" in query) == counted_directly


@pytest.mark.parametrize("general_type", ["N", "D", "B", "X", "T"])
@pytest.mark.parametrize("flavor", FLAVORS)
def test_only_text_columns_read_the_sample(flavor, general_type):
    for approx in _percentile_methods(flavor):
        assert not SAMPLING_CLAUSE.search(_render(flavor, general_type, sampled=True, approx=approx))


@pytest.mark.parametrize("flavor", FLAVORS)
def test_each_sample_a_text_column_takes_is_read_once(flavor):
    query = _render(flavor, "A", sampled=True)
    sampled_ctes = [name for name, body in CTE.findall(query) if SAMPLING_CLAUSE.search(body)]

    assert sampled_ctes, f"{flavor}: no sampled CTE"
    assert len(SAMPLING_CLAUSE.findall(query)) == len(sampled_ctes), f"{flavor}: a sampling clause outside a CTE"
    # Each CTE's own definition plus one read: an engine may draw a new sample on every read.
    reads = {name: len(re.findall(rf"\b{name}\b", query)) for name in sampled_ctes}
    assert reads == dict.fromkeys(sampled_ctes, 2), f"{flavor}: {reads}"


# A CSV column of each general type, as DuckDB reads it back.
DUCKDB_COLUMN_VALUES = {
    "A": "'v' || i",
    "N": "i * 1.5",
    "D": "DATE '2026-01-01' + i::INTEGER",
    "B": "i % 2 = 0",
}


def _source_reads(plan: list[dict]) -> int:
    nodes = list(plan)
    reads = 0
    while nodes:
        node = nodes.pop()
        reads += node.get("name") == "READ_CSV"
        nodes.extend(node.get("children", []))
    return reads


@pytest.mark.parametrize("sampled", [False, True])
@pytest.mark.parametrize("general_type", sorted(DUCKDB_COLUMN_VALUES))
def test_a_duckdb_column_query_reads_its_source_once(tmp_path, general_type, sampled):
    """On a file source every read parses the whole file, so the plan is held to one."""
    source = tmp_path / "t.csv"
    database = duckdb.connect()
    database.execute(
        f"COPY (SELECT {DUCKDB_COLUMN_VALUES[general_type]} AS c FROM range(100) r(i)) TO '{source}' (HEADER)"
    )
    database.execute("CREATE SCHEMA s")
    database.execute(f"CREATE VIEW s.t AS SELECT * FROM read_csv('{source}')")

    for approx in _percentile_methods("duckdb"):
        query = _render("duckdb", general_type, sampled, approx=approx)
        plan = json.loads(database.execute(f"EXPLAIN (FORMAT json) {query}").fetchone()[1])
        assert _source_reads(plan) == 1
        assert database.execute(query).fetchone()


# --- the frequency analysis query --------------------------------------------------------

# The value count summed over the grouped read the frequencies come from, not taken by a read of its own.
FREQUENCY_SAMPLE_VALUE_CT = re.compile(
    r"SUM\(\s*(?:COUNT(?:_BIG)?\(\*\)|ct)\s*\)\s+OVER\s*\(\s*\)\s+AS\s+sample_value_ct", re.IGNORECASE
)


def _render_frequency(flavor: str, sampled: bool) -> str:
    sampling = TableSampling(table_name="t", sample_count=300, sample_ratio=1000 / 300, sample_percent=30.0) if sampled else None
    query, _ = _profiling_sql(flavor).run_frequency_analysis(_column("A"), sampling)
    return query


@pytest.mark.parametrize("sampled", [False, True])
@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_frequency_query_counts_its_values_on_the_read_it_ranks(flavor, sampled):
    query = _render_frequency(flavor, sampled)
    assert FREQUENCY_SAMPLE_VALUE_CT.search(query), f"{flavor}: sample_value_ct is not a window over the ranked read"
    assert re.search(r"MAX\(sample_value_ct\) AS sample_value_ct", query), f"{flavor}: sample_value_ct not in the output"


def test_a_duckdb_frequency_query_counts_blank_values_without_listing_them():
    database = duckdb.connect()
    database.execute("CREATE SCHEMA s")
    database.execute(
        "CREATE TABLE s.t AS SELECT * FROM (VALUES ('a'), ('a'), ('a'), ('b'), ('b'), (''), (' '), (NULL)) v(c)"
    )
    cursor = database.execute(_render_frequency("duckdb", sampled=False))
    rows = [dict(zip([column[0] for column in cursor.description], row, strict=True)) for row in cursor.fetchall()]

    assert [(row["value"], row["value_ct"], row["value_rank"]) for row in rows] == [("a", 3, 1), ("b", 2, 2)]
    assert {row["sample_value_ct"] for row in rows} == {7}
