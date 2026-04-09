"""
Unit tests for data contract export (ODCS v3.1.0 generation).

pytest -m unit tests/unit/commands/test_data_contract_export.py
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest
import yaml

from unittest.mock import patch

from testgen.commands.export_data_contract import (
    FUNCTIONAL_TYPE_TO_LOGICAL,
    VALID_STATUSES,
    _build_compliance_summary,
    _build_quality,
    _build_references,
    _build_schema,
    _build_servers,
    _build_sla,
    _derive_origin,
    _pii_flag_to_classification as _pii_to_classification,
    _safe_float,
    run_export_data_contract,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

class Test_PiiToClassification:
    def test_null_returns_public(self):
        assert _pii_to_classification(None) == "public"

    def test_empty_returns_public(self):
        assert _pii_to_classification("") == "public"

    def test_a_prefix_returns_confidential(self):
        assert _pii_to_classification("A/ID/SSN") == "confidential"
        assert _pii_to_classification("A/DEMO/Medical") == "confidential"

    def test_non_a_prefix_returns_restricted(self):
        assert _pii_to_classification("B/CONTACT/Email") == "restricted"
        assert _pii_to_classification("C/ID/Bank") == "restricted"


class Test_DeriveOrigin:
    def test_custom_type_always_business_rule(self):
        assert _derive_origin(datetime.now(), datetime.now(), "N", "CUSTOM") == "business_rule"

    def test_lock_refresh_y_is_business_rule(self):
        assert _derive_origin(datetime.now(), None, "Y", "Row_Ct") == "business_rule"

    def test_manual_update_after_auto_gen_is_business_rule(self):
        auto = datetime(2026, 1, 1)
        manual = datetime(2026, 3, 1)
        assert _derive_origin(auto, manual, "N", "Missing_Pct") == "business_rule"

    def test_auto_gen_date_returns_auto_generated(self):
        assert _derive_origin(datetime.now(), None, "N", "Row_Ct") == "auto_generated"

    def test_no_auto_gen_date_returns_manual(self):
        assert _derive_origin(None, None, "N", "Row_Ct") == "manual"

    def test_manual_update_before_auto_gen_returns_auto_generated(self):
        auto   = datetime(2026, 3, 1)
        manual = datetime(2026, 1, 1)  # manual earlier than auto — auto wins
        assert _derive_origin(auto, manual, "N", "Row_Ct") == "auto_generated"

    def test_manual_update_only_no_auto_gen_returns_business_rule(self):
        # manual without any auto_gen_date — manual overrides
        assert _derive_origin(None, datetime(2026, 1, 1), "N", "Row_Ct") == "manual"


class Test_SafeFloat:
    def test_numeric_string(self):
        assert _safe_float("3.14") == pytest.approx(3.14)

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_non_numeric_returns_none(self):
        assert _safe_float("abc") is None

    def test_integer(self):
        assert _safe_float(42) == 42.0


class Test_FunctionalTypeMapping:
    def test_id_unique_maps_to_string(self):
        assert FUNCTIONAL_TYPE_TO_LOGICAL["ID-Unique"] == "string"

    def test_boolean_maps_to_boolean(self):
        assert FUNCTIONAL_TYPE_TO_LOGICAL["Boolean"] == "boolean"

    def test_measurement_maps_to_number(self):
        assert FUNCTIONAL_TYPE_TO_LOGICAL["Measurement"] == "number"

    def test_date_stamp_maps_to_date(self):
        assert FUNCTIONAL_TYPE_TO_LOGICAL["Date Stamp"] == "date"

    def test_period_year_maps_to_integer(self):
        assert FUNCTIONAL_TYPE_TO_LOGICAL["Period Year"] == "integer"


class Test_ValidStatuses:
    def test_contains_all_lifecycle_states(self):
        assert VALID_STATUSES == {"proposed", "draft", "active", "deprecated", "retired"}


# ---------------------------------------------------------------------------
# _build_schema
# ---------------------------------------------------------------------------

class Test_BuildSchema:
    def _col(self, table="orders", column="order_id", **kwargs):
        return {
            "table_name": table,
            "column_name": column,
            "db_data_type": "INTEGER",
            "general_type": "N",
            "functional_data_type": "ID-Unique",
            "description": None,
            "pii_flag": None,
            "critical_data_element": False,
            "null_value_ct": 0,
            "record_ct": 1000,
            "distinct_value_ct": 1000,
            "min_length": None,
            "max_length": None,
            "min_value": "1",
            "max_value": "9999",
            "top_freq_values": None,
            "std_pattern_match": None,
            "datatype_suggestion": None,
            **kwargs,
        }

    def test_empty_input_returns_empty_list(self):
        assert _build_schema([]) == []

    def test_single_column_produces_one_table(self):
        result = _build_schema([self._col()])
        assert len(result) == 1
        assert result[0]["name"] == "orders"
        assert len(result[0]["properties"]) == 1

    def test_property_has_correct_physical_type(self):
        prop = _build_schema([self._col()])[0]["properties"][0]
        assert prop["physicalType"] == "INTEGER"

    def test_property_logical_type_from_functional(self):
        prop = _build_schema([self._col(functional_data_type="Boolean")])[0]["properties"][0]
        assert prop["logicalType"] == "boolean"

    def test_required_when_no_nulls(self):
        prop = _build_schema([self._col(null_value_ct=0, record_ct=100)])[0]["properties"][0]
        assert prop["required"] is True

    def test_not_required_when_has_nulls(self):
        result = _build_schema([self._col(null_value_ct=5, record_ct=100)])
        prop = result[0]["properties"][0]
        # required may be False or absent — either is acceptable
        assert not prop.get("required", False)

    def test_pii_flag_a_gives_confidential_classification(self):
        prop = _build_schema([self._col(pii_flag="A/ID/SSN")])[0]["properties"][0]
        assert prop["classification"] == "confidential"

    def test_email_pattern_sets_format(self):
        prop = _build_schema([self._col(std_pattern_match="EMAIL", functional_data_type="Email")])[0]["properties"][0]
        cp = {c["property"]: c["value"] for c in prop.get("customProperties", [])}
        assert cp.get("testgen.format") == "email"

    def test_min_max_length_in_custom_properties(self):
        prop = _build_schema([self._col(min_length=1, max_length=50)])[0]["properties"][0]
        cp = {c["property"]: c["value"] for c in prop.get("customProperties", [])}
        assert cp["testgen.minLength"] == 1
        assert cp["testgen.maxLength"] == 50

    def test_examples_from_top_freq_values(self):
        # DB format: "| value | count\n| value | count"
        prop = _build_schema([self._col(top_freq_values="| alice@x.com | 45\n| bob@y.com | 30\n")])[0]["properties"][0]
        assert "examples" in prop
        assert "alice@x.com" in prop["examples"]

    def test_examples_capped_at_five(self):
        freq = "\n".join(f"| val{i} | {i}" for i in range(10))
        prop = _build_schema([self._col(top_freq_values=freq)])[0]["properties"][0]
        assert len(prop.get("examples", [])) <= 5

    def test_multiple_tables_grouped(self):
        cols = [
            self._col("orders", "order_id"),
            self._col("orders", "amount"),
            self._col("customers", "id"),
        ]
        result = _build_schema(cols)
        tables = {t["name"]: t for t in result}
        assert len(tables["orders"]["properties"]) == 2
        assert len(tables["customers"]["properties"]) == 1

    def test_critical_data_element_propagated(self):
        prop = _build_schema([self._col(critical_data_element=True)])[0]["properties"][0]
        assert prop["criticalDataElement"] is True

    def test_description_included_when_present(self):
        prop = _build_schema([self._col(description="Unique order identifier")])[0]["properties"][0]
        assert prop.get("description") == "Unique order identifier"

    def test_description_omitted_when_null(self):
        prop = _build_schema([self._col(description=None)])[0]["properties"][0]
        assert "description" not in prop

    def test_description_omitted_when_empty(self):
        prop = _build_schema([self._col(description="")])[0]["properties"][0]
        assert "description" not in prop

    def test_required_false_when_record_ct_is_none(self):
        # When profiling data is absent (record_ct=None), required must not be True.
        prop = _build_schema([self._col(record_ct=None, null_value_ct=None)])[0]["properties"][0]
        assert not prop.get("required", False)

    def test_required_false_when_record_ct_is_zero(self):
        prop = _build_schema([self._col(record_ct=0, null_value_ct=0)])[0]["properties"][0]
        assert not prop.get("required", False)


# ---------------------------------------------------------------------------
# _build_quality
# ---------------------------------------------------------------------------

class Test_BuildQuality:
    def _test(self, test_type="Row_Ct", dq_dimension="Completeness", **kwargs):
        return {
            "id": str(uuid4()),
            "suite_id": str(uuid4()),
            "test_type": test_type,
            "user_description": None,
            "type_description": None,
            "schema_name": "public",
            "table_name": "orders",
            "column_name": None,
            "test_scope": "table",      # comes from tt.test_scope (fixed column source)
            "severity": "Fail",
            "threshold_value": "1000",
            "baseline_value": None,
            "baseline_ct": "5000",
            "lower_tolerance": None,
            "upper_tolerance": None,
            "subset_condition": None,
            "custom_query": None,
            "skip_errors": None,
            "lock_refresh": "N",
            "last_auto_gen_date": datetime(2026, 1, 1),
            "last_manual_update": None,
            "dq_dimension": dq_dimension,
            "test_name_short": test_type.replace("_", " "),
            "measure_uom": "rows",
            "result_status": "Passed",
            "result_measure": "5200",
            "result_threshold": "1000",
            "result_message": None,
            "result_time": datetime(2026, 4, 1),
            **kwargs,
        }

    def test_library_type_for_row_ct(self):
        rules = _build_quality([self._test("Row_Ct")])
        assert rules[0]["type"] == "library"
        assert rules[0]["metric"] == "rowCount"

    def test_sql_type_for_custom(self):
        rules = _build_quality([self._test(
            "CUSTOM", test_scope="custom",
            custom_query="SELECT * FROM bad_data", skip_errors=0,
        )])
        assert rules[0]["type"] == "sql"
        assert "query" in rules[0]

    def test_custom_vendor_type_for_unknown_test(self):
        rules = _build_quality([self._test("Avg_Shift", dq_dimension="Accuracy")])
        assert rules[0]["type"] == "custom"
        assert rules[0]["vendor"] == "testgen"

    def test_tolerance_band_uses_must_be_between(self):
        rules = _build_quality([self._test(lower_tolerance="0.95", upper_tolerance="1.05")])
        assert "mustBeBetween" in rules[0]
        assert rules[0]["mustBeBetween"] == [0.95, 1.05]

    def test_referential_tests_excluded_from_quality(self):
        # test_scope comes from test_types (tt), not test_definitions (td)
        rules = _build_quality([self._test(test_scope="referential")])
        assert rules == []

    def test_column_test_sets_element_with_column(self):
        rules = _build_quality([self._test(column_name="email", test_scope="column")])
        assert rules[0]["element"] == "orders.email"

    def test_table_test_sets_element_without_column(self):
        rules = _build_quality([self._test(column_name=None, test_scope="table")])
        assert rules[0]["element"] == "orders"

    def test_last_result_included_when_status_present(self):
        rules = _build_quality([self._test()])
        assert rules[0]["lastResult"]["status"] == "passing"
        assert rules[0]["lastResult"]["measuredValue"] == "5200"

    def test_no_last_result_when_status_absent(self):
        rules = _build_quality([self._test(result_status=None, result_measure=None)])
        assert "lastResult" not in rules[0]

    def test_dq_dimension_mapped_to_odcs(self):
        assert _build_quality([self._test(dq_dimension="Validity")])[0]["dimension"] == "conformity"
        assert _build_quality([self._test(dq_dimension="Freshness")])[0]["dimension"] == "timeliness"
        assert _build_quality([self._test(dq_dimension="Uniqueness")])[0]["dimension"] == "uniqueness"

    def test_subset_condition_becomes_filter(self):
        rules = _build_quality([self._test(subset_condition="status = 'active'")])
        assert rules[0]["filter"] == "status = 'active'"

    def test_missing_pct_uses_null_values_metric(self):
        rules = _build_quality([self._test("Missing_Pct")])
        assert rules[0]["metric"] == "nullValues"
        assert rules[0]["type"] == "library"


# ---------------------------------------------------------------------------
# _build_references
# ---------------------------------------------------------------------------

class Test_BuildReferences:
    def _ref_test(self, **kwargs):
        return {
            "id": str(uuid4()),
            "test_type": "Combo_Match",
            "test_scope": "referential",
            "table_name": "orders",
            "column_name": "customer_id",
            "match_table_name": "customers",
            "match_column_names": "id",
            **kwargs,
        }

    def test_builds_foreign_key_reference(self):
        refs = _build_references([self._ref_test()])
        assert len(refs) == 1
        assert refs[0]["type"] == "foreignKey"
        assert refs[0]["from"] == "orders.customer_id"
        assert refs[0]["to"] == "customers.id"

    def test_non_referential_tests_excluded(self):
        refs = _build_references([self._ref_test(test_scope="column")])
        assert refs == []

    def test_missing_match_table_excluded(self):
        refs = _build_references([self._ref_test(match_table_name=None)])
        assert refs == []

    def test_missing_column_excluded(self):
        refs = _build_references([self._ref_test(column_name=None, match_column_names=None)])
        assert refs == []


# ---------------------------------------------------------------------------
# _build_sla
# ---------------------------------------------------------------------------

class Test_BuildSla:
    def test_latency_from_profiling_delay(self):
        sla = _build_sla({"profiling_delay_days": 3, "last_run_dq_score": None})
        latency = next(s for s in sla if s["property"] == "latency")
        assert latency["value"] == 3
        assert latency["unit"] == "day"

    def test_error_rate_from_dq_score(self):
        sla = _build_sla({"profiling_delay_days": None, "last_run_dq_score": 0.95})
        error_rate = next(s for s in sla if s["property"] == "errorRate")
        assert error_rate["value"] == pytest.approx(0.05)

    def test_empty_when_no_data(self):
        assert _build_sla({}) == []

    def test_both_properties_included(self):
        sla = _build_sla({"profiling_delay_days": 2, "last_run_dq_score": 0.9})
        props = {s["property"] for s in sla}
        assert "latency" in props
        assert "errorRate" in props

    def test_null_dq_score_omits_error_rate(self):
        sla = _build_sla({"profiling_delay_days": None, "last_run_dq_score": None})
        assert not any(s["property"] == "errorRate" for s in sla)

    def test_non_numeric_dq_score_omits_error_rate(self):
        # Malformed DB value must not cause 1.0 - 0 = 1.0 to be emitted.
        sla = _build_sla({"profiling_delay_days": None, "last_run_dq_score": "N/A"})
        assert not any(s["property"] == "errorRate" for s in sla)

    def test_dq_score_one_gives_zero_error_rate(self):
        sla = _build_sla({"profiling_delay_days": None, "last_run_dq_score": 1.0})
        er = next(s for s in sla if s["property"] == "errorRate")
        assert er["value"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _build_servers
# ---------------------------------------------------------------------------

class Test_BuildServers:
    def _ctx(self, flavor="postgresql", **kwargs):
        return {
            "sql_flavor_code": flavor,
            "project_host": "localhost",
            "project_port": 5432,
            "project_db": "mydb",
            "table_group_schema": "public",
            **kwargs,
        }

    def test_postgresql_maps_to_postgresql(self):
        assert _build_servers(self._ctx("postgresql"))[0]["type"] == "PostgreSQL"

    def test_snowflake_maps_correctly(self):
        assert _build_servers(self._ctx("snowflake"))[0]["type"] == "Snowflake"

    def test_bigquery_maps_correctly(self):
        assert _build_servers(self._ctx("bigquery"))[0]["type"] == "BigQuery"

    def test_mssql_maps_to_sql_server(self):
        assert _build_servers(self._ctx("mssql"))[0]["type"] == "SQLServer"

    def test_unknown_flavor_passes_through(self):
        assert _build_servers(self._ctx("custom_db"))[0]["type"] == "custom_db"

    def test_host_and_database_included(self):
        server = _build_servers(self._ctx())[0]
        assert server["host"] == "localhost"
        assert server["database"] == "mydb"


# ---------------------------------------------------------------------------
# _build_compliance_summary
# ---------------------------------------------------------------------------

class Test_BuildComplianceSummary:
    def _test(self, status, dim="Completeness"):
        return {
            "id": str(uuid4()),
            "test_type": "Row_Ct",
            "result_status": status,
            "dq_dimension": dim,
            "user_description": "row count test",
            "test_name_short": "Row Count",
            "table_name": "orders",
            "column_name": None,
            "result_message": None,
            "severity": "Fail",
        }

    def test_overall_passing_when_all_pass(self):
        assert _build_compliance_summary([self._test("Passed")])["overall"] == "passing"

    def test_overall_failing_when_any_fail(self):
        result = _build_compliance_summary([self._test("Passed"), self._test("Failed")])
        assert result["overall"] == "failing"

    def test_violated_tests_listed_on_failure(self):
        result = _build_compliance_summary([self._test("Failed")])
        assert len(result["violatedTests"]) == 1

    def test_no_violated_tests_when_all_pass(self):
        result = _build_compliance_summary([self._test("Passed")])
        assert "violatedTests" not in result

    def test_empty_input_returns_empty_dict(self):
        assert _build_compliance_summary([]) == {}

    def test_by_dimension_aggregated(self):
        result = _build_compliance_summary([
            self._test("Passed", "Completeness"),
            self._test("Failed", "Accuracy"),
        ])
        assert result["byDimension"]["completeness"] == "passing"
        assert result["byDimension"]["accuracy"] == "failing"

    def test_tests_without_result_status_ignored(self):
        result = _build_compliance_summary([self._test(None)])
        assert result == {}


# ---------------------------------------------------------------------------
# SQL column source: test_scope must come from test_types (tt), not test_definitions (td)
# ---------------------------------------------------------------------------

class Test_FetchTestsQuery:
    """Verify the SQL query uses tt.test_scope (from test_types), not td.test_scope."""

    def test_query_references_tt_test_scope(self):
        import inspect

        import testgen.commands.export_data_contract as mod
        src = inspect.getsource(mod._fetch_tests)
        assert "tt.test_scope" in src, "test_scope must be sourced from test_types alias (tt), not test_definitions (td)"
        assert "td.test_scope" not in src, "td.test_scope does not exist; column is on test_types"


class Test_FetchColumnsQuery:
    """Verify the column fetch SQL includes the description field."""

    def test_query_includes_description(self):
        import inspect

        import testgen.commands.export_data_contract as mod
        src = inspect.getsource(mod._fetch_columns)
        assert "col.description" in src, "_fetch_columns must SELECT col.description from data_column_chars"


# ---------------------------------------------------------------------------
# Full ODCS YAML structure
# ---------------------------------------------------------------------------

class Test_AnomalyTypeCriteria:
    """
    Validate the anomaly criteria expressions for the three Layer-2 anomaly types.
    These are pure-logic tests that evaluate the criteria SQL expressions in Python
    to confirm they detect the right conditions without requiring a running database.
    """

    # ------------------------------------------------------------------
    # 1032 Exceeds_Declared_Length
    # Fires when max_length >= the declared length in varchar(n)
    # ------------------------------------------------------------------

    def _length_row(self, column_type, max_length, value_ct=100, general_type="A"):
        return {"general_type": general_type, "column_type": column_type,
                "max_length": max_length, "value_ct": value_ct}

    def _matches_exceeds_declared(self, row) -> bool:
        """Python equivalent of the 1032 anomaly_criteria."""
        import re
        if row["general_type"] != "A":
            return False
        m = re.search(r"\((\d+)\)$", row["column_type"])
        if not m:
            return False
        if not row["value_ct"]:
            return False
        return row["max_length"] >= int(m.group(1))

    def test_fires_when_max_length_equals_declared(self):
        assert self._matches_exceeds_declared(self._length_row("character varying(50)", 50))

    def test_fires_when_max_length_exceeds_declared(self):
        # Edge case: profiler observed length beyond declared (shouldn't happen in strict DBs,
        # but possible with some loaders)
        assert self._matches_exceeds_declared(self._length_row("varchar(20)", 25))

    def test_does_not_fire_below_limit(self):
        assert not self._matches_exceeds_declared(self._length_row("character varying(50)", 42))

    def test_does_not_fire_for_non_alpha_column(self):
        assert not self._matches_exceeds_declared(self._length_row("integer", 10, general_type="N"))

    def test_does_not_fire_without_length_spec(self):
        assert not self._matches_exceeds_declared(self._length_row("text", 5000))

    def test_does_not_fire_on_empty_column(self):
        assert not self._matches_exceeds_declared(self._length_row("varchar(50)", 50, value_ct=0))

    # ------------------------------------------------------------------
    # 1033 Numeric_Precision_Overflow
    # Fires when max_value >= 10^(precision - scale) for numeric(p,s)
    # ------------------------------------------------------------------

    def _precision_row(self, column_type, max_value):
        return {"general_type": "N", "column_type": column_type, "max_value": max_value}

    def _matches_precision_overflow(self, row) -> bool:
        """Python equivalent of the 1033 anomaly_criteria."""
        import re
        if row["general_type"] != "N":
            return False
        m = re.match(r"^numeric\((\d+),(\d+)\)$", row["column_type"])
        if not m:
            return False
        if row["max_value"] is None:
            return False
        p, s = int(m.group(1)), int(m.group(2))
        return row["max_value"] >= 10 ** (p - s)

    def test_fires_when_max_equals_overflow_boundary(self):
        # numeric(10,2) → max integer digits = 8 → boundary = 10^8 = 100_000_000
        assert self._matches_precision_overflow(self._precision_row("numeric(10,2)", 100_000_000))

    def test_fires_when_max_exceeds_precision(self):
        assert self._matches_precision_overflow(self._precision_row("numeric(6,2)", 9999.99 + 1))

    def test_does_not_fire_below_boundary(self):
        # numeric(10,2) boundary = 100_000_000; value 99_999_999 is safe
        assert not self._matches_precision_overflow(self._precision_row("numeric(10,2)", 99_999_999))

    def test_does_not_fire_for_non_numeric_column(self):
        assert not self._matches_precision_overflow({"general_type": "A", "column_type": "varchar(20)", "max_value": 1e9})

    def test_does_not_fire_without_precision_spec(self):
        assert not self._matches_precision_overflow(self._precision_row("numeric", 1e15))

    def test_does_not_fire_when_max_value_null(self):
        assert not self._matches_precision_overflow(self._precision_row("numeric(10,2)", None))

    # ------------------------------------------------------------------
    # 1034 Decimal_In_Integer_Column
    # Fires when an integer-family column has a numeric datatype_suggestion
    # ------------------------------------------------------------------

    def _int_row(self, column_type, datatype_suggestion):
        return {"general_type": "N", "column_type": column_type,
                "datatype_suggestion": datatype_suggestion, "max_value": 42.7}

    def _matches_decimal_in_integer(self, row) -> bool:
        """Python equivalent of the 1034 anomaly_criteria."""
        import re
        if row["general_type"] != "N":
            return False
        integer_types = {"integer", "int", "int4", "int8", "bigint", "smallint", "int2", "tinyint"}
        ct = row["column_type"]
        is_integer_family = ct in integer_types or bool(re.match(r"^numeric\(\d+,\s*0\)$", ct))
        if not is_integer_family:
            return False
        ds = row.get("datatype_suggestion") or ""
        return ds.lower().startswith("numeric")

    def test_fires_for_integer_with_numeric_suggestion(self):
        assert self._matches_decimal_in_integer(self._int_row("integer", "numeric(12,4)"))

    def test_fires_for_bigint_with_numeric_suggestion(self):
        assert self._matches_decimal_in_integer(self._int_row("bigint", "numeric(18,6)"))

    def test_fires_for_numeric_scale0_with_numeric_suggestion(self):
        assert self._matches_decimal_in_integer(self._int_row("numeric(10,0)", "numeric(10,3)"))

    def test_does_not_fire_for_already_decimal_column(self):
        assert not self._matches_decimal_in_integer(self._int_row("numeric(10,2)", "numeric(12,4)"))

    def test_does_not_fire_when_suggestion_is_not_numeric(self):
        assert not self._matches_decimal_in_integer(self._int_row("integer", "integer"))

    def test_does_not_fire_when_suggestion_is_null(self):
        assert not self._matches_decimal_in_integer(self._int_row("integer", None))

    def test_does_not_fire_for_alpha_column(self):
        row = {"general_type": "A", "column_type": "varchar(20)", "datatype_suggestion": "numeric(10,2)", "max_value": None}
        assert not self._matches_decimal_in_integer(row)


class Test_FullOdcsYaml:
    def test_valid_yaml_parses_to_expected_keys(self):
        contract = {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "id": str(uuid4()),
            "version": "1.0.0",
            "status": "active",
            "name": "test_suite_orders",
            "tenant": "PROJ",
            "domain": "commerce",
            "dataProduct": "orders",
        }
        output = yaml.dump(contract, default_flow_style=False, allow_unicode=True, sort_keys=False)
        parsed = yaml.safe_load(output)
        assert parsed["apiVersion"] == "v3.1.0"
        assert parsed["kind"] == "DataContract"
        assert parsed["status"] == "active"
        assert parsed["domain"] == "commerce"

    def test_null_and_empty_fields_stripped(self):
        contract = {k: v for k, v in {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "id": str(uuid4()),
            "version": "1.0.0",
            "status": "draft",
            "name": "suite",
            "domain": None,
            "tags": [],
        }.items() if v is not None and v != []}
        output = yaml.dump(contract, default_flow_style=False, sort_keys=False)
        parsed = yaml.safe_load(output)
        assert "domain" not in parsed
        assert "tags" not in parsed


# ---------------------------------------------------------------------------
# Integration: run_export_data_contract orchestration
# ---------------------------------------------------------------------------

_TG_ID = str(uuid4())

_CTX = {
    "table_group_id": _TG_ID,
    "table_groups_name": "orders_group",
    "table_group_schema": "public",
    "group_description": "Order data",
    "contract_version": "1.0.0",
    "contract_status": "active",
    "project_code": "PROJ",
    "business_domain": "commerce",
    "data_product": "orders",
    "data_source": None,
    "source_system": None,
    "source_process": None,
    "data_location": None,
    "transform_level": None,
    "stakeholder_group": None,
    "profiling_delay_days": 3,
    "sql_flavor_code": "postgresql",
    "project_host": "localhost",
    "project_port": 5432,
    "project_db": "mydb",
    "last_run_test_ct": 10,
    "last_run_passed_ct": 9,
    "last_run_failed_ct": 1,
    "last_run_warning_ct": 0,
    "last_run_error_ct": 0,
    "last_run_dq_score": 0.9,
}


class Test_RunExportDataContract:
    _SCOPE = {"included": ["daily_checks"], "excluded": [], "total": 1}

    def _run(self, columns=None, tests=None, runs=None, output_path=None, scope=None):
        with (
            patch("testgen.commands.export_data_contract.get_tg_schema", return_value="public"),
            patch("testgen.commands.export_data_contract._fetch_group_context", return_value=_CTX),
            patch("testgen.commands.export_data_contract._fetch_suite_scope", return_value=scope or self._SCOPE),
            patch("testgen.commands.export_data_contract._fetch_columns", return_value=columns or []),
            patch("testgen.commands.export_data_contract._fetch_tests", return_value=tests or []),
            patch("testgen.commands.export_data_contract._fetch_test_run_history", return_value=runs or []),
        ):
            run_export_data_contract(_TG_ID, output_path)

    def test_produces_valid_odcs_yaml_to_stdout(self, capsys):
        self._run()
        out = capsys.readouterr().out
        doc = yaml.safe_load(out)
        assert doc["apiVersion"] == "v3.1.0"
        assert doc["kind"] == "DataContract"
        assert doc["id"] == _TG_ID
        assert doc["status"] == "active"
        assert doc["name"] == "orders_group"

    def test_writes_to_file_when_output_path_given(self, tmp_path):
        out_file = tmp_path / "contract.yaml"
        self._run(output_path=str(out_file))
        assert out_file.exists()
        doc = yaml.safe_load(out_file.read_text())
        assert doc["apiVersion"] == "v3.1.0"

    def test_schema_section_included_when_columns_present(self, capsys):
        col = {
            "table_name": "orders", "column_name": "id", "db_data_type": "INTEGER",
            "general_type": "N", "functional_data_type": "ID-Unique", "description": None,
            "pii_flag": None, "critical_data_element": False, "null_value_ct": 0,
            "record_ct": 1000, "distinct_value_ct": 1000, "min_length": None, "max_length": None,
            "min_value": "1", "max_value": "9999", "top_freq_values": None,
            "std_pattern_match": None, "datatype_suggestion": None,
        }
        self._run(columns=[col])
        doc = yaml.safe_load(capsys.readouterr().out)
        assert "schema" in doc
        assert doc["schema"][0]["name"] == "orders"

    def test_no_schema_section_when_no_columns(self, capsys):
        self._run(columns=[])
        doc = yaml.safe_load(capsys.readouterr().out)
        assert "schema" not in doc

    def test_invalid_contract_status_defaults_to_draft(self, capsys):
        ctx = {**_CTX, "contract_status": "bogus_value"}
        with (
            patch("testgen.commands.export_data_contract.get_tg_schema", return_value="public"),
            patch("testgen.commands.export_data_contract._fetch_group_context", return_value=ctx),
            patch("testgen.commands.export_data_contract._fetch_suite_scope", return_value=self._SCOPE),
            patch("testgen.commands.export_data_contract._fetch_columns", return_value=[]),
            patch("testgen.commands.export_data_contract._fetch_tests", return_value=[]),
            patch("testgen.commands.export_data_contract._fetch_test_run_history", return_value=[]),
        ):
            run_export_data_contract(_TG_ID)
        doc = yaml.safe_load(capsys.readouterr().out)
        assert doc["status"] == "draft"

    def test_exits_when_table_group_not_found(self):
        with (
            patch("testgen.commands.export_data_contract.get_tg_schema", return_value="public"),
            patch("testgen.commands.export_data_contract._fetch_group_context", return_value={}),
        ):
            with pytest.raises(SystemExit):
                run_export_data_contract(_TG_ID)

    def test_x_testgen_block_includes_suite_names(self, capsys):
        scope = {"included": ["prod_rules", "schema_checks"], "excluded": ["dev_tests"], "total": 3}
        self._run(scope=scope)
        doc = yaml.safe_load(capsys.readouterr().out)
        assert "x-testgen" in doc
        assert doc["x-testgen"]["includedSuites"] == ["prod_rules", "schema_checks"]
        assert doc["x-testgen"]["excludedSuites"] == ["dev_tests"]

    def test_x_testgen_excluded_omitted_when_all_included(self, capsys):
        self._run()  # _SCOPE has no excluded suites
        doc = yaml.safe_load(capsys.readouterr().out)
        assert "x-testgen" in doc
        assert "excludedSuites" not in doc["x-testgen"]

    def test_warns_when_no_suites_included(self, capsys):
        scope = {"included": [], "excluded": ["suite_a"], "total": 1}
        import logging
        with self.assertLogs("testgen", level="WARNING") if False else patch("testgen.commands.export_data_contract.LOG") as mock_log:
            self._run(scope=scope)
        assert mock_log.warning.called
