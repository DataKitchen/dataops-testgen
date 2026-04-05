"""
Unit tests for data contract import (ODCS v3.1.0 → TestGen).

pytest -m unit tests/unit/commands/test_data_contract_import.py
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
import yaml

from testgen.commands.import_data_contract import (
    ContractDiff,
    apply_diff,
    compute_diff,
    run_import_data_contract,
    validate_contract_yaml,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TABLE_GROUP_ID = str(uuid4())
TEST_DEF_ID = str(uuid4())

_GROUP_ROW = {
    "id": TABLE_GROUP_ID,
    "table_groups_name": "orders_group",
    "description": "Order checks",
    "contract_version": "1.0.0",
    "contract_status": "active",
    "business_domain": "commerce",
    "data_product": "orders",
    "profiling_delay_days": 3,
}

_TEST_ROW = {
    "id": TEST_DEF_ID,
    "test_type": "Row_Ct",
    "test_description": "Row count check",
    "test_active": "Y",
    "threshold_value": "1000",
    "lower_tolerance": None,
    "upper_tolerance": None,
    "custom_query": None,
    "skip_errors": None,
    "severity": "Fail",
}


def _valid_doc(**overrides) -> dict:
    doc = {
        "apiVersion": "v3.1.0",
        "kind": "DataContract",
        "id": TABLE_GROUP_ID,
        "version": "1.1.0",
        "status": "active",
        "name": "orders_group",
        "domain": "commerce",
        "dataProduct": "orders",
    }
    doc.update(overrides)
    return doc


def _valid_yaml(**overrides) -> str:
    return yaml.dump(_valid_doc(**overrides))


def _db_fetch(group_rows=None, test_rows=None):
    """Return a side_effect function for fetch_dict_from_db."""
    def _fetch(sql, params=None):
        if "test_definitions" in sql:
            return test_rows if test_rows is not None else [_TEST_ROW]
        if "table_groups" in sql:
            return group_rows if group_rows is not None else [_GROUP_ROW]
        return []
    return _fetch


# ---------------------------------------------------------------------------
# validate_contract_yaml
# ---------------------------------------------------------------------------

class Test_ValidateContractYaml:
    def test_valid_document_returns_no_errors(self):
        doc, errors = validate_contract_yaml(_valid_yaml())
        assert errors == []
        assert doc is not None

    def test_invalid_yaml_returns_error(self):
        doc, errors = validate_contract_yaml("{ invalid: yaml: [")
        assert doc is None
        assert errors

    def test_wrong_api_version_returns_error(self):
        _, errors = validate_contract_yaml(_valid_yaml(apiVersion="v2.0.0"))
        assert any("apiVersion" in e for e in errors)

    def test_wrong_kind_returns_error(self):
        _, errors = validate_contract_yaml(_valid_yaml(kind="NotAContract"))
        assert any("kind" in e for e in errors)

    def test_missing_id_returns_error(self):
        doc = _valid_doc()
        doc.pop("id")
        _, errors = validate_contract_yaml(yaml.dump(doc))
        assert any("id" in e.lower() for e in errors)

    def test_invalid_status_returns_error(self):
        _, errors = validate_contract_yaml(_valid_yaml(status="banana"))
        assert any("status" in e.lower() for e in errors)

    def test_all_lifecycle_statuses_accepted(self):
        for status in ("proposed", "draft", "active", "deprecated", "retired"):
            _, errors = validate_contract_yaml(_valid_yaml(status=status))
            assert errors == [], f"Unexpected errors for status={status!r}: {errors}"

    def test_non_dict_document_returns_error(self):
        doc, errors = validate_contract_yaml("- just a list")
        assert doc is None
        assert errors

    def test_missing_status_does_not_error(self):
        doc = _valid_doc()
        doc.pop("status")
        _, errors = validate_contract_yaml(yaml.dump(doc))
        # Missing status is allowed — only invalid status values are rejected
        assert not any("status" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------

class Test_ComputeDiff:
    def test_version_change_detected(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(version="2.0.0"), TABLE_GROUP_ID, "public")
        assert diff.contract_updates["contract_version"] == "2.0.0"

    def test_no_change_when_version_same(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(version="1.0.0"), TABLE_GROUP_ID, "public")
        assert "contract_version" not in diff.contract_updates

    def test_status_change_detected(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(status="deprecated"), TABLE_GROUP_ID, "public")
        assert diff.contract_updates["contract_status"] == "deprecated"

    def test_no_status_change_when_same(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(status="active"), TABLE_GROUP_ID, "public")
        assert "contract_status" not in diff.contract_updates

    def test_description_purpose_updates_description(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(description={"purpose": "New purpose"}), TABLE_GROUP_ID, "public")
        assert diff.contract_updates["description"] == "New purpose"

    def test_domain_change_goes_to_table_group(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(domain="finance"), TABLE_GROUP_ID, "public")
        assert diff.table_group_updates["business_domain"] == "finance"

    def test_data_product_change_goes_to_table_group(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(dataProduct="invoices"), TABLE_GROUP_ID, "public")
        assert diff.table_group_updates["data_product"] == "invoices"

    def test_latency_sla_updates_profiling_delay(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(slaProperties=[{"property": "latency", "value": 7, "unit": "day"}]),
                TABLE_GROUP_ID, "public",
            )
        assert diff.table_group_updates["profiling_delay_days"] == 7

    def test_latency_sla_no_change_when_same_value(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(slaProperties=[{"property": "latency", "value": 3, "unit": "day"}]),
                TABLE_GROUP_ID, "public",
            )
        assert "profiling_delay_days" not in diff.table_group_updates

    def test_threshold_change_in_quality_rule(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(quality=[{"id": TEST_DEF_ID, "name": "Row count check", "type": "library", "mustBeGreaterOrEqualTo": 5000}]),
                TABLE_GROUP_ID, "public",
            )
        assert diff.test_updates[0]["threshold_value"] == "5000"

    def test_description_change_in_quality_rule(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(quality=[{"id": TEST_DEF_ID, "name": "Updated description", "type": "library"}]),
                TABLE_GROUP_ID, "public",
            )
        assert diff.test_updates[0]["test_description"] == "Updated description"

    def test_tolerance_band_update(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(quality=[{"id": TEST_DEF_ID, "name": "avg shift", "type": "custom", "mustBeBetween": [0.95, 1.05]}]),
                TABLE_GROUP_ID, "public",
            )
        upd = diff.test_updates[0]
        assert upd["lower_tolerance"] == "0.95"
        assert upd["upper_tolerance"] == "1.05"

    def test_custom_query_update_for_custom_test(self):
        custom_row = {**_TEST_ROW, "test_type": "CUSTOM", "custom_query": "SELECT * FROM bad"}
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch(test_rows=[custom_row])):
            diff = compute_diff(
                _valid_doc(quality=[{"id": TEST_DEF_ID, "type": "sql", "query": "SELECT * FROM worse", "mustBeLessOrEqualTo": 0}]),
                TABLE_GROUP_ID, "public",
            )
        assert diff.test_updates[0]["custom_query"] == "SELECT * FROM worse"

    def test_unknown_quality_rule_id_produces_warning(self):
        ghost_id = str(uuid4())
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(
                _valid_doc(quality=[{"id": ghost_id, "name": "ghost", "type": "library"}]),
                TABLE_GROUP_ID, "public",
            )
        assert any(ghost_id in w for w in diff.warnings)

    def test_missing_group_produces_error(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", return_value=[]):
            diff = compute_diff(_valid_doc(), TABLE_GROUP_ID, "public")
        assert diff.has_errors

    def test_total_changes_counted_correctly(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(_valid_doc(version="2.0.0", status="deprecated"), TABLE_GROUP_ID, "public")
        assert diff.total_changes == 2

    def test_no_changes_when_doc_matches_db(self):
        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            # active status and commerce domain already match _GROUP_ROW
            diff = compute_diff(_valid_doc(version="1.0.0", status="active", domain="commerce"), TABLE_GROUP_ID, "public")
        assert diff.total_changes == 0


# ---------------------------------------------------------------------------
# ContractDiff
# ---------------------------------------------------------------------------

class Test_ContractDiff:
    def test_no_errors_by_default(self):
        assert not ContractDiff().has_errors

    def test_has_errors_when_errors_present(self):
        assert ContractDiff(errors=["oops"]).has_errors

    def test_summary_no_changes(self):
        assert ContractDiff().summary() == "no changes"

    def test_summary_includes_contract_changes(self):
        diff = ContractDiff(contract_updates={"contract_version": "2.0.0"})
        assert "contract field" in diff.summary()

    def test_summary_includes_test_changes(self):
        diff = ContractDiff(test_updates=[{"id": str(uuid4()), "threshold_value": "500"}])
        assert "test definition" in diff.summary()

    def test_total_changes_sums_all_buckets(self):
        diff = ContractDiff(
            contract_updates={"contract_version": "2.0.0"},
            table_group_updates={"business_domain": "finance"},
            test_updates=[{"id": str(uuid4())}],
        )
        assert diff.total_changes == 3


# ---------------------------------------------------------------------------
# apply_diff
# ---------------------------------------------------------------------------

class Test_ApplyDiff:
    def test_raises_when_diff_has_errors(self):
        with pytest.raises(ValueError, match="Cannot apply diff"):
            apply_diff(ContractDiff(errors=["parse error"]), TABLE_GROUP_ID, "public")

    def test_no_queries_when_no_changes(self):
        with patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec:
            apply_diff(ContractDiff(), TABLE_GROUP_ID, "public")
        mock_exec.assert_not_called()

    def test_contract_update_generates_parameterized_sql(self):
        with patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec:
            apply_diff(ContractDiff(contract_updates={"contract_version": "2.0.0"}), TABLE_GROUP_ID, "public")
        calls = mock_exec.call_args[0][0]
        sql_list = [q for q, _ in calls]
        params_list = [p for _, p in calls]
        assert any("table_groups" in q and "contract_version" in q for q in sql_list)
        assert any(p.get("tg_id") == TABLE_GROUP_ID for p in params_list)
        assert any(p.get("p_contract_version") == "2.0.0" for p in params_list)

    def test_table_group_update_generates_sql(self):
        with patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec:
            apply_diff(ContractDiff(table_group_updates={"business_domain": "finance"}), TABLE_GROUP_ID, "public")
        calls = mock_exec.call_args[0][0]
        sql_list = [q for q, _ in calls]
        assert any("table_groups" in q and "business_domain" in q for q in sql_list)

    def test_test_update_sets_lock_refresh(self):
        test_id = str(uuid4())
        with patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec:
            apply_diff(ContractDiff(test_updates=[{"id": test_id, "threshold_value": "500"}]), TABLE_GROUP_ID, "public")
        calls = mock_exec.call_args[0][0]
        sql_list = [q for q, _ in calls]
        params_list = {k: v for _, p in calls for k, v in (p or {}).items()}
        assert any("lock_refresh" in q and "test_definitions" in q for q in sql_list)
        assert params_list.get("lock_y") == "Y"
        assert params_list.get("test_id") == test_id

    def test_contract_and_group_updates_merged_into_one_query(self):
        """contract_updates and table_group_updates both target table_groups — one SQL statement."""
        test_id = str(uuid4())
        diff = ContractDiff(
            contract_updates={"contract_status": "deprecated"},
            table_group_updates={"profiling_delay_days": 7},
            test_updates=[{"id": test_id, "threshold_value": "9999"}],
        )
        with patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec:
            apply_diff(diff, TABLE_GROUP_ID, "public")
        # 1 merged table_groups UPDATE + 1 test_definitions UPDATE = 2 queries
        assert len(mock_exec.call_args[0][0]) == 2

    def test_unknown_column_in_diff_raises(self):
        """Diff with an unknown column is rejected — guards against injection via the diff object."""
        with pytest.raises(ValueError, match="Unexpected table_groups columns"):
            apply_diff(
                ContractDiff(contract_updates={"evil_col; DROP TABLE x--": "x"}),
                TABLE_GROUP_ID, "public",
            )


# ---------------------------------------------------------------------------
# Round-trip: export structure → validate → compute_diff
# ---------------------------------------------------------------------------

class Test_RoundTrip:
    def test_exported_yaml_passes_validation(self):
        contract = {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "id": TABLE_GROUP_ID,
            "version": "1.0.0",
            "status": "active",
            "name": "round_trip_group",
        }
        raw = yaml.dump(contract, default_flow_style=False, allow_unicode=True, sort_keys=False)
        doc, errors = validate_contract_yaml(raw)
        assert errors == []
        assert doc is not None

    def test_threshold_change_detected_after_export(self):
        contract = {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "id": TABLE_GROUP_ID,
            "version": "1.0.0",
            "status": "active",
            "name": "group",
            "quality": [{
                "id": TEST_DEF_ID,
                "name": "row count",
                "type": "library",
                "metric": "rowCount",
                "mustBeGreaterOrEqualTo": 99999,
            }],
        }
        raw = yaml.dump(contract)
        doc, errors = validate_contract_yaml(raw)
        assert not errors

        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(doc, TABLE_GROUP_ID, "public")

        assert any(u.get("threshold_value") == "99999" for u in diff.test_updates)

    def test_no_changes_on_identical_round_trip(self):
        """A contract that mirrors current DB state should produce zero changes."""
        contract = {
            "apiVersion": "v3.1.0",
            "kind": "DataContract",
            "id": TABLE_GROUP_ID,
            "version": "1.0.0",   # same as _GROUP_ROW
            "status": "active",   # same as _GROUP_ROW
            "name": "orders_group",
            "domain": "commerce",  # same as _GROUP_ROW
        }
        raw = yaml.dump(contract)
        doc, errors = validate_contract_yaml(raw)
        assert not errors

        with patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch()):
            diff = compute_diff(doc, TABLE_GROUP_ID, "public")

        assert diff.total_changes == 0


# ---------------------------------------------------------------------------
# Integration: run_import_data_contract orchestration
# ---------------------------------------------------------------------------

class Test_RunImportDataContract:
    def _run(self, yaml_content: str, group_rows=None, test_rows=None, dry_run: bool = False):
        with (
            patch("testgen.commands.import_data_contract.get_tg_schema", return_value="public"),
            patch("testgen.commands.import_data_contract.fetch_dict_from_db", side_effect=_db_fetch(group_rows, test_rows)),
            patch("testgen.commands.import_data_contract.execute_db_queries") as mock_exec,
        ):
            diff = run_import_data_contract(yaml_content, TABLE_GROUP_ID, dry_run=dry_run)
        return diff, mock_exec

    def test_valid_yaml_with_changes_applies_updates(self):
        diff, mock_exec = self._run(_valid_yaml(version="2.0.0"))
        assert not diff.has_errors
        assert diff.contract_updates.get("contract_version") == "2.0.0"
        mock_exec.assert_called_once()

    def test_dry_run_does_not_call_execute(self):
        diff, mock_exec = self._run(_valid_yaml(version="2.0.0"), dry_run=True)
        assert not diff.has_errors
        mock_exec.assert_not_called()

    def test_invalid_yaml_returns_errors_without_writing(self):
        diff, mock_exec = self._run("{ not: valid: yaml: [")
        assert diff.has_errors
        mock_exec.assert_not_called()

    def test_wrong_api_version_returns_errors(self):
        diff, mock_exec = self._run(_valid_yaml(apiVersion="v2.0.0"))
        assert diff.has_errors
        mock_exec.assert_not_called()

    def test_no_changes_does_not_call_execute(self):
        # _valid_yaml() matches _GROUP_ROW defaults except version
        diff, mock_exec = self._run(_valid_yaml(version="1.0.0", status="active", domain="commerce"))
        assert not diff.has_errors
        assert diff.total_changes == 0
        mock_exec.assert_not_called()

    def test_unknown_table_group_returns_error(self):
        diff, mock_exec = self._run(_valid_yaml(), group_rows=[])
        assert diff.has_errors
        mock_exec.assert_not_called()

    def test_unmatched_quality_rule_produces_warning(self):
        ghost_id = str(uuid4())
        yaml_with_ghost = _valid_yaml(quality=[{"id": ghost_id, "type": "library", "name": "ghost rule"}])
        diff, _ = self._run(yaml_with_ghost)
        assert any(ghost_id in w for w in diff.warnings)

    def test_quality_threshold_update_applied(self):
        yaml_content = _valid_yaml(quality=[{
            "id": TEST_DEF_ID, "name": "Row count check", "type": "library",
            "mustBeGreaterOrEqualTo": 9999,
        }])
        diff, mock_exec = self._run(yaml_content)
        assert any(u.get("threshold_value") == "9999" for u in diff.test_updates)
        mock_exec.assert_called_once()
