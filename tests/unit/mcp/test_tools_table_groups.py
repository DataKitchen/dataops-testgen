"""Tests for the MCP table-group CRUD tools — create / update / preview."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.table_groups"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _patch_perms(allowed=("demo",), memberships=None, permission="edit", role="role_a"):
    # role_a has edit but NOT view_pii; role_d has edit + view_pii (see conftest matrix).
    memberships = memberships or dict.fromkeys(allowed, role)
    return patch(
        "testgen.mcp.permissions._compute_project_permissions",
        return_value=ProjectPermissions(
            memberships=memberships, permission=permission, username="test_user",
        ),
    )


def _mock_connection(**overrides) -> MagicMock:
    conn = MagicMock()
    conn.connection_id = overrides.get("connection_id", 42)
    conn.project_code = overrides.get("project_code", "demo")
    conn.connection_name = overrides.get("connection_name", "Local PG")
    conn.sql_flavor = overrides.get("sql_flavor", "postgresql")
    conn.sql_flavor_code = overrides.get("sql_flavor_code", "postgresql")
    return conn


def _mock_table_group(**overrides) -> MagicMock:
    """Build a MagicMock matching the TableGroup model surface used by the tools."""
    tg_id = overrides.get("id", uuid4())
    tg = MagicMock()
    tg.id = tg_id
    tg.project_code = overrides.get("project_code", "demo")
    tg.connection_id = overrides.get("connection_id", 42)
    tg.table_groups_name = overrides.get("table_groups_name", "Sample TG")
    tg.table_group_schema = overrides.get("table_group_schema", "public")
    tg.profiling_table_set = overrides.get("profiling_table_set", None)
    tg.profiling_include_mask = overrides.get("profiling_include_mask", None)
    tg.profiling_exclude_mask = overrides.get("profiling_exclude_mask", None)
    tg.profile_id_column_mask = overrides.get("profile_id_column_mask", "%id")
    tg.profile_sk_column_mask = overrides.get("profile_sk_column_mask", "%_sk")
    tg.profile_use_sampling = overrides.get("profile_use_sampling", False)
    tg.profile_sample_percent = overrides.get("profile_sample_percent", "30")
    tg.profile_sample_min_count = overrides.get("profile_sample_min_count", 100000)
    tg.profiling_delay_days = overrides.get("profiling_delay_days", "0")
    tg.profile_flag_cdes = overrides.get("profile_flag_cdes", True)
    tg.profile_flag_pii = overrides.get("profile_flag_pii", True)
    tg.profile_exclude_xde = overrides.get("profile_exclude_xde", True)
    tg.include_in_dashboard = overrides.get("include_in_dashboard", True)
    tg.description = overrides.get("description", None)
    tg.data_source = overrides.get("data_source", None)
    tg.source_system = overrides.get("source_system", None)
    tg.source_process = overrides.get("source_process", None)
    tg.data_location = overrides.get("data_location", None)
    tg.business_domain = overrides.get("business_domain", None)
    tg.stakeholder_group = overrides.get("stakeholder_group", None)
    tg.transform_level = overrides.get("transform_level", None)
    tg.data_product = overrides.get("data_product", None)
    tg.data_classification = overrides.get("data_classification", None)
    return tg


def _integrity_error(message: str) -> IntegrityError:
    orig = Exception(message)
    return IntegrityError("stmt", {}, orig)


# ---------------------------------------------------------------------------
# create_table_group
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_happy_path(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(table_groups_name="Sample TG")
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )

    instance.save.assert_called_once()
    assert "Table Group `Sample TG` created" in out
    assert "**Project:** `demo`" in out
    assert "**Schema:** `public`" in out


def test_model_defaults_normalize_ynstring_columns_to_python_bool():
    """``YNString`` columns store ``"Y"``/``"N"`` but expose ``bool``.

    The defaults dict mirrors ``Column(default=...)`` raw values, so without
    normalization a ``"N"`` default would render as truthy (non-empty string)
    in the create-tool output until the row is reloaded from the DB.
    """
    from testgen.mcp.tools.table_groups import _MODEL_DEFAULTS

    assert _MODEL_DEFAULTS["profile_use_sampling"] is False
    assert _MODEL_DEFAULTS["profile_do_pair_rules"] is False


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_applies_model_defaults_when_optional_args_omitted(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """Optional profiling fields must seed from the model's ``Column(default=...)`` values.

    SQLAlchemy column defaults only fire at flush time, but validation runs
    before flush — so the create tool must populate them in-memory or
    validation rejects every call that omits them.
    """
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group()
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )

    kwargs = mock_tg_cls.call_args.kwargs
    assert kwargs["profile_sample_percent"] == "30"
    assert kwargs["profile_sample_min_count"] == 100000
    assert kwargs["profiling_delay_days"] == "0"


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_with_table_set_joins_to_string(mock_resolve, mock_tg_cls, db_session_mock):
    """``table_set: list[str]`` is comma-joined into the model's ``profiling_table_set`` column."""
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(profiling_table_set="film,actor,customer")
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            table_set=["film", "actor", "customer"],
        )

    assert instance.profiling_table_set == "film,actor,customer"


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_renders_sample_settings_when_sampling_on(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """Sample % and Sample min rows only matter when sampling is on; render them then."""
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(
        profile_use_sampling=True,
        profile_sample_percent="50",
        profile_sample_min_count=5000,
    )
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            profile_use_sampling=True,
            profile_sample_percent=50,
            profile_sample_min_count=5000,
        )

    assert "Sample %" in out
    assert "50" in out
    assert "Sample min rows" in out
    assert "5000" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_skips_sample_settings_when_sampling_off(
    mock_resolve, mock_tg_cls, db_session_mock,
):
    """When sampling is off, Sample % / min rows are irrelevant — omit them."""
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(profile_use_sampling=False)
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )

    assert "Sample %" not in out
    assert "Sample min rows" not in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_with_catalog_tags_rendered(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(
        data_source="Postgres",
        business_domain="Sales",
    )
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            data_source="Postgres",
            business_domain="Sales",
        )

    assert "## Catalog" in out
    assert "Data source" in out
    assert "Postgres" in out
    assert "Business domain" in out
    assert "Sales" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_validation_error_no_save(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(table_groups_name="ab")
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_table_group(
            connection_id=42,
            table_group_name="ab",
            schema="public",
        )
    msg = str(exc.value)
    assert "Table group creation rejected" in msg
    assert "must be between 3 and 40 characters" in msg
    instance.save.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_duplicate_name_maps_to_user_error(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group()
    instance.save.side_effect = _integrity_error(
        'duplicate key value violates unique constraint "table_groups_name_unique"'
    )
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )
    assert str(exc.value) == "A Table Group with the same name already exists."


@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_connection_not_accessible(mock_resolve, db_session_mock):
    """Connection's project not in allowed_codes → MCPResourceNotAccessible from resolve_connection."""
    mock_resolve.side_effect = MCPResourceNotAccessible("Connection", "42")

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible) as exc:
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )
    assert "Connection" in str(exc.value)


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_adds_scorecard_by_default(mock_resolve, mock_tg_cls, db_session_mock):
    """Mirrors the UI checkbox default — a new table group gets a scorecard unless opted out."""
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group()
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )

    instance.save.assert_called_once_with(add_scorecard_definition=True)


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_add_scorecard_false_skips_scorecard(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group()
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            add_scorecard=False,
        )

    instance.save.assert_called_once_with(add_scorecard_definition=False)


def test_create_table_group_requires_edit(db_session_mock):
    """Role without 'edit' permission → MCPPermissionDenied."""
    from testgen.mcp.tools.table_groups import create_table_group

    # role_c lacks 'edit'
    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
        )


# ---------------------------------------------------------------------------
# create_table_group — PII flag is not gated on create
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_pii_on_allowed_without_view_pii(mock_resolve, mock_tg_cls, db_session_mock):
    """A new table group has no manually-marked PII to overwrite, so creating with the
    flag on is allowed even without view_pii — the gate applies only to editing it."""
    mock_resolve.return_value = _mock_connection()
    instance = _mock_table_group(profile_flag_pii=False)
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():  # role_a: edit, no view_pii
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            profile_flag_pii=True,
        )

    instance.save.assert_called_once()
    assert instance.profile_flag_pii is True


# ---------------------------------------------------------------------------
# update_table_group
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_no_fields_supplied(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_table_group()

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_table_group(table_group_id=str(uuid4()))
    assert str(exc.value) == "No fields supplied to update."


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_description_diff_table(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group(description=None)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), description="Pulled from postgres tutorial DB")

    tg.save.assert_called_once()
    assert "| Field | Before | After |" in out
    assert "Description" in out
    assert "Pulled from postgres tutorial DB" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_no_op(mock_resolve, mock_tg_cls, db_session_mock):
    """Supplying the current value → no-op message, no save call."""
    tg = _mock_table_group(description="existing")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), description="existing")

    tg.save.assert_not_called()
    assert "No fields changed" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_schema_locked_when_in_use(mock_resolve, mock_tg_cls, db_session_mock):
    """``is_in_use=True`` + new schema → MCPUserError, no save."""
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = True

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_table_group(table_group_id=str(tg.id), schema="staging")
    assert "Schema cannot be changed" in str(exc.value)
    assert "Delete and recreate" in str(exc.value)
    tg.save.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_schema_unlocked_when_not_in_use(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), schema="staging")

    tg.save.assert_called_once()
    assert "Schema" in out
    assert "staging" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_same_schema_on_in_use_group_is_noop(mock_resolve, mock_tg_cls, db_session_mock):
    """Re-supplying the current schema on an in-use group is a no-op, not a lock violation."""
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = True

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), schema="public")

    tg.save.assert_not_called()
    assert "No fields changed" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_validation_error_no_save(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_table_group(table_group_id=str(tg.id), table_group_name="ab")
    msg = str(exc.value)
    assert "Update rejected" in msg
    assert "must be between 3 and 40 characters" in msg
    tg.save.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_duplicate_name_maps_to_user_error(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG")
    tg.save.side_effect = _integrity_error(
        'duplicate key value violates unique constraint "table_groups_name_unique"'
    )
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_table_group(table_group_id=str(tg.id), table_group_name="Existing Name")
    assert str(exc.value) == "A Table Group with the same name already exists."


@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_not_accessible(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Table group", "abc")

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
        update_table_group(table_group_id=str(uuid4()), description="any")


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_delay_days_int_cast_to_str(mock_resolve, mock_tg_cls, db_session_mock):
    """``profiling_delay_days: int`` from the caller gets cast to ``str`` to match the model column."""
    tg = _mock_table_group(profiling_delay_days="0")
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        update_table_group(table_group_id=str(tg.id), profiling_delay_days=3)

    assert tg.profiling_delay_days == "3"


# ---------------------------------------------------------------------------
# update_table_group — PII flag gating (view_pii permission)
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_enable_pii_denied_without_view_pii(mock_resolve, mock_tg_cls, db_session_mock):
    """role_a has edit but not view_pii (real ProjectPermissions) — enabling PII is denied.

    role_a *does* hold administer, so this also proves the gate checks view_pii
    specifically, not some broader permission.
    """
    tg = _mock_table_group(profile_flag_pii=False)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(role="role_a"), pytest.raises(MCPPermissionDenied):
        update_table_group(table_group_id=str(tg.id), profile_flag_pii=True)
    tg.save.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_disable_pii_denied_without_view_pii(mock_resolve, mock_tg_cls, db_session_mock):
    """Change-detection mirrors the disabled checkbox — the value can't be touched either way."""
    tg = _mock_table_group(profile_flag_pii=True)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(role="role_a"), pytest.raises(MCPPermissionDenied):
        update_table_group(table_group_id=str(tg.id), profile_flag_pii=False)
    tg.save.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_unchanged_pii_allowed_without_view_pii(mock_resolve, mock_tg_cls, db_session_mock):
    """Re-sending the current PII value (as the disabled UI checkbox does) is not a change."""
    tg = _mock_table_group(profile_flag_pii=True, description=None)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(role="role_a"):
        out = update_table_group(
            table_group_id=str(tg.id),
            profile_flag_pii=True,
            description="Edited elsewhere",
        )

    tg.save.assert_called_once()
    assert tg.profile_flag_pii is True
    assert "Description" in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_enable_pii_allowed_with_view_pii(mock_resolve, mock_tg_cls, db_session_mock):
    """role_d holds edit + view_pii (real ProjectPermissions) — enabling PII is allowed."""
    tg = _mock_table_group(profile_flag_pii=False)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(role="role_d"):
        out = update_table_group(table_group_id=str(tg.id), profile_flag_pii=True)

    tg.save.assert_called_once()
    assert tg.profile_flag_pii is True
    assert "Flag PII" in out


# ---------------------------------------------------------------------------
# preview_table_group
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_success_renders_table(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG", table_group_schema="public")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id,
                "table_groups_name": "Sample TG",
                "table_group_schema": "public",
                "table_ct": 2,
                "column_ct": 5,
                "approx_record_ct": 150,
                "approx_data_point_ct": 350,
            },
            "tables": {
                "customer": {
                    "column_ct": 3,
                    "approx_record_ct": 100,
                    "approx_data_point_ct": 300,
                    "can_access": True,
                },
                "rental": {
                    "column_ct": 2,
                    "approx_record_ct": 50,
                    "approx_data_point_ct": 50,
                    "can_access": True,
                },
            },
            "success": True,
            "message": None,
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        out = preview_table_group(table_group_id=str(tg.id))

    assert "Preview for table group" in out
    assert "Sample TG" in out
    assert "customer" in out
    assert "rental" in out
    # verify_access defaults to False — no Read Access column
    assert "| Table | Columns | Approx Rows | Approx Data Points |" in out
    assert "Read Access" not in out
    _, kwargs = mock_preview_svc.call_args
    assert kwargs["verify_access"] is False


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_verify_access_adds_column(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG", table_group_schema="public")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id,
                "table_groups_name": "Sample TG",
                "table_group_schema": "public",
                "table_ct": 1,
                "column_ct": 3,
                "approx_record_ct": 100,
                "approx_data_point_ct": 300,
            },
            "tables": {
                "customer": {
                    "column_ct": 3,
                    "approx_record_ct": 100,
                    "approx_data_point_ct": 300,
                    "can_access": True,
                },
            },
            "success": True,
            "message": None,
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        out = preview_table_group(table_group_id=str(tg.id), verify_access=True)

    assert "| Table | Columns | Approx Rows | Approx Data Points | Read Access |" in out
    _, kwargs = mock_preview_svc.call_args
    assert kwargs["verify_access"] is True


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_partial_inaccessible_appends_footer(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG", table_group_schema="public")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id,
                "table_groups_name": "Sample TG",
                "table_group_schema": "public",
                "table_ct": 2,
                "column_ct": 5,
                "approx_record_ct": 150,
                "approx_data_point_ct": 350,
            },
            "tables": {
                "customer": {
                    "column_ct": 3, "approx_record_ct": 100,
                    "approx_data_point_ct": 300, "can_access": True,
                },
                "rental": {
                    "column_ct": 2, "approx_record_ct": 50,
                    "approx_data_point_ct": 50, "can_access": False,
                },
            },
            "success": True,
            "message": "Some tables were not accessible. Please the check the database permissions.",
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        out = preview_table_group(table_group_id=str(tg.id), verify_access=True)

    assert "Some tables were not accessible" in out


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_no_match(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG", table_group_schema="public")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id,
                "table_groups_name": "Sample TG",
                "table_group_schema": "public",
                "table_ct": 0,
                "column_ct": 0,
                "approx_record_ct": None,
                "approx_data_point_ct": None,
            },
            "tables": {},
            "success": False,
            "message": (
                "No tables found matching the criteria. Please check the Table Group configuration"
                " or the database permissions."
            ),
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        out = preview_table_group(table_group_id=str(tg.id))

    assert "returned no tables" in out
    assert "No tables found matching the criteria" in out


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_failed_returns_text_not_raises(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    """A failed preview surfaces as a text response — no exception raised."""
    tg = _mock_table_group(table_groups_name="Sample TG")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id, "table_groups_name": "Sample TG", "table_group_schema": "public",
                "table_ct": 0, "column_ct": 0, "approx_record_ct": None, "approx_data_point_ct": None,
            },
            "tables": {},
            "success": False,
            "message": "Could not connect to target DB: connection refused",
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        out = preview_table_group(table_group_id=str(tg.id))

    assert "Preview failed" in out
    assert "Could not connect" in out


@patch(f"{MODULE}.resolve_table_group")
def test_preview_not_accessible(mock_resolve, db_session_mock):
    mock_resolve.side_effect = MCPResourceNotAccessible("Table group", "abc")

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms(allowed=("other",)), pytest.raises(MCPResourceNotAccessible):
        preview_table_group(table_group_id=str(uuid4()))


def test_preview_requires_edit(db_session_mock):
    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms(memberships={"demo": "role_c"}), pytest.raises(MCPPermissionDenied):
        preview_table_group(table_group_id=str(uuid4()))


# ---------------------------------------------------------------------------
# list_table_groups
# ---------------------------------------------------------------------------


def _list_item(**overrides):
    from testgen.common.models.table_group import TableGroupListItem

    return TableGroupListItem(
        id=overrides.get("id", uuid4()),
        table_groups_name=overrides.get("table_groups_name", "core_tables"),
        table_group_schema=overrides.get("table_group_schema", "public"),
        project_code=overrides.get("project_code", "demo"),
        connection_name=overrides.get("connection_name", "warehouse_prod"),
        table_count=overrides.get("table_count", 12),
        column_count=overrides.get("column_count", 84),
        row_count=overrides.get("row_count", 100_000),
        last_profiled_date=overrides.get("last_profiled_date", None),
        last_tested_date=overrides.get("last_tested_date", None),
        profiling_score=overrides.get("profiling_score", 0.95),
        testing_score=overrides.get("testing_score", 0.97),
        quality_score=overrides.get("quality_score", 0.92),
    )


def test_list_table_groups_requires_one_arg(db_session_mock):
    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"), pytest.raises(
        MCPUserError, match="Pass either `project_code` or `connection_id`",
    ):
        list_table_groups()


def test_list_table_groups_rejects_both_args(db_session_mock):
    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"), pytest.raises(
        MCPUserError, match="Pass either `project_code` or `connection_id`",
    ):
        list_table_groups(project_code="demo", connection_id=12)


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_by_project_renders_rows(mock_tg_cls, db_session_mock):
    mock_tg_cls.list_for_project.return_value = ([_list_item()], 1)

    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"):
        out = list_table_groups(project_code="demo")

    assert "Table groups for project `demo`" in out
    assert "core_tables" in out
    assert "warehouse_prod" in out
    assert "public" in out
    assert "Quality Score" in out  # column header (#8)
    assert "Columns" in out  # column header (#10)
    assert "Rows" in out  # column header (#10)
    assert "12" in out  # table count
    # quality_score 0.92 rendered via friendly_score → "92.0" (percentage form, mirrors UI).
    assert "92.0" in out
    mock_tg_cls.list_for_project.assert_called_once_with("demo", page=1, limit=20)


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_by_connection_renders_rows(mock_tg_cls, mock_resolve, db_session_mock):
    conn = _mock_connection()
    conn.connection_id = 42
    conn.connection_name = "warehouse_prod"
    mock_resolve.return_value = conn
    mock_tg_cls.list_for_connection.return_value = ([_list_item()], 1)

    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"):
        out = list_table_groups(connection_id=42)

    assert "Table groups on connection `warehouse_prod` (`42`)" in out
    mock_tg_cls.list_for_connection.assert_called_once_with(42, page=1, limit=20)


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_empty(mock_tg_cls, db_session_mock):
    mock_tg_cls.list_for_project.return_value = ([], 0)

    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"):
        out = list_table_groups(project_code="demo")

    assert "none found" in out


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_table_groups_rejects_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"other": "role_a"}, permission="view", username="test_user",
    )

    from testgen.mcp.tools.table_groups import list_table_groups

    with pytest.raises(MCPResourceNotAccessible, match="Project `secret` not found or not accessible"):
        list_table_groups(project_code="secret")


# ---------------------------------------------------------------------------
# get_table_group
# ---------------------------------------------------------------------------


def _read_mock_table_group(**overrides):
    """Variant of _mock_table_group that also sets dq score fields used by get_table_group."""
    from testgen.utils import score

    tg = _mock_table_group(**overrides)
    testing = overrides.get("dq_score_testing", None)
    profiling = overrides.get("dq_score_profiling", None)
    tg.dq_score_testing = testing
    tg.dq_score_profiling = profiling
    # Mirror TableGroup.quality_score property — MagicMock would return a MagicMock for
    # the attribute, so wire it explicitly through the same `score` helper the property uses.
    tg.quality_score = score(profiling, testing)
    return tg


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.resolve_table_group")
def test_get_table_group_renders_all_dialog_sections(mock_resolve, mock_resolve_conn, db_session_mock):
    tg = _read_mock_table_group(
        description="Curated payments tables",
        profiling_include_mask="payments_%",
        profiling_exclude_mask="tmp_%",
        profiling_table_set="payments,refunds",
        profile_use_sampling=True,
        profile_sample_percent="50",
        data_source="DataKitchen",
        business_domain="Finance",
        dq_score_testing=0.91,
        dq_score_profiling=0.95,
    )
    mock_resolve.return_value = tg
    conn = _mock_connection(connection_name="warehouse_prod", sql_flavor_code="snowflake")
    mock_resolve_conn.return_value = conn

    from testgen.mcp.tools.table_groups import get_table_group

    with _patch_perms(permission="view"):
        out = get_table_group(str(tg.id))

    # Identity
    assert "Table group `Sample TG`" in out
    assert "warehouse_prod" in out
    assert "Snowflake" in out
    assert "`public`" in out
    assert "Curated payments tables" in out
    # Criteria — both table-name and column-name masks rendered (labels via _DIFF_LABELS)
    assert "## Criteria" in out
    assert "payments_%" in out
    assert "tmp_%" in out
    assert "payments,refunds" in out
    assert "ID column mask" in out
    assert "SK column mask" in out
    # Settings
    assert "## Settings" in out
    assert "Flag CDEs" in out  # _DIFF_LABELS["profile_flag_cdes"]
    # Sampling enabled → percent + min count rendered (labels via _DIFF_LABELS)
    assert "## Sampling parameters" in out
    assert "**Sample %:** 50" in out
    assert "Sample min rows" in out
    # Catalog tags only render when set
    assert "## Catalog tags" in out
    assert "DataKitchen" in out
    assert "Finance" in out
    # Latest activity — scores rendered via friendly_score (percentage form, mirrors UI).
    assert "## Latest activity" in out
    assert "**Profiling Score:** 95.0" in out
    assert "**Testing Score:** 91.0" in out
    # 0.95 * 0.91 = 0.8645 → friendly_score → "86.4" (Python banker's rounding of 86.45).
    assert "**Quality Score:** 86.4" in out


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.resolve_table_group")
def test_get_table_group_skips_catalog_when_no_tags(mock_resolve, mock_resolve_conn, db_session_mock):
    tg = _read_mock_table_group()  # all catalog tags None
    mock_resolve.return_value = tg
    mock_resolve_conn.return_value = _mock_connection()

    from testgen.mcp.tools.table_groups import get_table_group

    with _patch_perms(permission="view"):
        out = get_table_group(str(tg.id))

    assert "## Catalog tags" not in out


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.resolve_table_group")
def test_get_table_group_skips_sample_details_when_sampling_off(
    mock_resolve, mock_resolve_conn, db_session_mock,
):
    tg = _read_mock_table_group(profile_use_sampling=False)
    mock_resolve.return_value = tg
    mock_resolve_conn.return_value = _mock_connection()

    from testgen.mcp.tools.table_groups import get_table_group

    with _patch_perms(permission="view"):
        out = get_table_group(str(tg.id))

    # Sampling section header still present (with the toggle), but percent/min not shown
    assert "**Sampling:** No" in out  # _DIFF_LABELS["profile_use_sampling"]
    assert "**Sample %:**" not in out
    assert "Sample min rows" not in out


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_group_raises_not_found_for_inaccessible(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.table_groups import get_table_group

    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        get_table_group(str(uuid4()))
