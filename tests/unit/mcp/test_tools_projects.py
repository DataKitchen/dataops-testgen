"""Tests for the MCP project write tools — currently just update_project.

Project create/delete live in the enterprise plugin (gated on ``global_admin``);
this module owns the per-project ``administer`` slice that ships in core.
"""

from unittest.mock import MagicMock, patch

import pytest

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.projects"


def _patch_perms(allowed=("demo",), memberships=None, permission="administer", role="role_a"):
    memberships = memberships or dict.fromkeys(allowed, role)
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(memberships=memberships, permission=permission, username="test_user"),
    )


def _mock_project(**overrides) -> MagicMock:
    project = MagicMock()
    project.project_code = overrides.get("project_code", "demo")
    project.project_name = overrides.get("project_name", "Demo Project")
    project.use_dq_score_weights = overrides.get("use_dq_score_weights", True)
    project.observability_api_url = overrides.get("observability_api_url", None)
    project.observability_api_key = overrides.get("observability_api_key", None)
    project.data_retention_enabled = overrides.get("data_retention_enabled", True)
    project.data_retention_days = overrides.get("data_retention_days", 180)
    return project


def _mock_schedule(cron_expr: str = "0 1 * * *", cron_tz: str = "UTC") -> MagicMock:
    schedule = MagicMock()
    schedule.cron_expr = cron_expr
    schedule.cron_tz = cron_tz
    return schedule


# ---------------------------------------------------------------------------
# update_project — guards
# ---------------------------------------------------------------------------


def test_update_project_no_fields_supplied(db_session_mock):
    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_project(project_code="demo")
    assert str(exc.value) == "No fields supplied to update."


@patch(f"{MODULE}.resolve_project")
def test_update_project_inaccessible_uses_unified_wording(mock_resolve, db_session_mock):
    """When resolve_project raises (out-of-scope or missing), the tool re-raises with the
    unified wording. resolve_project's own behaviour is covered in test_tools_common.py."""
    mock_resolve.side_effect = MCPResourceNotAccessible("Project", "secret")

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(allowed=("demo",)), pytest.raises(MCPResourceNotAccessible) as exc:
        update_project(project_code="secret", project_name="Anything")
    assert "Project `secret` not found or not accessible" in str(exc.value)


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_not_found_uses_unified_wording(mock_resolve, mock_schedule_cls, db_session_mock):
    """resolve_project collapses 'no row' into the unified error."""
    mock_resolve.side_effect = MCPResourceNotAccessible("Project", "demo")
    mock_schedule_cls.get.return_value = None

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPResourceNotAccessible) as exc:
        update_project(project_code="demo", project_name="Anything")
    assert "Project `demo` not found or not accessible" in str(exc.value)


def test_update_project_requires_administer(db_session_mock):
    """role_d has edit but NOT administer (per conftest matrix)."""
    from testgen.mcp.tools.projects import update_project

    with _patch_perms(memberships={"demo": "role_d"}), pytest.raises(MCPPermissionDenied):
        update_project(project_code="demo", project_name="anything")


# ---------------------------------------------------------------------------
# update_project — rename
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_renames(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(project_name="Demo Project")
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        out = update_project(project_code="demo", project_name="Demo Renamed")

    project.save.assert_called_once()
    assert "Project `demo` updated" in out
    assert "| Field | Before | After |" in out
    assert "Demo Project" in out
    assert "Demo Renamed" in out


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_no_op_when_value_unchanged(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(project_name="Demo Project")
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        out = update_project(project_code="demo", project_name="Demo Project")

    project.save.assert_not_called()
    assert "No fields changed" in out


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_empty_name_rejected(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(project_name="Demo")
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_project(project_code="demo", project_name="   ")
    assert "project_name: must not be empty" in str(exc.value)
    project.save.assert_not_called()


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_strips_whitespace(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(project_name="Demo Project")
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", project_name="  Demo Renamed  ")

    assert project.project_name == "Demo Renamed"


# ---------------------------------------------------------------------------
# update_project — weights toggle (recalc-scores side effect)
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.JobExecution")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_weights_toggle_submits_recalc(
    mock_resolve, mock_schedule_cls, mock_job_exec_cls, db_session_mock,
):
    project = _mock_project(use_dq_score_weights=True)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", use_dq_score_weights=False)

    project.save.assert_called_once()
    # Background score recalc is submitted, matching the UI behaviour.
    mock_job_exec_cls.submit.assert_called_once()
    _, kwargs = mock_job_exec_cls.submit.call_args
    assert kwargs["project_code"] == "demo"


@patch(f"{MODULE}.JobExecution")
@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_weights_unchanged_no_recalc(
    mock_resolve, mock_schedule_cls, mock_job_exec_cls, db_session_mock,
):
    project = _mock_project(use_dq_score_weights=True)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        # Supplied but unchanged — no side effect.
        update_project(project_code="demo", use_dq_score_weights=True)

    mock_job_exec_cls.submit.assert_not_called()


# ---------------------------------------------------------------------------
# update_project — observability fields
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_observability_url_diff_visible(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(observability_api_url=None)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        out = update_project(project_code="demo", observability_api_url="https://obs.example/api")

    project.save.assert_called_once()
    assert "DataOps Observability API URL" in out
    assert "https://obs.example/api" in out


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_observability_key_redacted_in_diff(mock_resolve, mock_schedule_cls, db_session_mock):
    """Per mcp-patterns 'Secrets in inputs': the key is consumed but never echoed back."""
    project = _mock_project(observability_api_key=None)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        out = update_project(project_code="demo", observability_api_key="super-secret-key-value")

    project.save.assert_called_once()
    assert "DataOps Observability API key" in out
    assert "[secret]" in out
    assert "super-secret-key-value" not in out


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_observability_url_empty_string_clears(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    """Empty string clears the field (NullIfEmptyString column)."""
    project = _mock_project(observability_api_url="https://existing.example")
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", observability_api_url="")

    # After normalization "" → None on the way in.
    assert project.observability_api_url is None


# ---------------------------------------------------------------------------
# update_project — data retention
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_disable_retention_deletes_schedule(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    project = _mock_project(data_retention_enabled=True, data_retention_days=180)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", data_retention_enabled=False)

    project.save.assert_called_once()
    mock_schedule_cls.delete_for_retention.assert_called_once_with("demo")
    mock_schedule_cls.upsert_for_retention.assert_not_called()
    assert project.data_retention_enabled is False
    # Days cleared on disable (matches UI behaviour).
    assert project.data_retention_days is None


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_change_retention_days_upserts_schedule(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    project = _mock_project(data_retention_enabled=True, data_retention_days=180)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule(cron_expr="0 1 * * *", cron_tz="UTC")

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", data_retention_days=30)

    project.save.assert_called_once()
    mock_schedule_cls.upsert_for_retention.assert_called_once()
    _, kwargs = mock_schedule_cls.upsert_for_retention.call_args
    assert kwargs["project_code"] == "demo"
    assert kwargs["retention_days"] == 30
    # Cron is preserved from existing schedule when not supplied.
    assert kwargs["cron_expr"] == "0 1 * * *"
    assert kwargs["cron_tz"] == "UTC"


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_enable_retention_with_defaults(mock_resolve, mock_schedule_cls, db_session_mock):
    """Re-enabling retention without explicit days/cron falls back to the system defaults."""
    project = _mock_project(data_retention_enabled=False, data_retention_days=None)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = None  # no current schedule

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", data_retention_enabled=True)

    mock_schedule_cls.upsert_for_retention.assert_called_once()
    _, kwargs = mock_schedule_cls.upsert_for_retention.call_args
    assert kwargs["retention_days"] == 180  # default
    assert kwargs["cron_expr"] == "0 1 * * *"  # DEFAULT_DATA_CLEANUP_CRON
    assert kwargs["cron_tz"] == "UTC"  # DEFAULT_RETENTION_CRON_TZ


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_change_cron_only(mock_resolve, mock_schedule_cls, db_session_mock):
    project = _mock_project(data_retention_enabled=True, data_retention_days=180)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule(cron_expr="0 1 * * *", cron_tz="UTC")

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        out = update_project(project_code="demo", retention_cron_expr="0 2 * * *")

    mock_schedule_cls.upsert_for_retention.assert_called_once()
    _, kwargs = mock_schedule_cls.upsert_for_retention.call_args
    assert kwargs["cron_expr"] == "0 2 * * *"
    # Days carried over from the project's current value.
    assert kwargs["retention_days"] == 180
    assert "Retention cron expression" in out


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_retention_days_rejected_when_disabled(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    """Setting days while disabling retention is inconsistent — reject loudly instead of silently dropping."""
    project = _mock_project(data_retention_enabled=True)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_project(
            project_code="demo",
            data_retention_enabled=False,
            data_retention_days=90,
        )
    msg = str(exc.value)
    assert "data_retention_days: cannot be set when data_retention_enabled is False" in msg
    project.save.assert_not_called()
    mock_schedule_cls.upsert_for_retention.assert_not_called()
    mock_schedule_cls.delete_for_retention.assert_not_called()


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_cron_rejected_when_retention_currently_disabled(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    project = _mock_project(data_retention_enabled=False, data_retention_days=None)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = None

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_project(project_code="demo", retention_cron_expr="0 2 * * *")
    assert "retention_cron_expr: cannot be set when data_retention_enabled is False" in str(exc.value)


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_retention_days_must_be_positive(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    project = _mock_project(data_retention_enabled=True)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_project(project_code="demo", data_retention_days=0)
    assert "data_retention_days: must be a positive integer" in str(exc.value)


@patch(f"{MODULE}.JobSchedule")
@patch(f"{MODULE}.resolve_project")
def test_update_project_name_only_does_not_touch_schedule(
    mock_resolve, mock_schedule_cls, db_session_mock,
):
    """Renaming a project must NOT incidentally upsert / delete the retention schedule."""
    project = _mock_project(project_name="Old", data_retention_enabled=True)
    mock_resolve.return_value = project
    mock_schedule_cls.get.return_value = _mock_schedule()

    from testgen.mcp.tools.projects import update_project

    with _patch_perms():
        update_project(project_code="demo", project_name="New")

    project.save.assert_called_once()
    mock_schedule_cls.upsert_for_retention.assert_not_called()
    mock_schedule_cls.delete_for_retention.assert_not_called()
