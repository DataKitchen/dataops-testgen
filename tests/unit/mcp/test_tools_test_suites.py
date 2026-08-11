"""Tests for the MCP test-suite write tools — create / update for regular (non-monitor) suites."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.test_suites"


def _patch_perms(allowed=("demo",), memberships=None, permission="edit", role="role_a"):
    memberships = memberships or dict.fromkeys(allowed, role)
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(memberships=memberships, permission=permission, username="test_user"),
    )


def _mock_table_group(**overrides) -> MagicMock:
    tg_id = overrides.get("id", uuid4())
    tg = MagicMock()
    tg.id = tg_id
    tg.project_code = overrides.get("project_code", "demo")
    tg.connection_id = overrides.get("connection_id", 42)
    tg.table_groups_name = overrides.get("table_groups_name", "Sample TG")
    return tg


def _mock_test_suite(**overrides) -> MagicMock:
    suite = MagicMock()
    suite.id = overrides.get("id", uuid4())
    suite.project_code = overrides.get("project_code", "demo")
    suite.test_suite = overrides.get("test_suite", "Sample Suite")
    suite.connection_id = overrides.get("connection_id", 42)
    suite.table_groups_id = overrides.get("table_groups_id", uuid4())
    suite.test_suite_description = overrides.get("test_suite_description", None)
    suite.severity = overrides.get("severity", None)
    suite.export_to_observability = overrides.get("export_to_observability", False)
    suite.dq_score_exclude = overrides.get("dq_score_exclude", False)
    suite.component_key = overrides.get("component_key", None)
    suite.component_type = overrides.get("component_type", None)
    suite.component_name = overrides.get("component_name", None)
    suite.is_monitor = overrides.get("is_monitor", False)
    return suite


# ---------------------------------------------------------------------------
# create_test_suite
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_happy_path(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(
        test_suite="Sales Tests",
        project_code="demo",
        table_groups_id=tg.id,
    )
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(table_group_id=str(tg.id), test_suite_name="Sales Tests")

    # The tool does not call instance.save(); it relies on session.add + flush.
    # This checks that wiring only — the smoke test exercises actual DB persistence.
    mock_suite_cls.assert_called_once()
    instance.save.assert_not_called()
    db_session_mock.add.assert_called_once_with(instance)
    db_session_mock.flush.assert_called_once()
    assert "Test Suite `Sales Tests` created" in out
    assert "**Project:** `demo`" in out
    assert "Sample TG" in out


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_default_export_matches_ui(mock_resolve, mock_suite_cls, db_session_mock):
    """S1 review feedback: export_to_observability defaults to False (matches the UI dialog),
    not the model's legacy Y default."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="Anything")

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["export_to_observability"] is False
    # S3 review feedback: component_type defaults to "dataset" on create
    assert kwargs["component_type"] == "dataset"
    assert kwargs["dq_score_exclude"] is False


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_passes_all_new_args_to_model(mock_resolve, mock_suite_cls, db_session_mock):
    """S9: create_test_suite accepts the full UI-editable surface (export, dq_score_exclude, component_*)
    so the LLM can configure the suite in one round-trip."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="Full",
            description="d",
            severity_default="Warning",
            export_to_observability=True,
            component_key="ck",
            component_type="dataset",
            component_name="cn",
            dq_score_exclude=True,
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite_description"] == "d"
    assert kwargs["severity"] == "Warning"
    assert kwargs["export_to_observability"] is True
    assert kwargs["component_key"] == "ck"
    assert kwargs["component_type"] == "dataset"
    assert kwargs["component_name"] == "cn"
    assert kwargs["dq_score_exclude"] is True


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_normalizes_empty_text_args_to_none(mock_resolve, mock_suite_cls, db_session_mock):
    """S4: NullIfEmptyString writes "" -> NULL; pre-normalize on the way in so the model
    receives the canonical value."""
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    mock_suite_cls.return_value = _mock_test_suite()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="x",
            description="",
            component_key="",
            component_type="",
            component_name="",
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite_description"] is None
    assert kwargs["component_key"] is None
    assert kwargs["component_type"] is None
    assert kwargs["component_name"] is None


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_with_severity(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="Sev Suite", severity="Fail")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        out = create_test_suite(
            table_group_id=str(tg.id),
            test_suite_name="Sev Suite",
            severity_default="Fail",
        )

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["severity"] == "Fail"
    assert kwargs["is_monitor"] is False
    assert "Fail" in out


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_invalid_severity(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(
            table_group_id=str(uuid4()),
            test_suite_name="Anything",
            severity_default="Critical",
        )
    msg = str(exc.value)
    # S6: error is field-scoped and enumerates valid values without double-labeling.
    assert "severity_default" in msg
    assert "Fail" in msg and "Warning" in msg
    assert "Critical" in msg
    assert "Invalid severity" not in msg  # the double-labeled phrasing is gone


def test_create_test_suite_empty_name_rejected(db_session_mock):
    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="   ")
    assert "test_suite_name: must not be empty" in str(exc.value)


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_strips_whitespace(mock_resolve, mock_suite_cls, db_session_mock):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="Sales Tests")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms():
        create_test_suite(table_group_id=str(tg.id), test_suite_name="  Sales Tests  ")

    _, kwargs = mock_suite_cls.call_args
    assert kwargs["test_suite"] == "Sales Tests"


@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_table_group_not_accessible(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Table group", str(uuid4()))

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="Anything")


def test_create_test_suite_requires_edit(db_session_mock):
    """role_c lacks edit (per conftest matrix)."""
    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        create_test_suite(table_group_id=str(uuid4()), test_suite_name="Anything")


@patch(f"{MODULE}.TestSuite")
@patch(f"{MODULE}.resolve_table_group")
def test_create_test_suite_allows_role_with_edit_but_not_administer(
    mock_resolve, mock_suite_cls, db_session_mock,
):
    """role_d has edit but NOT administer (per conftest matrix) — must still be allowed.

    Mirrors the production data_quality role: write access to suites without
    project-level administer rights.
    """
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    instance = _mock_test_suite(test_suite="DQ Suite")
    mock_suite_cls.return_value = instance

    from testgen.mcp.tools.test_suites import create_test_suite

    with _patch_perms(memberships={"demo": "role_d"}):
        out = create_test_suite(table_group_id=str(tg.id), test_suite_name="DQ Suite")

    mock_suite_cls.assert_called_once()
    instance.save.assert_not_called()
    assert "Test Suite `DQ Suite` created" in out


# ---------------------------------------------------------------------------
# update_test_suite
# ---------------------------------------------------------------------------


def test_update_test_suite_no_fields_supplied(db_session_mock):
    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(test_suite_id=str(uuid4()))
    assert str(exc.value) == "No fields supplied to update."


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_renames(mock_resolve, db_session_mock):
    suite = _mock_test_suite(test_suite="Original Name")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(test_suite_id=str(suite.id), test_suite_name="New Name")

    suite.save.assert_called_once()
    assert "Test Suite `New Name` updated" in out
    assert "| Field | Before | After |" in out
    assert "Original Name" in out
    assert "New Name" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_multi_field_diff(mock_resolve, db_session_mock):
    suite = _mock_test_suite(
        test_suite="Suite",
        severity=None,
        export_to_observability=True,
        dq_score_exclude=False,
    )
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            severity_default="Warning",
            export_to_observability=False,
            dq_score_exclude=True,
        )

    suite.save.assert_called_once()
    assert "Default severity" in out
    assert "Warning" in out
    # S13/S15: column header capitalises "Observability" (product name).
    assert "Export to Observability" in out
    assert "Exclude from quality scoring" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_no_op(mock_resolve, db_session_mock):
    suite = _mock_test_suite(test_suite_description="same", severity="Fail")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            description="same",
            severity_default="Fail",
        )

    suite.save.assert_not_called()
    assert "No fields changed" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_text_arg_on_null_field_is_noop(mock_resolve, db_session_mock):
    """S4 phantom-diff regression: an "" arg on a currently-NULL NullIfEmptyString column must
    NOT show up as a "changed" diff row (the DB would read back identical to before)."""
    suite = _mock_test_suite(
        test_suite_description=None,
        component_key=None,
        component_type=None,
        component_name=None,
    )
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(
            test_suite_id=str(suite.id),
            description="",
            component_key="",
            component_type="",
            component_name="",
        )

    suite.save.assert_not_called()
    assert "No fields changed" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_text_arg_clears_populated_field(mock_resolve, db_session_mock):
    """S4 complement: "" on a currently-populated field clears it to NULL and shows in the diff."""
    suite = _mock_test_suite(component_key="existing-key")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms():
        out = update_test_suite(test_suite_id=str(suite.id), component_key="")

    suite.save.assert_called_once()
    assert "Component key" in out
    assert "existing-key" in out


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_empty_name_rejected(mock_resolve, db_session_mock):
    suite = _mock_test_suite()
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(test_suite_id=str(suite.id), test_suite_name="   ")
    assert "test_suite_name: must not be empty" in str(exc.value)
    suite.save.assert_not_called()


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_invalid_severity_collected(mock_resolve, db_session_mock):
    """Field-level validation collected, then raised together — name + severity errors in one message."""
    suite = _mock_test_suite()
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_test_suite(
            test_suite_id=str(suite.id),
            test_suite_name="",
            severity_default="Critical",
        )
    msg = str(exc.value)
    assert "Update rejected" in msg
    assert "test_suite_name: must not be empty" in msg
    # S6: field-scoped phrasing, no double-labeled "Invalid severity"
    assert "severity_default" in msg
    assert "Fail" in msg and "Warning" in msg
    assert "Invalid severity" not in msg
    suite.save.assert_not_called()


def test_update_test_suite_monitor_suite_unified_wording(db_session_mock):
    """Per TG-1053 review feedback: exercising an is_monitor=True suite must surface
    the unified missing-or-inaccessible error, not a distinct rejection. The filter
    side-effect is in ``resolve_test_suite``; this test exercises it end-to-end with
    the real TestSuite.get patched to behave as it would in DB (filter applied → None)."""
    with patch("testgen.mcp.tools.common.TestSuite") as mock_ts:
        mock_ts.get.return_value = None  # filter excluded the monitor suite
        from testgen.mcp.tools.test_suites import update_test_suite

        with _patch_perms(), pytest.raises(MCPResourceNotAccessible) as exc:
            update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")
    assert "Test suite" in str(exc.value)
    assert "not found or not accessible" in str(exc.value)


def test_update_test_suite_not_accessible(db_session_mock):
    """Suite in a project the user can't access → unified wording."""
    with patch("testgen.mcp.tools.common.TestSuite") as mock_ts:
        mock_ts.get.return_value = None
        from testgen.mcp.tools.test_suites import update_test_suite

        with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
            update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")


def test_update_test_suite_requires_edit(db_session_mock):
    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        update_test_suite(test_suite_id=str(uuid4()), test_suite_name="Anything")


@patch(f"{MODULE}.resolve_test_suite")
def test_update_test_suite_allows_role_with_edit_but_not_administer(mock_resolve, db_session_mock):
    """role_d has edit but NOT administer — must be allowed (mirrors production data_quality)."""
    suite = _mock_test_suite(test_suite="DQ Suite")
    mock_resolve.return_value = suite

    from testgen.mcp.tools.test_suites import update_test_suite

    with _patch_perms(memberships={"demo": "role_d"}):
        out = update_test_suite(test_suite_id=str(suite.id), description="updated by data_quality")

    suite.save.assert_called_once()
    assert "Test Suite `DQ Suite` updated" in out
