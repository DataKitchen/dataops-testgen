"""Unit tests for create_data_contract.py"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

pytestmark = pytest.mark.unit

VALID_YAML = """\
apiVersion: v3.1.0
kind: DataContract
id: test-001
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


def test_create_contract_from_yaml_success():
    from testgen.commands.create_data_contract import create_contract_from_yaml
    with patch("testgen.commands.create_data_contract.has_any_version", return_value=False), \
         patch("testgen.commands.create_data_contract.save_contract_version", return_value=0) as mock_save:
        version = create_contract_from_yaml("tg-id", VALID_YAML, "initial")
    assert version == 0
    mock_save.assert_called_once_with("tg-id", VALID_YAML, "initial")


def test_create_contract_raises_when_version_exists():
    from testgen.commands.create_data_contract import create_contract_from_yaml
    with patch("testgen.commands.create_data_contract.has_any_version", return_value=True):
        with pytest.raises(ValueError, match="already exists"):
            create_contract_from_yaml("tg-id", VALID_YAML)


def test_create_contract_raises_on_invalid_yaml():
    from testgen.commands.create_data_contract import create_contract_from_yaml
    with pytest.raises(ValueError, match="apiVersion"):
        create_contract_from_yaml("tg-id", MISSING_API_VERSION)
