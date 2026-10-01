"""Each general type's per-column profiling query emits only the measures that apply to it.

Rows are written by column name, so a measure a type does not take is simply absent from its
query rather than padded with a NULL placeholder to share one column list.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock
from uuid import uuid4

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
GENERAL_TYPES = ("A", "N", "D", "B", "X")

PLACEHOLDER = re.compile(r"^\s*NULL AS \w+,?\s*$", re.MULTILINE)
DANGLING_COMMA = re.compile(r",\s*(?:FROM\b|CROSS JOIN\b|\))", re.IGNORECASE)
# The percentile derived table: the innermost "(SELECT" that closes as ") pctile".
PERCENTILE_SUBQUERY = re.compile(r"\(SELECT(?:(?!\(SELECT).)*?\)\s*pctile", re.DOTALL)
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
def test_percentiles_never_read_the_sample(flavor):
    """Sampling covers the rest of the numeric query; the percentile derived table reads the whole
    table with whichever method the run resolved."""
    for approx in _percentile_methods(flavor):
        query = _render(flavor, "N", sampled=True, approx=approx)
        pctile = PERCENTILE_SUBQUERY.search(query)
        assert pctile, f"{flavor}: no percentile derived table"
        assert not SAMPLING_CLAUSE.search(pctile.group(0)), f"{flavor}: {pctile.group(0)}"


@pytest.mark.parametrize("flavor", FLAVORS)
def test_the_percentile_label_names_the_function_the_query_renders(flavor):
    for approx in _percentile_methods(flavor):
        pctile = PERCENTILE_SUBQUERY.search(_render(flavor, "N", sampled=False, approx=approx)).group(0)
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
    exact = PERCENTILE_SUBQUERY.search(_render(flavor, "N", sampled=False, approx=False)).group(0)
    approx = PERCENTILE_SUBQUERY.search(_render(flavor, "N", sampled=False, approx=True)).group(0)
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
