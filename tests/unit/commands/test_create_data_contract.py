"""Unit tests for create_data_contract.py"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

TG_ID = "aaaaaaaa-0000-0000-0000-000000000001"
CONTRACT_ID = "bbbbbbbb-0000-0000-0000-000000000002"

VALID_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-001
schema: []
"""

VALID_YAML_WITH_TITLE = """\
apiVersion: v3.1.0
kind: DataContract
info:
  title: My Custom Contract
schema: []
"""

MISSING_API_VERSION = """\
kind: DataContract
id: test-001
"""

WRONG_KIND = """\
apiVersion: v3.1.0
kind: SomeOtherThing
"""

UNPARSEABLE = "{ not yaml ]["


# ---------------------------------------------------------------------------
# validate_odcs_header
# ---------------------------------------------------------------------------

def test_validate_odcs_header_valid():
    from testgen.commands.create_data_contract import validate_odcs_header
    assert validate_odcs_header(VALID_YAML) == []


def test_validate_odcs_header_missing_api_version():
    from testgen.commands.create_data_contract import validate_odcs_header
    errors = validate_odcs_header(MISSING_API_VERSION)
    assert any("apiVersion" in e for e in errors)


def test_validate_odcs_header_wrong_kind():
    from testgen.commands.create_data_contract import validate_odcs_header
    errors = validate_odcs_header(WRONG_KIND)
    assert any("kind" in e for e in errors)


def test_validate_odcs_header_unparseable():
    from testgen.commands.create_data_contract import validate_odcs_header
    errors = validate_odcs_header(UNPARSEABLE)
    assert len(errors) == 1
    assert "Not valid YAML" in errors[0]


# ---------------------------------------------------------------------------
# create_contract_from_yaml — helpers
# ---------------------------------------------------------------------------

def _mock_tg_rows(name: str = "My Group", project_code: str = "proj") -> list[dict]:
    return [{"table_groups_name": name, "project_code": project_code}]


def _patch_all(tg_rows=None, contract_ids=None, version=0):
    """Return a context manager stack for the three external calls."""
    import contextlib
    tg_rows = tg_rows or _mock_tg_rows()
    contract_ids = contract_ids or {"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}

    return (
        patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"),
        patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=tg_rows),
        patch("testgen.commands.create_data_contract.create_contract", return_value=contract_ids),
        patch("testgen.commands.create_data_contract.save_contract_version", return_value=version),
    )


# ---------------------------------------------------------------------------
# create_contract_from_yaml — correct call signatures (Critical regression)
# ---------------------------------------------------------------------------

class Test_CreateContractFromYaml:

    def test_save_contract_version_called_with_contract_id_first(self):
        """save_contract_version must receive (contract_id, table_group_id, yaml_content).

        Regression: previously called as (table_group_id, yaml_content, label) — wrong order.
        """
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db",
                   return_value=_mock_tg_rows()), \
             patch("testgen.commands.create_data_contract.create_contract",
                   return_value={"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}), \
             patch("testgen.commands.create_data_contract.save_contract_version",
                   return_value=0) as mock_save:
            from testgen.commands.create_data_contract import create_contract_from_yaml
            create_contract_from_yaml(TG_ID, VALID_YAML, "initial")

        args = mock_save.call_args
        # First positional arg must be contract_id, not table_group_id or yaml string
        assert args[0][0] == CONTRACT_ID, (
            f"Expected contract_id={CONTRACT_ID!r} as first arg but got {args[0][0]!r}"
        )
        assert args[0][1] == TG_ID, (
            f"Expected table_group_id={TG_ID!r} as second arg but got {args[0][1]!r}"
        )
        assert args[0][2] == VALID_YAML, "Third arg must be yaml_content"

    def test_label_forwarded_to_save_contract_version(self):
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db",
                   return_value=_mock_tg_rows()), \
             patch("testgen.commands.create_data_contract.create_contract",
                   return_value={"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}), \
             patch("testgen.commands.create_data_contract.save_contract_version",
                   return_value=0) as mock_save:
            from testgen.commands.create_data_contract import create_contract_from_yaml
            create_contract_from_yaml(TG_ID, VALID_YAML, label="v0")

        assert mock_save.call_args[1].get("label") == "v0"

    def test_returns_version_number(self):
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db",
                   return_value=_mock_tg_rows()), \
             patch("testgen.commands.create_data_contract.create_contract",
                   return_value={"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}), \
             patch("testgen.commands.create_data_contract.save_contract_version", return_value=3):
            from testgen.commands.create_data_contract import create_contract_from_yaml
            version = create_contract_from_yaml(TG_ID, VALID_YAML)

        assert version == 3

    def test_raises_on_invalid_yaml(self):
        from testgen.commands.create_data_contract import create_contract_from_yaml
        with pytest.raises(ValueError, match="apiVersion"):
            create_contract_from_yaml(TG_ID, MISSING_API_VERSION)

    def test_raises_when_table_group_not_found(self):
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db", return_value=[]):
            from testgen.commands.create_data_contract import create_contract_from_yaml
            with pytest.raises(ValueError, match="not found"):
                create_contract_from_yaml(TG_ID, VALID_YAML)

    def test_contract_name_from_yaml_info_title(self):
        """Contract name is extracted from info.title when present."""
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db",
                   return_value=_mock_tg_rows(name="Fallback Group")), \
             patch("testgen.commands.create_data_contract.create_contract",
                   return_value={"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}) as mock_create, \
             patch("testgen.commands.create_data_contract.save_contract_version", return_value=0):
            from testgen.commands.create_data_contract import create_contract_from_yaml
            create_contract_from_yaml(TG_ID, VALID_YAML_WITH_TITLE)

        name_used = mock_create.call_args[0][0]
        assert name_used == "My Custom Contract"

    def test_contract_name_falls_back_to_table_group_name(self):
        """Contract name falls back to table_groups_name when info.title is absent."""
        with patch("testgen.commands.create_data_contract.get_tg_schema", return_value="tg"), \
             patch("testgen.commands.create_data_contract.fetch_dict_from_db",
                   return_value=_mock_tg_rows(name="My Group")), \
             patch("testgen.commands.create_data_contract.create_contract",
                   return_value={"contract_id": CONTRACT_ID, "test_suite_id": "ts-1"}) as mock_create, \
             patch("testgen.commands.create_data_contract.save_contract_version", return_value=0):
            from testgen.commands.create_data_contract import create_contract_from_yaml
            create_contract_from_yaml(TG_ID, VALID_YAML)

        name_used = mock_create.call_args[0][0]
        assert name_used == "My Group"
