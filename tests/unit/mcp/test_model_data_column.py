from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from testgen.common.models.data_column import ColumnProfileDetail, DataColumnChars


def _detail_row(**overrides) -> dict:
    """Build a dict matching every ColumnProfileDetail field."""
    base = {
        # Identity
        "column_name": "customer_name",
        "table_name": "customers",
        "schema_name": "demo",
        # Types & metadata
        "general_type": "A",
        "column_type": "varchar(50)",
        "db_data_type": "varchar(50)",
        "functional_data_type": "Person Given Name",
        "datatype_suggestion": "VARCHAR(20)",
        "functional_table_type": None,
        "pii_flag": "B/NAME/Individual",
        "critical_data_element": False,
        # Counts
        "record_ct": 500,
        "value_ct": 500,
        "distinct_value_ct": 260,
        "null_value_ct": 0,
        "filled_value_ct": 0,
        "zero_value_ct": 0,
        # Alpha
        "min_length": 3,
        "max_length": 50,
        "avg_length": 12.4,
        "min_text": "Aaron",
        "max_text": "Zoey",
        "top_freq_values": "| Mary | 12\n| John | 10",
        "top_patterns": "10 | A(5) | 8 | A(6)",
        "distinct_std_value_ct": 250,
        "distinct_pattern_ct": 35,
        "std_pattern_match": None,
        "mixed_case_ct": 100,
        "lower_case_ct": 350,
        "upper_case_ct": 50,
        "non_alpha_ct": 0,
        "includes_digit_ct": 0,
        "numeric_ct": 0,
        "date_ct": 0,
        "quoted_value_ct": 0,
        "lead_space_ct": 0,
        "embedded_space_ct": 0,
        "avg_embedded_spaces": 0.0,
        "zero_length_ct": 0,
        # Numeric (None for an alpha column)
        "min_value": None,
        "min_value_over_0": None,
        "max_value": None,
        "avg_value": None,
        "stdev_value": None,
        "percentile_25": None,
        "percentile_50": None,
        "percentile_75": None,
        # Date
        "min_date": None,
        "max_date": None,
        "before_1yr_date_ct": None,
        "before_5yr_date_ct": None,
        "before_20yr_date_ct": None,
        "within_1yr_date_ct": None,
        "within_1mo_date_ct": None,
        "future_date_ct": None,
        # Boolean
        "boolean_true_ct": None,
        # Per-column profiling failure
        "query_error": None,
        # Scores & hygiene
        "dq_score_profiling": 100.0,
        "dq_score_testing": 98.5,
        "hygiene_issue_count": 1,
        # Run identity
        "profile_run_id": uuid4(),
        "profile_run_je_id": uuid4(),
        "profile_run_status": "Complete",
        "profile_run_started_at": datetime(2026, 5, 1, 12, 0, 0),
        "profile_run_ended_at": datetime(2026, 5, 1, 12, 5, 0),
        "profile_run_log_message": None,
    }
    base.update(overrides)
    return base


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_returns_dataclass_when_row_exists(session_mock):
    row = _detail_row()
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = row

    result = DataColumnChars.get_column_detail(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="customer_name",
    )

    assert isinstance(result, ColumnProfileDetail)
    assert result.column_name == "customer_name"
    assert result.general_type == "A"
    assert result.min_text == "Aaron"
    assert result.profile_run_status == "Complete"
    assert result.hygiene_issue_count == 1


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_returns_none_when_missing(session_mock):
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = None

    result = DataColumnChars.get_column_detail(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="ghost_column",
    )

    assert result is None


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_numeric_column_carries_numeric_fields(session_mock):
    row = _detail_row(
        column_name="amount",
        general_type="N",
        column_type="numeric(18,4)",
        db_data_type="numeric",
        functional_data_type="Currency",
        pii_flag=None,
        # Numeric stats populated; alpha fields naturally None at the DB level for numeric columns
        min_value=0.0,
        min_value_over_0=0.01,
        max_value=99999.99,
        avg_value=125.34,
        stdev_value=42.1,
        percentile_25=50.0,
        percentile_50=100.0,
        percentile_75=200.0,
        # Alpha fields cleared for realism
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
    )
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = row

    result = DataColumnChars.get_column_detail(
        table_groups_id=uuid4(), table_name="orders", column_name="amount"
    )

    assert result.general_type == "N"
    assert result.min_value == 0.0
    assert result.percentile_50 == 100.0
    assert result.min_text is None


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_date_column_carries_date_fields(session_mock):
    row = _detail_row(
        column_name="created_at",
        general_type="D",
        functional_data_type="Datetime-Created",
        min_date=datetime(2024, 1, 1, 0, 0, 0),
        max_date=datetime(2026, 4, 30, 23, 59, 59),
        before_1yr_date_ct=10000,
        before_5yr_date_ct=2000,
        before_20yr_date_ct=0,
        within_1yr_date_ct=40000,
        within_1mo_date_ct=5000,
        future_date_ct=0,
    )
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = row

    result = DataColumnChars.get_column_detail(
        table_groups_id=uuid4(), table_name="orders", column_name="created_at"
    )

    assert result.general_type == "D"
    assert result.min_date == datetime(2024, 1, 1, 0, 0, 0)
    assert result.within_1yr_date_ct == 40000


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_boolean_column_carries_true_count(session_mock):
    row = _detail_row(
        column_name="is_active",
        general_type="B",
        functional_data_type="Boolean",
        boolean_true_ct=420,
        value_ct=500,
    )
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = row

    result = DataColumnChars.get_column_detail(
        table_groups_id=uuid4(), table_name="users", column_name="is_active"
    )

    assert result.general_type == "B"
    assert result.boolean_true_ct == 420


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_pinned_profiling_run_id_appears_in_query(session_mock):
    """When profiling_run_id is supplied, the rendered query references that pinned id."""
    pinned_id = uuid4()
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = None

    DataColumnChars.get_column_detail(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="customer_name",
        profiling_run_id=pinned_id,
    )

    # The query passed to execute() should reference the pinned id literally.
    call_args = session_mock.return_value.execute.call_args
    query = call_args[0][0]
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    # SQLAlchemy renders UUID literal binds without dashes (.hex form).
    assert pinned_id.hex in sql_str or str(pinned_id) in sql_str


@patch("testgen.common.models.data_column.get_current_session")
def test_get_column_detail_no_pin_uses_last_complete_profile_run_id(session_mock):
    """Without a pin, the join should reference the column's last_complete_profile_run_id column."""
    session_mock.return_value.execute.return_value.mappings.return_value.first.return_value = None

    DataColumnChars.get_column_detail(
        table_groups_id=uuid4(),
        table_name="customers",
        column_name="customer_name",
    )

    call_args = session_mock.return_value.execute.call_args
    query = call_args[0][0]
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "last_complete_profile_run_id" in sql_str


# ----------------------------------------------------------------------
# DataColumnChars.search_by_name
# ----------------------------------------------------------------------


@patch.object(DataColumnChars, "_paginate")
def test_search_by_name_joins_table_group_and_orders_for_stable_pagination(paginate_mock):
    paginate_mock.return_value = ([], 0)

    DataColumnChars.search_by_name(pattern="%email%", page=1, limit=10)

    query = paginate_mock.call_args[0][0]
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    # Join to table_groups + ILIKE on column_name + the expected ordering for stable paging.
    assert "table_groups" in sql_str.lower()
    assert "ilike" in sql_str.lower() or "like" in sql_str.lower()
    assert "ORDER BY" in sql_str
    assert "project_code" in sql_str
    assert "%email%" in sql_str


@patch.object(DataColumnChars, "_paginate")
def test_search_by_name_excludes_dropped_columns(paginate_mock):
    paginate_mock.return_value = ([], 0)

    DataColumnChars.search_by_name(pattern="%x%", page=1, limit=10)

    query = paginate_mock.call_args[0][0]
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "drop_date IS NULL" in sql_str


# ----------------------------------------------------------------------
# DataColumnChars.summarize_matches_by_project
# ----------------------------------------------------------------------


@patch("testgen.common.models.data_column.get_current_session")
def test_summarize_matches_by_project_returns_project_count_tuples(session_mock):
    row_a = type("Row", (), {"project_code": "DEFAULT", "match_count": 6})()
    row_b = type("Row", (), {"project_code": "DEMO_2", "match_count": 1})()
    session_mock.return_value.execute.return_value.all.return_value = [row_a, row_b]

    result = DataColumnChars.summarize_matches_by_project(pattern="%email%")

    assert result == [("DEFAULT", 6), ("DEMO_2", 1)]


@patch("testgen.common.models.data_column.get_current_session")
def test_summarize_matches_by_project_groups_and_orders_by_project(session_mock):
    session_mock.return_value.execute.return_value.all.return_value = []

    DataColumnChars.summarize_matches_by_project(pattern="%x%")

    query = session_mock.return_value.execute.call_args[0][0]
    sql_str = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "GROUP BY" in sql_str
    assert "ORDER BY" in sql_str
    assert "project_code" in sql_str.lower()
