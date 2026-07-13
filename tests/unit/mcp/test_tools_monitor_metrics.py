"""Tests for the MCP Metric monitor write tools."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.custom_test_validation import CustomQueryResult
from testgen.common.enums import MonitorType
from testgen.mcp.exceptions import (
    MCPPermissionDenied,
    MCPResourceNotAccessible,
    MCPUserError,
)
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.monitor_metrics"


@pytest.fixture(autouse=True)
def _stub_get_current_session():
    """Neutralize ``pii_masking.get_current_session`` so ``get_pii_columns`` can execute.

    ``testgen.common.pii_masking`` binds ``get_current_session`` at import time, so the
    ``mcp_user`` fixture's patch of ``testgen.common.models.get_current_session`` never
    reaches inside it. Uses a session mock whose ``.execute(...).mappings().all()``
    returns ``[]`` — the ``no PII columns`` outcome, harmless for every test that
    doesn't override ``get_pii_columns`` directly.
    """
    session = MagicMock()
    session.execute.return_value.mappings.return_value.all.return_value = []
    with patch("testgen.common.pii_masking.get_current_session", return_value=session):
        yield


def _patch_perms(allowed=("demo",), memberships=None, permission="edit"):
    memberships = memberships or dict.fromkeys(allowed, "role_a")
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission=permission, username="test_user",
        ),
    )


def _mock_table_group(**overrides) -> MagicMock:
    tg = MagicMock()
    tg.id = overrides.get("id", uuid4())
    tg.project_code = overrides.get("project_code", "demo")
    tg.table_groups_name = overrides.get("table_groups_name", "Sales")
    tg.table_group_schema = overrides.get("table_group_schema", "public")
    tg.monitor_test_suite_id = overrides.get("monitor_test_suite_id", uuid4())
    tg.connection_id = overrides.get("connection_id", 1)
    return tg


def _mock_monitor_suite(**overrides) -> MagicMock:
    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.is_monitor = True
    return suite


def _mock_monitor(test_type=MonitorType.METRIC.value, **overrides) -> MagicMock:
    monitor = MagicMock()
    monitor.id = overrides.get("id", uuid4())
    monitor.test_type = test_type
    monitor.table_name = overrides.get("table_name", "orders")
    monitor.column_name = overrides.get("column_name", "Daily revenue")
    monitor.custom_query = overrides.get("custom_query", "SELECT SUM(amount) FROM orders")
    monitor.test_suite_id = overrides.get("test_suite_id", uuid4())
    monitor.table_groups_id = overrides.get("table_groups_id", uuid4())
    return monitor


def _mock_connection(**overrides) -> MagicMock:
    conn = MagicMock()
    conn.connection_id = overrides.get("connection_id", 1)
    conn.connection_name = overrides.get("connection_name", "warehouse")
    return conn


# ---------------------------------------------------------------------------
# create_metric_monitor
# ---------------------------------------------------------------------------


@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.TestDefinition")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_create_metric_monitor_happy_path(mock_resolve, mock_td_cls, mock_in_catalog, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sales")
    suite = _mock_monitor_suite()
    mock_resolve.return_value = (tg, suite)

    saved_id = uuid4()
    instance = MagicMock()
    instance.id = saved_id
    instance.table_name = "orders"
    instance.column_name = "Daily revenue"
    instance.custom_query = "SELECT SUM(amount) FROM orders"
    mock_td_cls.return_value = instance

    from testgen.mcp.tools.monitor_metrics import create_metric_monitor

    with _patch_perms():
        out = create_metric_monitor(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_name="Daily revenue",
            metric_expression="SELECT SUM(amount) FROM orders",
        )

    mock_td_cls.assert_called_once()
    kwargs = mock_td_cls.call_args.kwargs
    assert kwargs["test_type"] == "Metric_Trend"
    assert kwargs["test_suite_id"] == suite.id
    assert kwargs["table_groups_id"] == tg.id
    assert kwargs["schema_name"] == "public"
    assert kwargs["table_name"] == "orders"
    assert kwargs["column_name"] == "Daily revenue"
    assert kwargs["custom_query"] == "SELECT SUM(amount) FROM orders"
    assert kwargs["history_calculation"] == "PREDICT"
    # UI default parity (monitors_dashboard.py new_metric defaults) — must match
    # to avoid silent divergence at runtime
    assert kwargs["history_calculation_upper"] is None
    assert kwargs["history_lookback"] is None
    assert kwargs["test_active"] is True
    assert kwargs["lock_refresh"] is True
    instance.save.assert_called_once()

    assert "Metric Monitor created" in out
    assert f"`{saved_id}`" in out
    assert "Daily revenue" in out
    assert "Predictive" in out
    # Internal codes never leak
    assert "Metric_Trend" not in out
    assert "PREDICT" not in out
    assert "custom_query" not in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_create_metric_monitor_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitor_metrics import create_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_metric_monitor(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_name="X",
            metric_expression="SELECT 1",
        )

    assert "Monitoring is not enabled" in str(exc.value)
    assert "enable_monitors" in str(exc.value)


@patch(f"{MODULE}._table_in_catalog", return_value=False)
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_create_metric_monitor_table_not_in_catalog(mock_resolve, mock_in_catalog, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    from testgen.mcp.tools.monitor_metrics import create_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_metric_monitor(
            table_group_id=str(tg.id),
            table_name="missing_table",
            metric_name="X",
            metric_expression="SELECT 1",
        )

    assert "missing_table" in str(exc.value)
    assert "not in the table group's catalog" in str(exc.value)


@pytest.mark.parametrize("field, value, missing", [
    ("metric_name", "", "metric_name"),
    ("metric_name", "   ", "metric_name"),
    ("metric_expression", "", "metric_expression"),
    ("metric_expression", "   ", "metric_expression"),
])
def test_create_metric_monitor_rejects_empty_fields(field, value, missing, db_session_mock):
    from testgen.mcp.tools.monitor_metrics import create_metric_monitor

    args = {
        "table_group_id": str(uuid4()),
        "table_name": "orders",
        "metric_name": "X",
        "metric_expression": "SELECT 1",
    }
    args[field] = value
    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_metric_monitor(**args)
    assert missing in str(exc.value)


def test_create_metric_monitor_requires_edit_permission(db_session_mock):
    """A user with view-only project access cannot create monitors —
    the `@mcp_permission('edit')` gate rejects before any tool body runs."""
    from testgen.mcp.tools.monitor_metrics import create_metric_monitor

    # role_b has view but no edit (per TEST_PERM_MATRIX)
    perms_patch = patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships={"demo": "role_b"}, permission="edit", username="test_user",
        ),
    )
    with perms_patch, pytest.raises(MCPPermissionDenied):
        create_metric_monitor(
            table_group_id=str(uuid4()),
            table_name="orders",
            metric_name="X",
            metric_expression="SELECT 1",
        )


# ---------------------------------------------------------------------------
# update_metric_monitor
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_rename(mock_resolve, db_session_mock):
    monitor = _mock_monitor(column_name="Old name", custom_query="SELECT 1")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms():
        out = update_metric_monitor(monitor_id=str(monitor.id), metric_name="New name")

    assert monitor.column_name == "New name"
    assert monitor.custom_query == "SELECT 1"  # unchanged
    assert monitor.lock_refresh is True
    monitor.save.assert_called_once()

    assert "Metric Monitor updated" in out
    assert f"`{monitor.id}`" in out
    # Diff table — Field column is code-wrapped via the shared render_diff_table helper
    assert "| Field | Before | After |" in out
    assert "`Metric name`" in out
    assert "Old name" in out
    assert "New name" in out
    # No leakage of internal attribute names
    assert "column_name" not in out
    assert "custom_query" not in out


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_change_expression(mock_resolve, db_session_mock):
    monitor = _mock_monitor(custom_query="SELECT 1")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms():
        out = update_metric_monitor(
            monitor_id=str(monitor.id),
            metric_expression="SELECT SUM(amount) FROM orders",
        )

    assert monitor.custom_query == "SELECT SUM(amount) FROM orders"
    assert "`Metric expression`" in out
    assert "SELECT SUM(amount) FROM orders" in out


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_both_fields(mock_resolve, db_session_mock):
    monitor = _mock_monitor(column_name="Old", custom_query="A")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms():
        out = update_metric_monitor(
            monitor_id=str(monitor.id),
            metric_name="New",
            metric_expression="B",
        )

    assert monitor.column_name == "New"
    assert monitor.custom_query == "B"
    assert "`Metric name`" in out
    assert "`Metric expression`" in out


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_rejects_non_metric(mock_resolve, db_session_mock):
    """Non-Metric monitor must be rejected by the test_type filter — exercise
    the actual code path with a real Freshness monitor, not a None-resolver mock."""
    freshness = _mock_monitor(test_type=MonitorType.FRESHNESS.value)
    mock_resolve.return_value = freshness

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_metric_monitor(monitor_id=str(freshness.id), metric_name="X")

    assert "This tool only updates Metric monitors" in str(exc.value)
    assert "Freshness/Volume/Schema" in str(exc.value)
    freshness.save.assert_not_called()


def test_update_metric_monitor_requires_a_field(db_session_mock):
    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_metric_monitor(monitor_id=str(uuid4()))

    assert "At least one of `metric_name`, `metric_expression`" in str(exc.value)


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_rejects_empty_fields(mock_resolve, db_session_mock):
    """Empty/whitespace-only field values are rejected before any save —
    catches partial-save regressions where one valid field would still apply."""
    monitor = _mock_monitor(column_name="Original", custom_query="SELECT 1")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError):
        update_metric_monitor(
            monitor_id=str(monitor.id),
            metric_name="Valid",
            metric_expression="   ",
        )
    # No partial save: column_name should NOT have been mutated to "Valid"
    assert monitor.column_name == "Original"
    monitor.save.assert_not_called()


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_no_op_when_same_values(mock_resolve, db_session_mock):
    monitor = _mock_monitor(column_name="Same", custom_query="SELECT 1")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms():
        out = update_metric_monitor(
            monitor_id=str(monitor.id),
            metric_name="Same",
            metric_expression="SELECT 1",
        )

    assert "No fields changed" in out
    monitor.save.assert_not_called()


@patch(f"{MODULE}.resolve_monitor")
def test_update_metric_monitor_not_found(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Monitor", "abc")

    from testgen.mcp.tools.monitor_metrics import update_metric_monitor

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible):
        update_metric_monitor(monitor_id="abc", metric_name="X")


# ---------------------------------------------------------------------------
# delete_metric_monitor
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.resolve_monitor")
def test_delete_metric_monitor_happy_path(mock_resolve, db_session_mock):
    monitor = _mock_monitor(table_name="orders", column_name="Daily revenue")
    mock_resolve.return_value = monitor

    from testgen.mcp.tools.monitor_metrics import delete_metric_monitor

    with _patch_perms():
        out = delete_metric_monitor(monitor_id=str(monitor.id))

    monitor.delete.assert_called_once()
    assert "Metric Monitor deleted" in out
    assert f"`{monitor.id}`" in out
    assert "orders" in out
    assert "Daily revenue" in out


@patch(f"{MODULE}.resolve_monitor")
def test_delete_metric_monitor_rejects_non_metric(mock_resolve, db_session_mock):
    """Non-Metric monitor must be rejected — exercise the actual filter."""
    schema_monitor = _mock_monitor(test_type=MonitorType.SCHEMA.value)
    mock_resolve.return_value = schema_monitor

    from testgen.mcp.tools.monitor_metrics import delete_metric_monitor

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        delete_metric_monitor(monitor_id=str(schema_monitor.id))

    assert "This tool only deletes Metric monitors" in str(exc.value)
    assert "disable_monitors" in str(exc.value)
    schema_monitor.delete.assert_not_called()


@patch(f"{MODULE}.resolve_monitor")
def test_delete_metric_monitor_not_found(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Monitor", "abc")

    from testgen.mcp.tools.monitor_metrics import delete_metric_monitor

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible):
        delete_metric_monitor(monitor_id="abc")


# ---------------------------------------------------------------------------
# validate_metric_expression
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.get_pii_columns", return_value=set())
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.validate_custom_query")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_happy_path(
    mock_resolve, mock_conn_cls, mock_validate, mock_in_catalog, mock_flavor, mock_pii,
    db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_conn_cls.get.return_value = _mock_connection(connection_name="warehouse")
    mock_flavor.return_value.get_table_ref.return_value = '"public"."orders"'

    preview_row = {"metric_value": 12345}
    mock_validate.return_value = CustomQueryResult(row_count=1, preview_rows=[preview_row])

    # role_d holds view_pii — see TEST_PERM_MATRIX
    perms = patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships={"demo": "role_d"}, permission="edit", username="test_user",
        ),
    )

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with perms:
        out = validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="SUM(amount)",
        )

    mock_validate.assert_called_once()
    kwargs = mock_validate.call_args.kwargs
    assert kwargs["schema"] == "public"
    # Expression wrapped as monitor evaluation does — SELECT ({expr}) AS metric_value FROM {table_ref}
    assert kwargs["custom_sql"] == 'SELECT (SUM(amount)) AS metric_value FROM "public"."orders"'
    assert kwargs["preview_limit"] == 1
    # view_pii → get_pii_columns is NOT queried
    mock_pii.assert_not_called()

    assert "SQL ran successfully" in out
    assert "warehouse" in out
    assert "| metric_value |" in out
    assert "12345" in out
    assert "PII redacted" not in out


@patch(f"{MODULE}.get_pii_columns")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.validate_custom_query")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_redacts_pii_columns_only(
    mock_resolve, mock_conn_cls, mock_validate, mock_in_catalog, mock_flavor, mock_pii,
    db_session_mock,
):
    """Caller lacking view_pii: only columns flagged as PII in data_column_chars are
    redacted; non-PII columns stay visible."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_conn_cls.get.return_value = _mock_connection()
    mock_flavor.return_value.get_table_ref.return_value = '"public"."orders"'
    # customer_id is PII in the catalog; amount is not
    mock_pii.return_value = {"customer_id"}

    preview_row = {"customer_id": 42, "amount": 199.99}
    mock_validate.return_value = CustomQueryResult(row_count=1, preview_rows=[preview_row])

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms():
        out = validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="customer_id, amount",
        )

    assert "| customer_id | amount |" in out
    assert "[PII redacted]" in out
    assert "42" not in out         # customer_id value hidden
    assert "199.99" in out         # amount value shown (not PII)
    assert "PII columns redacted" in out


@patch(f"{MODULE}.get_pii_columns")
@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.validate_custom_query")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_no_pii_columns_no_footer(
    mock_resolve, mock_conn_cls, mock_validate, mock_in_catalog, mock_flavor, mock_pii,
    db_session_mock,
):
    """When the table has no PII columns, values stay visible and no redaction footer appears
    (even though the caller lacks view_pii)."""
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_conn_cls.get.return_value = _mock_connection()
    mock_flavor.return_value.get_table_ref.return_value = '"public"."orders"'
    mock_pii.return_value = set()

    mock_validate.return_value = CustomQueryResult(
        row_count=1, preview_rows=[{"metric_value": 42}],
    )

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms():
        out = validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="SUM(amount)",
        )

    assert "42" in out
    assert "PII" not in out


@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.validate_custom_query")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_invalid_sql(
    mock_resolve, mock_conn_cls, mock_validate, mock_in_catalog, mock_flavor, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_conn_cls.get.return_value = _mock_connection(connection_name="warehouse")
    mock_flavor.return_value.get_table_ref.return_value = '"public"."orders"'
    mock_validate.side_effect = RuntimeError("syntax error at or near 'FROMM'")

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms():
        out = validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="* FROMM orders",
        )

    assert "SQL did not execute" in out
    assert "warehouse" in out
    # Driver error message verbatim — needed so the LLM can iterate
    assert "syntax error at or near 'FROMM'" in out


@patch(f"{MODULE}.get_flavor_service")
@patch(f"{MODULE}._table_in_catalog", return_value=True)
@patch(f"{MODULE}.validate_custom_query")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_no_rows(
    mock_resolve, mock_conn_cls, mock_validate, mock_in_catalog, mock_flavor, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())
    mock_conn_cls.get.return_value = _mock_connection()
    mock_flavor.return_value.get_table_ref.return_value = '"public"."orders"'
    mock_validate.return_value = CustomQueryResult(row_count=0, preview_rows=[])

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms():
        out = validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="SUM(amount) WHERE 1=0",
        )

    assert "ran, but returned no rows" in out


@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_not_monitored(mock_resolve, db_session_mock):
    tg = _mock_table_group(monitor_test_suite_id=None)
    mock_resolve.return_value = (tg, None)

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="orders",
            metric_expression="SUM(amount)",
        )

    assert "Monitoring is not enabled" in str(exc.value)


@patch(f"{MODULE}._table_in_catalog", return_value=False)
@patch(f"{MODULE}.resolve_monitored_table_group")
def test_validate_metric_expression_table_not_in_catalog(
    mock_resolve, mock_in_catalog, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = (tg, _mock_monitor_suite())

    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        validate_metric_expression(
            table_group_id=str(tg.id),
            table_name="missing_table",
            metric_expression="SUM(amount)",
        )
    assert "missing_table" in str(exc.value) and "catalog" in str(exc.value).lower()


def test_validate_metric_expression_rejects_empty(db_session_mock):
    from testgen.mcp.tools.monitor_metrics import validate_metric_expression

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        validate_metric_expression(
            table_group_id=str(uuid4()),
            table_name="orders",
            metric_expression="   ",
        )
    assert "metric_expression" in str(exc.value)


# ---------------------------------------------------------------------------
# resolve_monitor helper (covers the new common.py addition)
# ---------------------------------------------------------------------------


def test_resolve_monitor_invalid_uuid_rejected(db_session_mock):
    from testgen.mcp.tools.common import resolve_monitor

    with _patch_perms(), pytest.raises(MCPUserError):
        resolve_monitor("not-a-uuid")
