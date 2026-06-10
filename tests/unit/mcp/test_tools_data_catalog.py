from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def grant_perms():
    """Grant role_a disposition + view_pii on demo (overrides the conftest matrix)."""
    with patch("testgen.mcp.permissions.PluginHook") as hook:
        hook.instance.return_value.rbac.get_roles_with_permission.side_effect = (
            lambda perm: ["role_a"] if perm in ("disposition", "view_pii", "catalog", "view") else []
        )
        yield hook


def _mock_table_group():
    tg = MagicMock()
    tg.id = uuid4()
    tg.project_code = "demo"
    tg.table_groups_name = "sales_group"
    tg.profile_flag_cdes = True
    tg.profile_flag_pii = True
    return tg


def _mock_entity():
    """A stand-in table/column row that records attribute writes."""
    return MagicMock()


def _patch(tg=None, table_rows=None, column_rows=None):
    """Patch the resolution boundary: TableGroup.get, DataTable/DataColumnChars.select_where."""
    tg = tg or _mock_table_group()
    mock_tg_cls = patch("testgen.mcp.tools.common.TableGroup").start()
    mock_tg_cls.get.return_value = tg
    mock_dt = patch("testgen.mcp.tools.data_catalog.DataTable").start()
    mock_dt.select_where.return_value = table_rows if table_rows is not None else []
    mock_dcc = patch("testgen.mcp.tools.data_catalog.DataColumnChars").start()
    mock_dcc.select_where.return_value = column_rows if column_rows is not None else []
    return tg, mock_dt, mock_dcc


@pytest.fixture(autouse=True)
def _cleanup_patches():
    yield
    patch.stopall()


# ----------------------------------------------------------------------
# Happy paths
# ----------------------------------------------------------------------

def test_table_description_update(db_session_mock):
    table = _mock_entity()
    _patch(table_rows=[table])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "description": "Order header table"},
    ])

    assert table.description == "Order header table"
    assert "Updated" in result
    assert "1" in result


def test_column_pii_true_stores_manual(db_session_mock):
    column = _mock_entity()
    _patch(column_rows=[column])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "ssn", "pii": True},
    ])

    assert column.pii_flag == "MANUAL"


def test_column_pii_false_clears(db_session_mock):
    column = _mock_entity()
    _patch(column_rows=[column])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "ssn", "pii": False},
    ])

    assert column.pii_flag is None


# ----------------------------------------------------------------------
# Per-row isolation
# ----------------------------------------------------------------------

def test_one_bad_row_does_not_block_others(db_session_mock):
    good = _mock_entity()
    _tg, _mock_dt, mock_dcc = _patch()

    # First column resolves to the good row; the second is not found in the catalog.
    calls = {"n": 0}

    def _resolve(*_a, **_k):
        calls["n"] += 1
        return [good] if calls["n"] == 1 else []

    mock_dcc.select_where.side_effect = _resolve

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    tg_id = str(uuid4())
    result = update_catalog_metadata([
        {"table_group_id": tg_id, "table_name": "orders", "column_name": "known", "description": "ok"},
        {"table_group_id": tg_id, "table_name": "orders", "column_name": "missing", "description": "x"},
    ])

    assert good.description == "ok"
    assert "Updated" in result and "Failed" in result
    assert "not found" in result.lower()


# ----------------------------------------------------------------------
# Validation / rejection
# ----------------------------------------------------------------------

def test_xde_on_table_row_rejected(db_session_mock):
    _patch(table_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "xde": True},
    ])

    assert "Failed" in result
    assert "xde" in result.lower() and "column" in result.lower()


def test_pii_without_view_pii_rejected(db_session_mock):
    _patch(column_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    with patch("testgen.mcp.tools.data_catalog.get_project_permissions") as mock_perms:
        perms = MagicMock()
        perms.has_permission.return_value = False  # no view_pii
        mock_perms.return_value = perms
        result = update_catalog_metadata([
            {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "ssn", "pii": True},
        ])

    assert "Failed" in result
    assert "view_pii" not in result
    assert "permission to view PII" in result


def test_description_too_long_rejected(db_session_mock):
    _patch(table_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "description": "x" * 1001},
    ])

    assert "Failed" in result
    assert "description" in result.lower()


def test_non_boolean_pii_rejected(db_session_mock):
    _patch(column_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "ssn", "pii": "high"},
    ])

    assert "Failed" in result


def test_unknown_table_not_found(db_session_mock):
    _patch(table_rows=[])  # select_where finds nothing

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "ghost", "description": "x"},
    ])

    assert "Failed" in result
    assert "not found" in result.lower()


def test_inaccessible_table_group(db_session_mock):
    tg, _dt, _dcc = _patch()
    # TableGroup.get returns None → resolve_table_group raises not-found-or-not-accessible
    patch.stopall()
    mock_tg_cls = patch("testgen.mcp.tools.common.TableGroup").start()
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "description": "x"},
    ])

    assert "Failed" in result
    assert "not found or not accessible" in result.lower()


# ----------------------------------------------------------------------
# Side-effect notices
# ----------------------------------------------------------------------

def test_cde_write_auto_disables_flag(db_session_mock):
    tg = _mock_table_group()
    column = _mock_entity()
    _patch(tg=tg, column_rows=[column])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "amount", "cde": True},
    ])

    assert tg.profile_flag_cdes is False
    assert "Auto-disabled profile_flag_cdes" in result


def test_cde_noop_does_not_disable_flag(db_session_mock):
    tg = _mock_table_group()
    column = _mock_entity()
    column.critical_data_element = False  # already false; cde: false is a no-op
    _patch(tg=tg, column_rows=[column])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "amount", "cde": False},
    ])

    assert tg.profile_flag_cdes is True
    assert "Auto-disabled profile_flag_cdes" not in result


def test_pii_noop_does_not_disable_flag(db_session_mock):
    tg = _mock_table_group()
    column = _mock_entity()
    column.pii_flag = None  # already cleared; pii: false is a no-op
    _patch(tg=tg, column_rows=[column])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "ssn", "pii": False},
    ])

    assert tg.profile_flag_pii is True
    assert "Auto-disabled profile_flag_pii" not in result


def test_table_cde_inheritance_notice(db_session_mock):
    _patch(table_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "cde": True},
    ])

    assert "affects all columns" in result.lower()


def test_xde_exclusion_notice(db_session_mock):
    _patch(column_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders", "column_name": "scratch", "xde": True},
    ])

    assert "excluded" in result.lower()
    assert "next profiling run" in result.lower()
    assert "skip" in result.lower()


def test_empty_fields_skipped(db_session_mock):
    _patch(table_rows=[_mock_entity()])

    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    result = update_catalog_metadata([
        {"table_group_id": str(uuid4()), "table_name": "orders"},
    ])

    assert "Skipped" in result


def test_empty_updates_raises(db_session_mock):
    from testgen.mcp.exceptions import MCPUserError
    from testgen.mcp.tools.data_catalog import update_catalog_metadata
    with pytest.raises(MCPUserError):
        update_catalog_metadata([])
