from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from testgen.common.pii_masking import PII_REDACTED
from testgen.common.source_data_service import (
    LookupData,
    SourceDataResult,
    _build_query_custom,
    _build_query_standard,
    _generate_recency_lookup_query,
    _mask_lookup_pii,
    build_hygiene_query,
    build_test_result_query,
    fetch_hygiene_source_data,
    fetch_test_result_source_data,
)

pytestmark = pytest.mark.unit

MODULE = "testgen.common.source_data_service"

# fetch_from_target_db returns SQLAlchemy Row objects; to_dataframe calls dict() on them.
# Use dicts with _mapping for realistic mock data.
_MOCK_ROWS = [{"col_a": "val1"}, {"col_b": "val2"}]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _standard_issue_data(**overrides):
    base = {
        "test_type": "Alpha_Trunc",
        "test_type_id": "1001",
        "test_definition_id": "td-uuid-1",
        "table_groups_id": "tg-uuid-1",
        "schema_name": "demo",
        "table_name": "orders",
        "column_names": "name",
        "column_type": "varchar",
        "test_date": "2024-03-15 10:30:45",
    }
    base.update(overrides)
    return base


def _custom_issue_data(**overrides):
    base = _standard_issue_data(test_type="CUSTOM", test_type_id="CUSTOM")
    base.update(overrides)
    return base


def _hygiene_issue_data(**overrides):
    base = {
        "table_groups_id": "tg-uuid-1",
        "anomaly_id": "1001",
        "schema_name": "demo",
        "table_name": "orders",
        "column_name": "email",
        "detail": "some detail",
        "profiling_starttime": "2024-03-15 10:00:00",
    }
    base.update(overrides)
    return base


@dataclass
class _FakeTestDefinition:
    custom_query: str | None = None
    baseline_value: str | None = None
    baseline_ct: int | None = None
    baseline_avg: float | None = None
    baseline_sd: float | None = None
    lower_tolerance: str | None = None
    upper_tolerance: str | None = None
    threshold_value: str | None = "0"
    subset_condition: str | None = None
    groupby_names: str | None = None
    having_condition: str | None = None
    match_schema_name: str | None = None
    match_table_name: str | None = None
    match_column_names: str | None = None
    match_subset_condition: str | None = None
    match_groupby_names: str | None = None
    match_having_condition: str | None = None
    window_date_column: str | None = None
    window_days: int | None = None


# ---------------------------------------------------------------------------
# build_test_result_query: dispatch
# ---------------------------------------------------------------------------

class Test_build_test_result_query:
    @patch(f"{MODULE}._build_query_standard", return_value="SELECT 1")
    @patch(f"{MODULE}._build_query_custom")
    def test_dispatches_to_standard(self, mock_custom, mock_standard):
        result = build_test_result_query(_standard_issue_data(), limit=100)
        assert result == "SELECT 1"
        mock_standard.assert_called_once()
        mock_custom.assert_not_called()

    @patch(f"{MODULE}._build_query_custom", return_value="SELECT custom")
    @patch(f"{MODULE}._build_query_standard")
    def test_dispatches_to_custom(self, mock_standard, mock_custom):
        result = build_test_result_query(_custom_issue_data())
        assert result == "SELECT custom"
        mock_custom.assert_called_once()
        mock_standard.assert_not_called()


# ---------------------------------------------------------------------------
# _build_query_standard
# ---------------------------------------------------------------------------

class Test_build_query_standard:
    @patch(f"{MODULE}.replace_templated_functions", side_effect=lambda q, _f: q)
    @patch(f"{MODULE}.replace_params", side_effect=lambda q, _p: q)
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    @patch(f"{MODULE}._get_lookup_data")
    def test_returns_query_when_lookup_and_td_exist(self, mock_lookup, mock_td, _mock_replace, _mock_templated):
        mock_lookup.return_value = LookupData(
            lookup_query="SELECT {COLUMN_NAME} FROM {TABLE_NAME}",
            sql_flavor="postgresql",
        )
        result = _build_query_standard(_standard_issue_data(), limit=500)
        assert result is not None
        mock_lookup.assert_called_once_with("tg-uuid-1", "1001", "Test Results")
        mock_td.assert_called_once_with("td-uuid-1")

    @patch(f"{MODULE}._get_lookup_data", return_value=None)
    def test_returns_none_when_no_lookup(self, _mock_lookup):
        assert _build_query_standard(_standard_issue_data(), limit=500) is None

    @patch(f"{MODULE}.TestDefinition.get", return_value=None)
    @patch(f"{MODULE}._get_lookup_data")
    def test_returns_none_when_no_test_definition(self, _mock_lookup, _mock_td):
        _mock_lookup.return_value = LookupData(lookup_query="SELECT 1", sql_flavor="postgresql")
        assert _build_query_standard(_standard_issue_data(), limit=500) is None

    @patch(f"{MODULE}.replace_templated_functions", side_effect=lambda q, _f: q)
    @patch(f"{MODULE}.replace_params")
    @patch(f"{MODULE}.TestDefinition.get")
    @patch(f"{MODULE}._get_lookup_data")
    def test_tolerance_null_handling(self, mock_lookup, mock_td, mock_replace, _mock_templated):
        mock_lookup.return_value = LookupData(lookup_query="SELECT 1", sql_flavor="postgresql")
        mock_td.return_value = _FakeTestDefinition(lower_tolerance=None, upper_tolerance="")
        _build_query_standard(_standard_issue_data(), limit=500)
        params = mock_replace.call_args[0][1]
        assert params["LOWER_TOLERANCE"] == "NULL"
        assert params["UPPER_TOLERANCE"] == "NULL"

    @patch(f"{MODULE}.replace_templated_functions", side_effect=lambda q, _f: q)
    @patch(f"{MODULE}.replace_params")
    @patch(f"{MODULE}.TestDefinition.get")
    @patch(f"{MODULE}._get_lookup_data")
    def test_subset_condition_defaults(self, mock_lookup, mock_td, mock_replace, _mock_templated):
        mock_lookup.return_value = LookupData(lookup_query="SELECT 1", sql_flavor="postgresql")
        mock_td.return_value = _FakeTestDefinition(subset_condition=None)
        _build_query_standard(_standard_issue_data(), limit=500)
        params = mock_replace.call_args[0][1]
        assert params["SUBSET_CONDITION"] == "1=1"
        assert params["MATCH_SUBSET_CONDITION"] == "1=1"


# ---------------------------------------------------------------------------
# _build_query_custom
# ---------------------------------------------------------------------------

class Test_build_query_custom:
    @patch(f"{MODULE}._get_lookup_data_custom")
    def test_returns_query_with_schema_replaced(self, mock_lookup):
        mock_lookup.return_value = LookupData(lookup_query="SELECT * FROM {DATA_SCHEMA}.my_table")
        result = _build_query_custom(_custom_issue_data(schema_name="prod"))
        assert result == "SELECT * FROM prod.my_table"

    @patch(f"{MODULE}._get_lookup_data_custom", return_value=None)
    def test_returns_none_when_no_lookup(self, _mock_lookup):
        assert _build_query_custom(_custom_issue_data()) is None

    @patch(f"{MODULE}._get_lookup_data_custom")
    def test_returns_none_when_empty_query(self, mock_lookup):
        mock_lookup.return_value = LookupData(lookup_query="")
        assert _build_query_custom(_custom_issue_data()) is None


# ---------------------------------------------------------------------------
# _generate_recency_lookup_query
# ---------------------------------------------------------------------------

class Test_generate_recency_lookup_query:
    @patch(f"{MODULE}.get_flavor_service")
    def test_generates_union_for_1019(self, mock_flavor):
        mock_flavor.return_value = MagicMock(quote_character='"')
        result = _generate_recency_lookup_query(
            "1019", "Columns: col_a, col_b", "col_a,col_b", "postgresql",
        )
        assert "col_a" in result
        assert "col_b" in result
        assert "UNION ALL" in result
        assert "ORDER BY max_date_available DESC" in result

    @patch(f"{MODULE}.get_flavor_service")
    def test_extracts_columns_from_detail(self, mock_flavor):
        mock_flavor.return_value = MagicMock(quote_character='"')
        result = _generate_recency_lookup_query(
            "1020", "Columns: date_col", "fallback_col", "postgresql",
        )
        assert "date_col" in result
        assert "fallback_col" not in result

    @patch(f"{MODULE}.get_flavor_service")
    def test_falls_back_to_column_names_when_no_columns_prefix(self, mock_flavor):
        mock_flavor.return_value = MagicMock(quote_character='"')
        result = _generate_recency_lookup_query(
            "1019", "no columns prefix here", "fallback_col", "postgresql",
        )
        assert "fallback_col" in result

    def test_returns_empty_for_non_recency_anomaly(self):
        assert _generate_recency_lookup_query("1001", "detail", "col", "postgresql") == ""


# ---------------------------------------------------------------------------
# fetch_test_result_source_data
# ---------------------------------------------------------------------------

class Test_fetch_test_result_source_data:
    @patch(f"{MODULE}.fetch_from_target_db")
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}._build_query_standard", return_value="SELECT 1")
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_returns_ok_with_data(self, _mock_td, _mock_build, _mock_conn, mock_fetch):
        mock_fetch.return_value = _MOCK_ROWS
        result = fetch_test_result_source_data(_standard_issue_data(), limit=500)
        assert result.status == "OK"
        assert result.df is not None
        assert result.query == "SELECT 1"
        assert result.message is None

    @patch(f"{MODULE}.TestDefinition.get", return_value=None)
    def test_returns_na_when_no_test_definition(self, _mock_td):
        result = fetch_test_result_source_data(_standard_issue_data())
        assert result.status == "NA"
        assert "no longer exists" in result.message

    @patch(f"{MODULE}._build_query_standard", return_value=None)
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_returns_na_when_no_lookup_query(self, _mock_td, _mock_build):
        result = fetch_test_result_source_data(_standard_issue_data())
        assert result.status == "NA"
        assert "not available" in result.message

    @patch(f"{MODULE}.fetch_from_target_db", return_value=[])
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}._build_query_standard", return_value="SELECT 1")
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_returns_nd_when_no_rows(self, _mock_td, _mock_build, _mock_conn, _mock_fetch):
        result = fetch_test_result_source_data(_standard_issue_data())
        assert result.status == "ND"
        assert result.query == "SELECT 1"

    @patch(f"{MODULE}.fetch_from_target_db", side_effect=Exception("connection refused"))
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}._build_query_standard", return_value="SELECT 1")
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_returns_err_on_exception(self, _mock_td, _mock_build, _mock_conn, _mock_fetch):
        result = fetch_test_result_source_data(_standard_issue_data())
        assert result.status == "ERR"
        assert "connection refused" in result.message

    @patch(f"{MODULE}._mask_lookup_pii")
    @patch(f"{MODULE}.fetch_from_target_db")
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}._build_query_standard", return_value="SELECT 1")
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_calls_mask_pii_for_standard(self, _mock_td, _mock_build, _mock_conn, mock_fetch, mock_mask):
        mock_fetch.return_value = _MOCK_ROWS
        fetch_test_result_source_data(_standard_issue_data(), mask_pii=True)
        mock_mask.assert_called_once()
        _, kwargs = mock_mask.call_args
        assert kwargs["error_type"] == "Test Results"

    @patch(f"{MODULE}.mask_source_data_pii")
    @patch(f"{MODULE}._get_lookup_data_custom")
    @patch(f"{MODULE}._mask_lookup_pii")
    @patch(f"{MODULE}.fetch_from_target_db")
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}._build_query_custom", return_value="SELECT custom")
    @patch(f"{MODULE}.TestDefinition.get", return_value=_FakeTestDefinition())
    def test_masks_redactable_columns_for_custom(
        self, _mock_td, _mock_build, _mock_conn, mock_fetch, mock_mask, mock_custom_lookup, mock_mask_pii,
    ):
        mock_fetch.return_value = _MOCK_ROWS
        mock_custom_lookup.return_value = LookupData(
            lookup_query="SELECT 1", lookup_redactable_columns="ssn, email",
        )
        fetch_test_result_source_data(_custom_issue_data(), mask_pii=True)
        mock_mask.assert_called_once()
        mock_mask_pii.assert_called_once()
        redactable = mock_mask_pii.call_args[0][1]
        assert redactable == {"ssn", "email"}


# ---------------------------------------------------------------------------
# fetch_hygiene_source_data
# ---------------------------------------------------------------------------

class Test_fetch_hygiene_source_data:
    @patch(f"{MODULE}.fetch_from_target_db")
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}.build_hygiene_query", return_value="SELECT 1")
    def test_returns_ok_with_data(self, _mock_build, _mock_conn, mock_fetch):
        mock_fetch.return_value = _MOCK_ROWS
        result = fetch_hygiene_source_data(_hygiene_issue_data())
        assert result.status == "OK"
        assert result.df is not None

    @patch(f"{MODULE}.build_hygiene_query", return_value=None)
    def test_returns_na_when_no_query(self, _mock_build):
        result = fetch_hygiene_source_data(_hygiene_issue_data())
        assert result.status == "NA"

    @patch(f"{MODULE}.fetch_from_target_db", return_value=[])
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}.build_hygiene_query", return_value="SELECT 1")
    def test_returns_nd_when_no_rows(self, _mock_build, _mock_conn, _mock_fetch):
        result = fetch_hygiene_source_data(_hygiene_issue_data())
        assert result.status == "ND"

    @patch(f"{MODULE}.fetch_from_target_db", side_effect=Exception("timeout"))
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}.build_hygiene_query", return_value="SELECT 1")
    def test_returns_err_on_exception(self, _mock_build, _mock_conn, _mock_fetch):
        result = fetch_hygiene_source_data(_hygiene_issue_data())
        assert result.status == "ERR"
        assert "timeout" in result.message

    @patch(f"{MODULE}._mask_lookup_pii")
    @patch(f"{MODULE}.fetch_from_target_db")
    @patch(f"{MODULE}.Connection.get_by_table_group")
    @patch(f"{MODULE}.build_hygiene_query", return_value="SELECT 1")
    def test_calls_mask_pii(self, _mock_build, _mock_conn, mock_fetch, mock_mask):
        mock_fetch.return_value = _MOCK_ROWS
        fetch_hygiene_source_data(_hygiene_issue_data(), mask_pii=True)
        mock_mask.assert_called_once()
        _, kwargs = mock_mask.call_args
        assert kwargs["error_type"] == "Profile Anomaly"


# ---------------------------------------------------------------------------
# _mask_lookup_pii
# ---------------------------------------------------------------------------

class Test_mask_lookup_pii:
    @patch(f"{MODULE}.get_pii_columns", return_value={"ssn"})
    def test_masks_pii_column(self, _mock_pii):
        df = pd.DataFrame({"ssn": ["123"], "name": ["Alice"]})
        _mask_lookup_pii(df, "tg-1", "orders")
        assert df["ssn"].tolist() == [PII_REDACTED]
        assert df["name"].tolist() == ["Alice"]

    @patch(f"{MODULE}.get_pii_columns", return_value={"email"})
    def test_row_level_masking_for_column_name_column(self, _mock_pii):
        df = pd.DataFrame({
            "column_name": ["email", "age"],
            "max_date_available": ["2024-01-01", "2024-02-01"],
        })
        _mask_lookup_pii(df, "tg-1", "orders")
        assert df.loc[0, "max_date_available"] == PII_REDACTED
        assert df.loc[1, "max_date_available"] == "2024-02-01"

    @patch(f"{MODULE}.get_pii_columns", return_value=set())
    def test_no_masking_when_no_pii_columns(self, _mock_pii):
        df = pd.DataFrame({"ssn": ["123"], "name": ["Alice"]})
        _mask_lookup_pii(df, "tg-1", "orders")
        assert df["ssn"].tolist() == ["123"]

    @patch(f"{MODULE}.get_current_session")
    @patch(f"{MODULE}.get_pii_columns", return_value={"email"})
    def test_masks_redactable_columns_when_target_is_pii(self, _mock_pii, mock_session):
        mock_result = {"lookup_redactable_columns": "value_col"}
        mock_session.return_value.execute.return_value.mappings.return_value.first.return_value = mock_result
        df = pd.DataFrame({"email": ["a@b.com"], "value_col": ["secret"]})
        _mask_lookup_pii(
            df, "tg-1", "orders",
            column_name="email", test_type_id="1001", error_type="Test Results",
        )
        assert df["email"].tolist() == [PII_REDACTED]
        assert df["value_col"].tolist() == [PII_REDACTED]

    @patch(f"{MODULE}.get_current_session")
    @patch(f"{MODULE}.get_pii_columns", return_value={"email"})
    def test_skips_redactable_when_target_not_pii(self, _mock_pii, mock_session):
        df = pd.DataFrame({"name": ["Alice"], "value_col": ["visible"]})
        _mask_lookup_pii(
            df, "tg-1", "orders",
            column_name="name", test_type_id="1001", error_type="Test Results",
        )
        # name is not in pii_columns, so redactable check is skipped
        mock_session.return_value.execute.assert_not_called()
        assert df["value_col"].tolist() == ["visible"]


# ---------------------------------------------------------------------------
# build_hygiene_query
# ---------------------------------------------------------------------------

class Test_build_hygiene_query:
    @patch(f"{MODULE}.replace_templated_functions", side_effect=lambda q, _f: q)
    @patch(f"{MODULE}._get_lookup_data")
    def test_returns_parameterized_query(self, mock_lookup, _mock_templated):
        mock_lookup.return_value = LookupData(
            lookup_query="SELECT {COLUMN_NAME} FROM {TARGET_SCHEMA}.{TABLE_NAME} LIMIT {LIMIT}",
            sql_flavor="postgresql",
        )
        result = build_hygiene_query(_hygiene_issue_data(), limit=100)
        assert "email" in result
        assert "demo" in result
        assert "orders" in result
        assert "100" in result

    @patch(f"{MODULE}._get_lookup_data", return_value=None)
    def test_returns_none_when_no_lookup(self, _mock_lookup):
        assert build_hygiene_query(_hygiene_issue_data()) is None

    @patch(f"{MODULE}.replace_templated_functions", side_effect=lambda q, _f: q)
    @patch(f"{MODULE}._generate_recency_lookup_query", return_value="SELECT recency")
    @patch(f"{MODULE}._get_lookup_data")
    def test_uses_generated_query_for_created_in_ui(self, mock_lookup, mock_recency, _mock_templated):
        mock_lookup.return_value = LookupData(lookup_query="created_in_ui", sql_flavor="postgresql")
        result = build_hygiene_query(_hygiene_issue_data(anomaly_id="1019"))
        assert result is not None
        mock_recency.assert_called_once()


# ---------------------------------------------------------------------------
# SourceDataResult
# ---------------------------------------------------------------------------

class Test_SourceDataResult:
    def test_ok_result(self):
        df = pd.DataFrame({"a": [1]})
        r = SourceDataResult("OK", None, "SELECT 1", df)
        assert r.status == "OK"
        assert r.df is df

    def test_error_result(self):
        r = SourceDataResult("ERR", "something broke", None, None)
        assert r.status == "ERR"
        assert r.df is None
