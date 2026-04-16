# tests/unit/commands/test_export_data_contract_filters.py
"""Tests for filter params added to run_export_data_contract. pytest -m unit"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import inspect
import pytest

pytestmark = pytest.mark.unit


def test_signature_has_suite_ids_param():
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    assert "suite_ids" in sig.parameters


def test_signature_has_table_names_param():
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    assert "table_names" in sig.parameters


def test_signature_has_include_profiling_param():
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    assert "include_profiling" in sig.parameters


def test_signature_has_include_ddl_param():
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    assert "include_ddl" in sig.parameters


def test_signature_has_include_monitors_param():
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    assert "include_monitors" in sig.parameters


def test_defaults_preserve_existing_behavior():
    """Calling with all defaults must not change existing behavior."""
    from testgen.commands.export_data_contract import run_export_data_contract
    sig = inspect.signature(run_export_data_contract)
    params = sig.parameters
    assert params["suite_ids"].default is None
    assert params["table_names"].default is None
    assert params["include_profiling"].default is True
    assert params["include_ddl"].default is True
    assert params["include_monitors"].default is True
