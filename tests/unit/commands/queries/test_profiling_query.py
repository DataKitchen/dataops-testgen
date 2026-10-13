import re
from dataclasses import replace as dataclasses_replace
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from testgen.commands.queries.profiling_query import ProfilingSQL, TableSampling, calculate_sampling_params
from testgen.common.database.column_chars import ColumnChars
from testgen.common.models.profile_result import PercentileMethod, ProfileResult
from testgen.common.read_file import read_template_sql_file

pytestmark = pytest.mark.unit

# Microseconds are deliberate: they must not reach run_date, which carries whole seconds.
RUN_STARTTIME = datetime(2026, 7, 14, 21, 22, 26, 227897, tzinfo=UTC)


# --- ProfilingSQL.update_profiling_results ---


def _make_profiling_sql(
    profile_flag_pii=False,
    profile_flag_cdes=False,
    profiling_starttime=RUN_STARTTIME,
    flavor="snowflake",
):
    connection = MagicMock(sql_flavor=flavor, sql_flavor_code=flavor)
    table_group = MagicMock()
    table_group.profile_flag_pii = profile_flag_pii
    table_group.profile_flag_cdes = profile_flag_cdes
    profiling_run = MagicMock(profiling_starttime=profiling_starttime)
    return ProfilingSQL(connection, table_group, profiling_run)


@pytest.mark.parametrize("profile_flag_pii,profile_flag_cdes", [
    (False, False),
    (True, False),
    (False, True),
    (True, True),
])
def test_update_profiling_results_weight_query_is_always_last(profile_flag_pii, profile_flag_cdes):
    sql = _make_profiling_sql(profile_flag_pii=profile_flag_pii, profile_flag_cdes=profile_flag_cdes)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert templates[-1] == "dq_score_weight_update.sql"


def test_update_profiling_results_includes_pii_queries_when_flag_set():
    sql = _make_profiling_sql(profile_flag_pii=True)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "pii_flag.sql" in templates
    assert "pii_flag_update.sql" in templates


def test_update_profiling_results_excludes_pii_queries_when_flag_unset():
    sql = _make_profiling_sql(profile_flag_pii=False)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "pii_flag.sql" not in templates
    assert "pii_flag_update.sql" not in templates


def test_update_profiling_results_includes_cde_query_when_flag_set():
    sql = _make_profiling_sql(profile_flag_cdes=True)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "cde_flagger_query.sql" in templates


def test_update_profiling_results_excludes_cde_query_when_flag_unset():
    sql = _make_profiling_sql(profile_flag_cdes=False)

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        queries = sql.update_profiling_results()

    templates = [q[0] for q in queries]
    assert "cde_flagger_query.sql" not in templates


# --- calculate_sampling_params ---


def test_sampling_basic_calculation():
    result = calculate_sampling_params("orders", 10000, "30", min_sample=100)
    assert result is not None
    assert result.table_name == "orders"
    assert result.sample_count == 3000
    assert result.sample_ratio == pytest.approx(10000 / 3000)
    assert result.sample_percent == pytest.approx(30.0)


def test_sampling_non_numeric_percent_fallback():
    """Non-numeric string should fall back to 30%."""
    result = calculate_sampling_params("orders", 10000, "abc", min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_empty_string_percent_fallback():
    result = calculate_sampling_params("orders", 10000, "", min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_none_percent_fallback():
    result = calculate_sampling_params("orders", 10000, None, min_sample=100)
    assert result is not None
    assert result.sample_count == 3000


def test_sampling_percent_out_of_range_zero():
    result = calculate_sampling_params("orders", 10000, "0", min_sample=100)
    assert result is None


def test_sampling_percent_out_of_range_100():
    result = calculate_sampling_params("orders", 10000, "100", min_sample=100)
    assert result is None


def test_sampling_record_count_below_min_sample():
    result = calculate_sampling_params("small_table", 50, "30", min_sample=100)
    assert result is None


def test_sampling_record_count_equals_min_sample():
    result = calculate_sampling_params("small_table", 100, "30", min_sample=100)
    assert result is None


def test_sampling_clamped_to_min_sample():
    """When calculated sample is below min_sample, clamp up to min_sample."""
    result = calculate_sampling_params("orders", 1000, "5", min_sample=200)
    # 5% of 1000 = 50, but min_sample is 200
    assert result is not None
    assert result.sample_count == 200


def test_sampling_clamped_to_max_sample():
    """When calculated sample exceeds max, clamp down to max."""
    result = calculate_sampling_params("huge_table", 10_000_000, "50", min_sample=100, max_sample=999000)
    # 50% of 10M = 5M, but max is 999000
    assert result is not None
    assert result.sample_count == 999000


def test_sampling_ratio_and_percent_math():
    result = calculate_sampling_params("orders", 5000, "20", min_sample=100)
    # 20% of 5000 = 1000
    assert result.sample_count == 1000
    assert result.sample_ratio == pytest.approx(5.0)
    assert result.sample_percent == pytest.approx(20.0)


def test_sampling_float_percent():
    result = calculate_sampling_params("orders", 10000, 25.5, min_sample=100)
    # 25.5% of 10000 = 2550
    assert result is not None
    assert result.sample_count == 2550


def test_sampling_decimal_string_percent():
    result = calculate_sampling_params("orders", 10000, "15.5", min_sample=100)
    assert result is not None
    assert result.sample_count == 1550


# --- ProfilingSQL row values ---


def _alpha_column(column_name: str = "nct_id") -> ColumnChars:
    return ColumnChars(
        schema_name="public",
        table_name="studies",
        column_name=column_name,
        ordinal_position=1,
        general_type="A",
        column_type="varchar",
        db_data_type="character varying",
        record_ct=513,
    )


def test_row_values_carry_the_run_date_the_query_is_rendered_with():
    sql = _make_profiling_sql()

    # One run writes one run_date, and the app-side profiling queries match rows against the
    # value the target queries are rendered with.
    assert sql.column_row_values(_alpha_column())["run_date"] == sql._get_params()["RUN_DATE"]
    assert sql.column_error_row(_alpha_column(), "unsupported type")["run_date"] == "2026-07-14 21:22:26"


def test_row_values_key_the_row_by_the_catalog_column_name():
    sql = _make_profiling_sql()

    assert sql.column_row_values(_alpha_column("owner's_name"))["column_name"] == "owner's_name"
    assert sql.column_error_row(_alpha_column("owner's_name"), "boom")["column_name"] == "owner's_name"


@pytest.mark.parametrize("general_type", ["A", "D", "B", "X"])
def test_only_a_numeric_column_is_labelled_with_a_percentile_method(general_type):
    sql = _make_profiling_sql()
    column = dataclasses_replace(_alpha_column(), general_type=general_type)

    assert "percentile_method" not in sql.profiled_row_values(column, use_approx_percentile=True)


@pytest.mark.parametrize("approx, method", [(False, PercentileMethod.EXACT), (True, PercentileMethod.APPROXIMATE)])
def test_a_numeric_column_is_labelled_with_the_percentile_method_it_was_run_with(approx, method):
    sql = _make_profiling_sql()
    column = dataclasses_replace(_alpha_column(), general_type="N")

    assert sql.profiled_row_values(column, use_approx_percentile=approx)["percentile_method"] == method


TABLE_GROUP_ID = UUID("00000000-0000-0000-0000-00000000a001")
PROFILE_RUN_ID = UUID("00000000-0000-0000-0000-00000000b002")


def _identified_profiling_sql() -> ProfilingSQL:
    connection = MagicMock(sql_flavor="snowflake", sql_flavor_code="snowflake", connection_id=42)
    table_group = MagicMock(project_code="PROJ", id=TABLE_GROUP_ID, table_group_schema="group_schema")
    profiling_run = MagicMock(id=PROFILE_RUN_ID, profiling_starttime=RUN_STARTTIME)
    return ProfilingSQL(connection, table_group, profiling_run)


def _distinct_fields_column(general_type: str = "A") -> ColumnChars:
    # Every field differs from the others, so a value written under the wrong key shows up.
    return ColumnChars(
        schema_name="catalog_schema",
        table_name="studies",
        column_name="nct_id",
        ordinal_position=7,
        general_type=general_type,
        column_type="varchar(20)",
        db_data_type="character varying",
        record_ct=513,
    )


EXPECTED_ROW_VALUES = {
    "project_code": "PROJ",
    "connection_id": 42,
    "table_groups_id": TABLE_GROUP_ID,
    "schema_name": "group_schema",
    "profile_run_id": PROFILE_RUN_ID,
    "run_date": "2026-07-14 21:22:26",
    "table_name": "studies",
    "column_name": "nct_id",
    "position": 7,
    "column_type": "varchar(20)",
    "db_data_type": "character varying",
    "general_type": "A",
}


def test_row_values_map_each_known_value_to_its_profile_results_column():
    assert _identified_profiling_sql().column_row_values(_distinct_fields_column()) == EXPECTED_ROW_VALUES


def test_every_supplied_field_is_a_profile_results_column():
    sql = _identified_profiling_sql()
    columns = set(ProfileResult.__table__.columns.keys())

    assert set(sql.profiled_row_values(_distinct_fields_column("N"), use_approx_percentile=True)) <= columns
    assert set(sql.column_error_row(_distinct_fields_column(), "boom")) <= columns


def test_an_error_row_records_the_error_under_the_column_it_belongs_to():
    sql = _identified_profiling_sql()

    row = sql.column_error_row(_distinct_fields_column("N"), "x" * (sql.max_error_length + 10))

    assert row == {
        **EXPECTED_ROW_VALUES,
        "general_type": "X",
        "record_ct": 513,
        "query_error": "x" * sql.max_error_length,
    }


def test_datatype_suggestions_runs_before_and_after_functional_datatype():
    """The two templates each read what the other writes: functional_datatype keys rules off
    datatype_suggestion, and datatype_suggestions keys its 'State' / 'Boolean' /
    'Measurement Pct' rules off functional_data_type. A single pass before functional_datatype
    leaves functional_data_type NULL, so those three rules can never fire."""
    sql = _make_profiling_sql()

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        templates = [q[0] for q in sql.update_profiling_results()]

    suggestion_passes = [i for i, name in enumerate(templates) if name == "datatype_suggestions.sql"]
    functional_datatype = templates.index("functional_datatype.sql")

    assert len(suggestion_passes) == 2, "datatype_suggestions must run twice"
    assert suggestion_passes[0] < functional_datatype < suggestion_passes[1]


def test_tabletype_staging_runs_after_the_second_suggestion_pass():
    """functional_tabletype_stage reads functional_data_type, so it must not be interleaved
    between the two datatype_suggestions passes."""
    sql = _make_profiling_sql()

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        templates = [q[0] for q in sql.update_profiling_results()]

    last_suggestion = max(i for i, name in enumerate(templates) if name == "datatype_suggestions.sql")
    assert templates.index("functional_tabletype_stage.sql") > last_suggestion


def test_tabletype_staging_is_deleted_after_it_is_consumed():
    """functional_tabletype_update is the only reader of the staged rows, so deleting them
    ahead of it leaves functional_table_type unwritten."""
    sql = _make_profiling_sql()

    with patch.object(sql, "_get_query", side_effect=lambda name, *_args, **_kw: (name, {})):
        templates = [q[0] for q in sql.update_profiling_results()]

    assert (
        templates.index("delete_staging_functional_tables.sql")
        > templates.index("functional_tabletype_update.sql")
    )


# --- Table type staging is keyed on the run ---


def test_tabletype_staging_rows_carry_the_run_id():
    """stg_functional_table_updates carries no table group, so
    (project_code, schema_name, table_name) cannot identify one run's rows on its own."""
    sql = read_template_sql_file("functional_tabletype_stage.sql", "profiling")

    insert_columns = re.search(
        r"INSERT INTO stg_functional_table_updates\s*\(([^)]*)\)", sql, re.IGNORECASE
    ).group(1)
    assert "profile_run_id" in insert_columns


def test_tabletype_update_selects_its_staged_rows_by_run_id():
    sql = read_template_sql_file("functional_tabletype_update.sql", "profiling")

    assert "s.profile_run_id = :PROFILE_RUN_ID" in sql
    assert "s.run_date" not in sql


# --- ProfilingSQL.run_column_profiling: percentiles ---


def _numeric_column() -> ColumnChars:
    return ColumnChars(
        schema_name="public",
        table_name="orders",
        column_name="amount",
        ordinal_position=1,
        general_type="N",
        column_type="numeric",
        db_data_type="numeric",
        record_ct=100000,
        is_decimal=True,
    )


SAMPLING = TableSampling(table_name="orders", sample_count=30000, sample_ratio=100000 / 30000, sample_percent=30.0)


def _percentile_subquery(query: str) -> str:
    match = re.search(r"\(SELECT(?:(?!\(SELECT).)*?\)\s*pctile", query, re.DOTALL)
    assert match, "no percentile subquery rendered"
    return match.group(0)


def test_exact_percentiles_read_the_whole_table_on_a_sampled_run():
    sql = _make_profiling_sql()
    query, _ = sql.run_column_profiling(_numeric_column(), SAMPLING, use_approx_percentile=False)

    pctile = _percentile_subquery(query)
    assert "PERCENTILE_CONT" in pctile
    assert "SAMPLE" not in pctile.upper()


def test_approximate_percentiles_use_the_engine_function():
    sql = _make_profiling_sql()
    query, _ = sql.run_column_profiling(_numeric_column(), SAMPLING, use_approx_percentile=True)

    pctile = _percentile_subquery(query)
    assert "APPROX_PERCENTILE" in pctile
    assert "PERCENTILE_CONT" not in pctile
    assert "SAMPLE" not in pctile.upper()


def test_a_non_numeric_column_carries_no_percentile_method():
    sql = _make_profiling_sql()
    column = dataclasses_replace(_numeric_column(), general_type="A")
    query, _ = sql.run_column_profiling(column, None, use_approx_percentile=True)
    assert "percentile" not in query.lower()


# --- ProfilingSQL.run_column_profiling: value hashes ---


def _column_of_type(general_type: str) -> ColumnChars:
    column_type, is_decimal = {"A": ("varchar", False), "N": ("numeric", True), "D": ("date", False)}[general_type]
    return dataclasses_replace(
        _numeric_column(), general_type=general_type, column_type=column_type, db_data_type=column_type,
        is_decimal=is_decimal,
    )


@pytest.mark.parametrize(("general_type", "measures"), [
    ("A", {"multiset_hash"}),
    ("N", {"multiset_hash"}),
    ("D", {"multiset_hash", "epoch_sum"}),
])
def test_a_hashed_type_records_its_value_hashes(general_type, measures):
    sql = _make_profiling_sql()
    query, _ = sql.run_column_profiling(_column_of_type(general_type), None, hashed_types=frozenset({"A", "N", "D"}))

    assert {measure for measure in ("multiset_hash", "epoch_sum") if f"AS {measure}" in query} == measures


@pytest.mark.parametrize(
    ("general_type", "hashed_types"),
    [("A", frozenset()), ("N", frozenset()), ("D", frozenset()), ("A", frozenset({"N", "D"}))],
    ids=["text, nothing hashed", "number, nothing hashed", "date, nothing hashed", "text, text not hashed"],
)
def test_a_type_not_hashed_records_no_value_hashes(general_type, hashed_types):
    sql = _make_profiling_sql()
    query, _ = sql.run_column_profiling(_column_of_type(general_type), None, hashed_types=hashed_types)

    assert "multiset_hash" not in query
    assert "epoch_sum" not in query
    assert "{MULTISET_HASH_TERM}" not in query
