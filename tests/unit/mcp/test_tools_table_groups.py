"""Tests for the MCP table-group CRUD tools — create / update / preview."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from testgen.common.database.table_group_service import SchemaMove, SchemaMoveRefused
from testgen.mcp.exceptions import MCPPermissionDenied, MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

pytestmark = pytest.mark.unit

MODULE = "testgen.mcp.tools.table_groups"
SERVICE_MODULE = "testgen.common.database.table_group_service"


@pytest.fixture(autouse=True)
def catalog_write():
    """Stand in for the catalog write, which would otherwise probe the target."""
    with (
        patch(f"{MODULE}.write_table_group_catalog", return_value=None) as mock_write,
        patch(f"{SERVICE_MODULE}.write_table_group_catalog", new=mock_write),
    ):
        yield mock_write


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
    tg.file_declarations = overrides.get("file_declarations", None)
    tg.profiling_table_set = overrides.get("profiling_table_set", None)
    tg.profiling_include_mask = overrides.get("profiling_include_mask", None)
    tg.profiling_exclude_mask = overrides.get("profiling_exclude_mask", None)
    tg.profile_id_column_mask = overrides.get("profile_id_column_mask", "%id")
    tg.profile_sk_column_mask = overrides.get("profile_sk_column_mask", "%_sk")
    tg.profile_use_sampling = overrides.get("profile_use_sampling", False)
    tg.profile_sample_percent = overrides.get("profile_sample_percent", 30)
    tg.profile_sample_min_count = overrides.get("profile_sample_min_count", 100000)
    tg.profiling_delay_days = overrides.get("profiling_delay_days", 0)
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
    from testgen.common.models.table_group import _MODEL_DEFAULTS

    assert _MODEL_DEFAULTS["profile_use_sampling"] is False


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
    assert kwargs["profile_sample_percent"] == 30
    assert kwargs["profile_sample_min_count"] == 100000
    assert kwargs["profiling_delay_days"] == 0
    assert kwargs["profiling_include_mask"] == "%"
    assert kwargs["profiling_exclude_mask"] == "tmp%"


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
        profile_sample_percent=50,
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
    db_session_mock.rollback.assert_called_once()


@patch(f"{MODULE}.move_table_group_schema")
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_moves_the_schema_through_the_guarded_path(
    mock_resolve, mock_tg_cls, mock_move, db_session_mock,
):
    """The move probes the target and repoints stored definitions, so a plain assignment
    would skip both."""
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg
    def apply(table_group, schema, **_kwargs):
        # The real move sets this; the tool saves only what its diff can see.
        table_group.table_group_schema = schema
        return SchemaMove(
            previous_schema="public", schema=schema, missing_tables=[], definitions_repointed=3,
        )

    mock_move.side_effect = apply

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), schema="staging")

    assert mock_move.call_args.args[1] == "staging"
    tg.save.assert_called_once()
    assert "staging" in out


@patch(f"{MODULE}.move_table_group_schema")
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_surfaces_a_refused_move(mock_resolve, mock_tg_cls, mock_move, db_session_mock):
    """A schema carrying none of the table group's tables is refused, and the caller is told why."""
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg
    mock_move.side_effect = SchemaMoveRefused("schema_empty", "No tables in staging match this table group.")

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms(), pytest.raises(MCPUserError) as exc:
        update_table_group(table_group_id=str(tg.id), schema="staging")

    assert "No tables in staging" in str(exc.value)


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_same_schema_is_noop(mock_resolve, mock_tg_cls, db_session_mock):
    """Re-supplying the current schema moves nothing, so there is nothing to save."""
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), schema="public")

    tg.save.assert_not_called()
    assert "No fields changed" in out
    db_session_mock.rollback.assert_called_once()


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
def test_update_table_group_delay_days_assigned(mock_resolve, mock_tg_cls, db_session_mock):
    tg = _mock_table_group(profiling_delay_days=0)
    mock_resolve.return_value = tg
    mock_tg_cls.is_in_use.return_value = False

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        update_table_group(table_group_id=str(tg.id), profiling_delay_days=3)

    assert tg.profiling_delay_days == 3


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
            "message": "Some tables were not accessible. Check that TestGen has read access to them.",
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
        connection_id=overrides.get("connection_id", 42),
        connection_name=overrides.get("connection_name", "warehouse_prod"),
        sql_flavor_code=overrides.get("sql_flavor_code", "postgresql"),
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
        profile_sample_percent=50,
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


# ---------------------------------------------------------------------------
# Table groups on a connection whose tables are files
# ---------------------------------------------------------------------------


def _files_connection(**overrides) -> MagicMock:
    return _mock_connection(sql_flavor="duckdb", sql_flavor_code="files", **overrides)


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_stores_the_declared_tables(mock_resolve, mock_tg_cls, db_session_mock):
    mock_resolve.return_value = _files_connection()
    instance = _mock_table_group(table_groups_name="Files TG")

    # The constructor kwargs have to land on the instance: validation reads the declarations back
    # off it, so a mock that swallows them would pass whatever it was given.
    def construct(**kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_tg_cls.side_effect = construct

    from testgen.mcp.tools.table_groups import FileDeclaration, create_table_group

    with _patch_perms():
        create_table_group(
            connection_id=42,
            table_group_name="Files TG",
            file_declarations=[
                FileDeclaration(name="orders", uri="sales/orders_*.csv", format="csv", delimiter="|"),
                FileDeclaration(name="products", uri="catalog/products.json", format="json"),
            ],
        )

    declared = mock_tg_cls.call_args.kwargs["file_declarations"]
    assert declared == [
        {"name": "orders", "uri": "sales/orders_*.csv", "format": "csv", "options": {"delimiter": "|"}},
        {"name": "products", "uri": "catalog/products.json", "format": "json", "options": {}},
    ]
    assert (instance.profiling_include_mask, instance.profiling_exclude_mask) == (None, None)
    instance.save.assert_called_once()


@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_on_a_files_connection_needs_declarations(mock_resolve, db_session_mock):
    mock_resolve.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms(), pytest.raises(MCPUserError, match="file_declarations"):
        create_table_group(connection_id=42, table_group_name="Files TG")


@patch(f"{MODULE}.resolve_connection")
def test_a_files_connection_has_no_schema_to_choose(mock_resolve, db_session_mock):
    mock_resolve.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, create_table_group

    with _patch_perms(), pytest.raises(MCPUserError, match="no schema to choose"):
        create_table_group(
            connection_id=42,
            table_group_name="Files TG",
            schema="public",
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv")],
        )


@patch(f"{MODULE}.resolve_connection")
def test_declarations_are_refused_on_a_database_connection(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, create_table_group

    with _patch_perms(), pytest.raises(MCPUserError, match="only to a connection whose tables are files"):
        create_table_group(
            connection_id=42,
            table_group_name="Sample TG",
            schema="public",
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv")],
        )


@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_on_a_database_connection_still_needs_a_schema(mock_resolve, db_session_mock):
    mock_resolve.return_value = _mock_connection()

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms(), pytest.raises(MCPUserError, match="`schema` is required"):
        create_table_group(connection_id=42, table_group_name="Sample TG")


@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_replaces_the_declared_tables(mock_resolve_tg, mock_conn_cls, db_session_mock):
    table_group = _mock_table_group(table_groups_name="Files TG")
    table_group.table_group_schema = "main"
    table_group.file_declarations = [{"name": "old", "uri": "old.csv", "format": "csv", "options": {}}]
    mock_resolve_tg.return_value = table_group
    mock_conn_cls.get.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, update_table_group

    with _patch_perms():
        update_table_group(
            table_group_id=str(table_group.id),
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv")],
        )

    assert table_group.file_declarations == [
        {"name": "orders", "uri": "orders.csv", "format": "csv", "options": {}},
    ]
    # The declarations are the only thing that changed, so a diff that does not watch them reports
    # "no fields changed" and returns before the save.
    table_group.save.assert_called_once()


@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_reports_the_declared_tables_as_changed(
    mock_resolve_tg, mock_conn_cls, db_session_mock
):
    table_group = _mock_table_group(table_groups_name="Files TG")
    table_group.table_group_schema = "main"
    table_group.file_declarations = [{"name": "old", "uri": "old.csv", "format": "csv", "options": {}}]
    mock_resolve_tg.return_value = table_group
    mock_conn_cls.get.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, update_table_group

    with _patch_perms():
        output = update_table_group(
            table_group_id=str(table_group.id),
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv")],
        )

    assert "No fields changed" not in output
    assert "Declared tables" in output
    assert "orders" in output


@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_sees_a_path_change_on_the_same_table_names(
    mock_resolve_tg, mock_conn_cls, db_session_mock
):
    """The summary carries every stored field, so two lists sharing a name still differ."""
    table_group = _mock_table_group(table_groups_name="Files TG")
    table_group.table_group_schema = "main"
    table_group.file_declarations = [{"name": "orders", "uri": "old.csv", "format": "csv", "options": {}}]
    mock_resolve_tg.return_value = table_group
    mock_conn_cls.get.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, update_table_group

    with _patch_perms():
        output = update_table_group(
            table_group_id=str(table_group.id),
            file_declarations=[FileDeclaration(name="orders", uri="new.csv", format="csv")],
        )

    assert "No fields changed" not in output
    table_group.save.assert_called_once()


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.resolve_table_group")
def test_get_table_group_lists_the_declared_tables(mock_resolve_tg, mock_resolve_conn, db_session_mock):
    """An update replaces the whole list, so the caller needs somewhere to read it first."""
    table_group = _mock_table_group(table_groups_name="Files TG")
    table_group.table_group_schema = "main"
    table_group.file_declarations = [
        {"name": "orders", "uri": "sales/orders_*.csv", "format": "csv", "options": {"delimiter": "|"}},
    ]
    mock_resolve_tg.return_value = table_group
    mock_resolve_conn.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import get_table_group

    with _patch_perms():
        output = get_table_group(table_group_id=str(table_group.id))

    assert "orders" in output
    assert "sales/orders_*.csv" in output
    assert "delimiter=|" in output


@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_rejects_table_filters_on_a_files_connection(mock_resolve, db_session_mock):
    mock_resolve.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import FileDeclaration, create_table_group

    with _patch_perms(), pytest.raises(MCPUserError, match="table_set"):
        create_table_group(
            connection_id="1",
            table_group_name="Files TG",
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv")],
            table_set=["orders"],
        )


def test_a_declaration_rejects_csv_settings_on_another_format():
    """The fields are documented CSV-only, and a stored value for another format is dropped."""
    from testgen.mcp.tools.table_groups import FileDeclaration

    with pytest.raises(ValidationError, match="delimiter"):
        FileDeclaration(name="orders", uri="orders.parquet", format="parquet", delimiter="|")


def test_a_declaration_rejects_a_multi_character_quote():
    """DuckDB caps quote and escape at one byte, and the view fails to build without saying why."""
    from testgen.mcp.tools.table_groups import FileDeclaration

    with pytest.raises(ValidationError):
        FileDeclaration(name="orders", uri="orders.csv", format="csv", quote="ab")

    FileDeclaration(name="orders", uri="orders.csv", format="csv", delimiter="||")


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_names_a_declaration_it_could_not_read(
    mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock
):
    """A run does not stop for an unreadable declaration, so the preview is where it is reported.

    Without it the table is a row of zeroes, indistinguishable from one that is simply empty.
    """
    tg = _mock_table_group(table_groups_name="Files TG", table_group_schema="main")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _files_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {
                "id": tg.id,
                "table_groups_name": "Files TG",
                "table_group_schema": "main",
                "table_ct": 2,
                "column_ct": 3,
            },
            "tables": {
                "orders": {
                    "column_ct": 3,
                    "approx_record_ct": 100,
                    "approx_data_point_ct": 300,
                    "can_access": None,
                    "error": None,
                },
                "claims": {
                    "column_ct": 0,
                    "approx_record_ct": None,
                    "approx_data_point_ct": None,
                    "can_access": None,
                    "error": 'IO Error: No files found that match the pattern "claims_*.csv"',
                },
            },
            "success": True,
            "message": "1 table could not be read. Check the highlighted paths.",
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        # verify_access defaults to False, which is the path that reported nothing.
        output = preview_table_group(table_group_id=str(tg.id))

    assert "could not be read" in output
    assert "claims" in output
    assert "No files found" in output


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_reports_the_files_each_table_reads(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Files TG", table_group_schema="main")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _files_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {"id": tg.id, "table_groups_name": "Files TG", "table_ct": 1, "column_ct": 2},
            "tables": {
                "claims": {
                    "column_ct": 2,
                    "approx_record_ct": None,
                    "approx_data_point_ct": None,
                    "can_access": None,
                    "file_ct": 3,
                    "error": None,
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
        output = preview_table_group(table_group_id=str(tg.id))

    assert "| Table | Files | Columns | Approx Rows | Approx Data Points |" in output
    assert "| `claims` | 3 | 2 |" in output


def _preview_with_columns(tg, tables: dict) -> tuple:
    return (
        {
            "stats": {"id": tg.id, "table_groups_name": "Sample TG", "table_ct": len(tables), "column_ct": 0},
            "tables": tables,
            "success": True,
            "message": None,
        },
        None,
        None,
    )


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_lists_columns_only_when_asked(mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock):
    tg = _mock_table_group(table_groups_name="Sample TG", table_group_schema="public")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _mock_connection()
    mock_preview_svc.return_value = _preview_with_columns(tg, {
        "customer": {
            "column_ct": 2,
            "approx_record_ct": 100,
            "approx_data_point_ct": 200,
            "can_access": None,
            "columns": [
                {"column_name": "id", "column_type": "integer"},
                {"column_name": "email", "column_type": "character varying(255)"},
            ],
        },
    })

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        default_output = preview_table_group(table_group_id=str(tg.id))
        output = preview_table_group(table_group_id=str(tg.id), include_columns=True)

    assert "## Columns" not in default_output
    assert "character varying" not in default_output
    assert "## Columns" in output
    assert "### `customer`" in output
    assert "| Column | Type |\n| --- | --- |\n| `id` | integer |\n| `email` | character varying(255) |" in output


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_preview_lists_no_columns_for_an_unreadable_declaration(
    mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock,
):
    tg = _mock_table_group(table_groups_name="Files TG", table_group_schema="main")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _files_connection()
    mock_preview_svc.return_value = _preview_with_columns(tg, {
        "orders": {
            "column_ct": 1,
            "can_access": None,
            "file_ct": 1,
            "columns": [{"column_name": "order_id", "column_type": "BIGINT"}],
            "error": None,
        },
        "claims": {
            "column_ct": 0,
            "can_access": None,
            "columns": [],
            "error": "No files matched this path.",
        },
    })

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms():
        output = preview_table_group(table_group_id=str(tg.id), include_columns=True)

    assert "### `orders`" in output
    assert "| `order_id` | BIGINT |" in output
    assert "### `claims`" not in output
    # The column listing can run long, so the read failures come before it.
    assert output.index("No files matched this path.") < output.index("## Columns")


@patch(f"{MODULE}.TableGroup")
def test_list_table_groups_shows_no_schema_for_a_files_connection(mock_tg_cls, db_session_mock):
    """The stored value is the engine's own default schema, not one the user chose."""
    mock_tg_cls.list_for_project.return_value = (
        [_list_item(table_groups_name="files_tg", table_group_schema="main", sql_flavor_code="files")],
        1,
    )

    from testgen.mcp.tools.table_groups import list_table_groups

    with _patch_perms(permission="view"):
        output = list_table_groups(project_code="demo")

    assert "files_tg" in output
    assert "main" not in output


@patch(f"{MODULE}.resolve_connection")
@patch(f"{MODULE}.resolve_table_group")
def test_get_table_group_reports_no_schema_for_a_files_connection(
    mock_resolve_tg, mock_resolve_conn, db_session_mock
):
    """The stored value is the engine's own default schema, not one the user chose."""
    table_group = _mock_table_group(table_groups_name="Files TG")
    table_group.table_group_schema = "main"
    table_group.file_declarations = [{"name": "orders", "uri": "orders.csv", "format": "csv", "options": {}}]
    mock_resolve_tg.return_value = table_group
    mock_resolve_conn.return_value = _files_connection()

    from testgen.mcp.tools.table_groups import get_table_group

    with _patch_perms():
        output = get_table_group(table_group_id=str(table_group.id))

    assert "main" not in output
    assert "Schema" not in output


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_reports_the_declared_tables_not_a_schema(
    mock_resolve, mock_tg_cls, db_session_mock
):
    mock_resolve.return_value = _files_connection()
    instance = _mock_table_group(table_groups_name="Files TG")
    instance.table_group_schema = "main"

    def construct(**kwargs):
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    mock_tg_cls.side_effect = construct

    from testgen.mcp.tools.table_groups import FileDeclaration, create_table_group

    with _patch_perms():
        output = create_table_group(
            connection_id="1",
            table_group_name="Files TG",
            file_declarations=[FileDeclaration(name="orders", uri="orders.csv", format="csv", header=True)],
        )

    assert "Declared tables" in output
    assert "orders" in output
    assert "header=Yes" in output
    assert "main" not in output


# ---------------------------------------------------------------------------
# data catalog
# ---------------------------------------------------------------------------


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_writes_the_catalog(mock_resolve, mock_tg_cls, catalog_write, db_session_mock):
    connection = _mock_connection()
    mock_resolve.return_value = connection
    instance = _mock_table_group()
    mock_tg_cls.return_value = instance

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(connection_id=42, table_group_name="Sample TG", schema="public")

    catalog_write.assert_called_once_with(instance, connection)
    assert "data catalog" not in out


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_connection")
def test_create_table_group_reports_a_catalog_it_could_not_read(
    mock_resolve, mock_tg_cls, catalog_write, db_session_mock,
):
    mock_resolve.return_value = _mock_connection()
    mock_tg_cls.return_value = _mock_table_group()
    catalog_write.return_value = 'schema "public" does not exist'

    from testgen.mcp.tools.table_groups import create_table_group

    with _patch_perms():
        out = create_table_group(connection_id=42, table_group_name="Sample TG", schema="public")

    assert "Table Group `Sample TG` created" in out
    assert (
        "The data catalog could not be read from the target, so it is empty until the table group is "
        'profiled or tested. schema "public" does not exist'
    ) in out


@pytest.mark.parametrize(
    ("argument", "value"),
    [("include_mask", "fact_%"), ("exclude_mask", "tmp_%"), ("table_set", ["orders", "customers"])],
)
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_refreshes_the_catalog_when_its_tables_change(
    mock_resolve, mock_tg_cls, catalog_write, db_session_mock, argument, value,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        update_table_group(table_group_id=str(tg.id), **{argument: value})

    catalog_write.assert_called_once()
    assert catalog_write.call_args.args[0] is tg


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_leaves_the_catalog_when_its_tables_stay(
    mock_resolve, mock_tg_cls, catalog_write, db_session_mock,
):
    tg = _mock_table_group(description=None)
    mock_resolve.return_value = tg

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        update_table_group(table_group_id=str(tg.id), description="Nightly load")

    catalog_write.assert_not_called()


@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_reports_a_catalog_it_could_not_read(
    mock_resolve, mock_tg_cls, catalog_write, db_session_mock,
):
    tg = _mock_table_group()
    mock_resolve.return_value = tg
    catalog_write.return_value = "connection refused"

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        out = update_table_group(table_group_id=str(tg.id), include_mask="fact_%")

    assert (
        "The data catalog could not be read from the target, so it keeps the tables it had before this "
        "change until the table group is profiled or tested. connection refused"
    ) in out


@patch(f"{SERVICE_MODULE}.apply_schema_move")
@patch(f"{MODULE}.move_table_group_schema")
@patch(f"{MODULE}.TableGroup")
@patch(f"{MODULE}.resolve_table_group")
def test_update_table_group_leaves_the_catalog_to_a_schema_move(
    mock_resolve, mock_tg_cls, mock_move, mock_apply, catalog_write, db_session_mock,
):
    tg = _mock_table_group(table_group_schema="public")
    mock_resolve.return_value = tg

    def move(table_group, schema, **_kwargs):
        table_group.table_group_schema = schema
        return SchemaMove(previous_schema="public", schema=schema, missing_tables=[], definitions_repointed=0)

    mock_move.side_effect = move

    from testgen.mcp.tools.table_groups import update_table_group

    with _patch_perms():
        update_table_group(table_group_id=str(tg.id), schema="staging", include_mask="fact_%")

    mock_apply.assert_called_once()
    catalog_write.assert_not_called()


@patch(f"{MODULE}.preview_table_group_service")
@patch(f"{MODULE}.Connection")
@patch(f"{MODULE}.resolve_table_group")
def test_a_declaration_read_error_is_withheld_under_source_data_protection(
    mock_resolve, mock_conn_cls, mock_preview_svc, db_session_mock
):
    """A file read error can quote the file's contents, which are source data."""
    tg = _mock_table_group(table_groups_name="Files TG", table_group_schema="main")
    mock_resolve.return_value = tg
    mock_conn_cls.get_by_table_group.return_value = _files_connection()
    mock_preview_svc.return_value = (
        {
            "stats": {"id": tg.id, "table_groups_name": "Files TG", "table_group_schema": "main"},
            "tables": {
                "claims": {
                    "column_ct": 0,
                    "approx_record_ct": None,
                    "approx_data_point_ct": None,
                    "can_access": None,
                    "error": 'Invalid Input Error: Error when converting column "ssn": "123-45-6789"',
                },
            },
            "success": True,
            "message": "1 table could not be read. Check the highlighted paths.",
        },
        None,
        None,
    )

    from testgen.mcp.tools.table_groups import preview_table_group

    with _patch_perms(), patch("testgen.mcp.tools.common.mcp_source_data_protected", return_value=True):
        output = preview_table_group(table_group_id=str(tg.id))

    assert "claims" in output
    assert "123-45-6789" not in output
    assert "withheld by the source-data protection policy" in output
