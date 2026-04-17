"""CLI tests for data contract commands: export, import, create, run."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

pytestmark = pytest.mark.unit

VALID_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-001
schema: []
"""

TG_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


# ---------------------------------------------------------------------------
# export-data-contract
# ---------------------------------------------------------------------------

class Test_ExportDataContract:
    def test_export_prints_to_stdout(self, tmp_path):
        from testgen.__main__ import cli

        with patch("testgen.__main__.run_export_data_contract") as mock_export:
            mock_export.return_value = None
            runner = CliRunner()
            result = runner.invoke(cli, ["export-data-contract", "-tg", TG_ID])

        assert result.exit_code == 0
        mock_export.assert_called_once_with(TG_ID, None)

    def test_export_writes_to_file(self, tmp_path):
        from testgen.__main__ import cli

        out = tmp_path / "contract.yaml"
        with patch("testgen.__main__.run_export_data_contract") as mock_export:
            mock_export.return_value = None
            runner = CliRunner()
            result = runner.invoke(cli, ["export-data-contract", "-tg", TG_ID, "-o", str(out)])

        assert result.exit_code == 0
        mock_export.assert_called_once_with(TG_ID, str(out))

    def test_export_requires_table_group_id(self):
        from testgen.__main__ import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["export-data-contract"])
        assert result.exit_code != 0
        assert "table-group-id" in result.output or "tg" in result.output


# ---------------------------------------------------------------------------
# import-data-contract
# ---------------------------------------------------------------------------

class Test_ImportDataContract:
    def _make_diff(self, *, changes=1, errors=None, warnings=None, contract_updates=None, test_updates=None):
        diff = MagicMock()
        diff.errors = errors or []
        diff.warnings = warnings or []
        diff.total_changes = changes
        diff.contract_updates = contract_updates or []
        diff.table_group_updates = []
        diff.test_updates = test_updates or []
        diff.summary.return_value = f"{changes} change(s)"
        return diff

    def test_dry_run_shows_diff_no_write(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)
        diff = self._make_diff(changes=2, contract_updates=["status"])

        with patch("testgen.__main__.run_import_data_contract", return_value=diff) as mock_import:
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data-contract", "-tg", TG_ID, "-i", str(yaml_file), "--dry-run"
            ])

        assert result.exit_code == 0
        assert "--dry-run" in result.output or "dry-run" in result.output
        # Only one call (dry_run=True preview), no second apply call
        mock_import.assert_called_once()

    def test_no_changes_exits_cleanly(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)
        diff = self._make_diff(changes=0)

        with patch("testgen.__main__.run_import_data_contract", return_value=diff):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data-contract", "-tg", TG_ID, "-i", str(yaml_file), "--yes"
            ])

        assert result.exit_code == 0
        assert "up to date" in result.output

    def test_validation_errors_exit_nonzero(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)
        diff = self._make_diff(errors=["Schema mismatch"])

        with patch("testgen.__main__.run_import_data_contract", return_value=diff):
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data-contract", "-tg", TG_ID, "-i", str(yaml_file), "--yes"
            ])

        assert result.exit_code != 0

    def test_yes_flag_applies_without_prompt(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)
        diff = self._make_diff(changes=1, contract_updates=["status"])

        with patch("testgen.__main__.run_import_data_contract", return_value=diff) as mock_import:
            runner = CliRunner()
            result = runner.invoke(cli, [
                "import-data-contract", "-tg", TG_ID, "-i", str(yaml_file), "--yes"
            ])

        assert result.exit_code == 0
        assert mock_import.call_count == 2  # dry-run preview + apply


# ---------------------------------------------------------------------------
# create-contract
# ---------------------------------------------------------------------------

_TG_DB_ROW = [{"project_code": "P1", "table_groups_name": "orders_tg"}]
_CONTRACT_IDS = {"contract_id": "cccccccc-0000-0000-0000-000000000001", "test_suite_id": "ssssssss-0000-0000-0000-000000000002"}


class Test_CreateContract:
    def _base_patches(self) -> list:
        return [
            patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"),
            patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=_TG_DB_ROW),
            patch("testgen.commands.create_data_contract.create_contract", return_value=_CONTRACT_IDS),
            patch("testgen.commands.create_data_contract.save_contract_version", return_value=0),
        ]

    def test_create_success(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)

        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=_TG_DB_ROW), \
             patch("testgen.commands.create_data_contract.create_contract", return_value=_CONTRACT_IDS), \
             patch("testgen.commands.create_data_contract.save_contract_version", return_value=0):
            runner = CliRunner()
            result = runner.invoke(cli, ["create-contract", "-tg", TG_ID, "-i", str(yaml_file)])

        assert result.exit_code == 0
        assert "version 0" in result.output.lower()

    def test_create_fails_when_table_group_not_found(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)

        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, ["create-contract", "-tg", TG_ID, "-i", str(yaml_file)])

        assert result.exit_code != 0
        assert "Error" in result.output

    def test_create_with_label(self, tmp_path):
        from testgen.__main__ import cli

        yaml_file = tmp_path / "contract.yaml"
        yaml_file.write_text(VALID_YAML)

        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=_TG_DB_ROW), \
             patch("testgen.commands.create_data_contract.create_contract", return_value=_CONTRACT_IDS), \
             patch("testgen.commands.create_data_contract.save_contract_version", return_value=0) as mock_save:
            runner = CliRunner()
            runner.invoke(cli, [
                "create-contract", "-tg", TG_ID, "-i", str(yaml_file), "--label", "v1 baseline"
            ])

        assert mock_save.call_args[1].get("label") == "v1 baseline" or mock_save.call_args[0][3] == "v1 baseline"

    def test_create_requires_input_file(self):
        from testgen.__main__ import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["create-contract", "-tg", TG_ID])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# run-contract-tests
# ---------------------------------------------------------------------------

class Test_RunContractTests:
    _SUITES = [
        {"suite_id": "suite-id-1", "suite_name": "orders_suite"},
        {"suite_id": "suite-id-2", "suite_name": "customers_suite"},
    ]

    def test_runs_all_in_scope_suites(self):
        from testgen.__main__ import cli

        with patch("testgen.__main__.get_tg_schema", return_value="tg"), \
             patch("testgen.common.database.database_service.fetch_dict_from_db", return_value=self._SUITES), \
             patch("testgen.__main__.run_test_execution", return_value="Done") as mock_run:
            runner = CliRunner()
            result = runner.invoke(cli, ["run-contract-tests", "-tg", TG_ID])

        assert result.exit_code == 0
        assert mock_run.call_count == 2
        mock_run.assert_any_call("suite-id-1")
        mock_run.assert_any_call("suite-id-2")

    def test_exits_nonzero_when_no_suites(self):
        from testgen.__main__ import cli

        with patch("testgen.__main__.get_tg_schema", return_value="tg"), \
             patch("testgen.common.database.database_service.fetch_dict_from_db", return_value=[]):
            runner = CliRunner()
            result = runner.invoke(cli, ["run-contract-tests", "-tg", TG_ID])

        assert result.exit_code != 0
        assert "No in-scope" in result.output

    def test_reports_suite_failures_and_exits_nonzero(self):
        from testgen.__main__ import cli

        def _run(suite_id: str) -> str:
            if suite_id == "suite-id-1":
                raise RuntimeError("connection refused")
            return "Done"

        with patch("testgen.__main__.get_tg_schema", return_value="tg"), \
             patch("testgen.common.database.database_service.fetch_dict_from_db", return_value=self._SUITES), \
             patch("testgen.__main__.run_test_execution", side_effect=_run):
            runner = CliRunner()
            result = runner.invoke(cli, ["run-contract-tests", "-tg", TG_ID])

        assert result.exit_code != 0
        assert "FAILED" in result.output or "failed" in result.output.lower()

    def test_continues_after_one_suite_fails(self):
        from testgen.__main__ import cli

        call_log: list[str] = []

        def _run(suite_id: str) -> str:
            call_log.append(suite_id)
            if suite_id == "suite-id-1":
                raise RuntimeError("boom")
            return "Done"

        with patch("testgen.__main__.get_tg_schema", return_value="tg"), \
             patch("testgen.common.database.database_service.fetch_dict_from_db", return_value=self._SUITES), \
             patch("testgen.__main__.run_test_execution", side_effect=_run):
            runner = CliRunner()
            runner.invoke(cli, ["run-contract-tests", "-tg", TG_ID])

        # Both suites were attempted despite first failing
        assert call_log == ["suite-id-1", "suite-id-2"]
