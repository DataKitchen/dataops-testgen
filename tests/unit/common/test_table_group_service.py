"""Tests for the table_group_service common-layer module.

Covers ``validate_table_group_fields``, ``table_group_defaults``,
``is_duplicate_name_error`` and ``preview_table_group`` (happy path,
verify-access flag, partial-inaccessible footer, no-connection branch,
connection failure, empty result).
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from testgen import settings
from testgen.common.database.column_chars import ObjectType
from testgen.common.database.table_group_service import (
    SchemaMove,
    apply_table_group_flavor_rules,
    catalog_membership,
    is_duplicate_name_error,
    preview_table_group,
    update_catalog_for_edit,
    validate_table_group_fields,
    write_table_group_catalog,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import SCHEMA_NAME_MAX_LENGTH, TableGroup, table_group_defaults
from testgen.ui.services.database_service import TargetQuery

pytestmark = pytest.mark.unit

MODULE = "testgen.common.database.table_group_service"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tg(**overrides) -> TableGroup:
    """Build a TableGroup without touching the DB. Defaults to a valid baseline."""
    defaults = {
        "project_code": "demo",
        "connection_id": 7,
        "table_groups_name": "Sample TG",
        "table_group_schema": "public",
        "profile_use_sampling": False,
        "profile_sample_percent": 30,
        "profile_sample_min_count": 100000,
        "profiling_delay_days": 0,
    }
    defaults.update(overrides)
    return TableGroup(**defaults)


def _conn(**overrides) -> Connection:
    defaults = {
        "sql_flavor": "postgresql",
        "sql_flavor_code": "postgresql",
        "connection_id": 7,
        "project_code": "demo",
        "connection_name": "Local PG",
        "project_host": "localhost",
        "project_port": "5432",
        "project_db": "demo",
        "project_user": "demo",
    }
    defaults.update(overrides)
    return Connection(**defaults)


# ---------------------------------------------------------------------------
# validate_table_group_fields — happy paths and per-field errors
# ---------------------------------------------------------------------------


def test_validate_passes_baseline():
    assert validate_table_group_fields(_tg()) == []


def test_validate_missing_name():
    errors = validate_table_group_fields(_tg(table_groups_name=None))
    assert "`table_group_name` is required." in errors


def test_validate_blank_name():
    errors = validate_table_group_fields(_tg(table_groups_name="   "))
    assert "`table_group_name` is required." in errors


def test_validate_name_too_short():
    errors = validate_table_group_fields(_tg(table_groups_name="ab"))
    assert "`table_group_name` must be between 3 and 40 characters." in errors


def test_validate_name_too_long():
    errors = validate_table_group_fields(_tg(table_groups_name="a" * 41))
    assert "`table_group_name` must be between 3 and 40 characters." in errors


def test_validate_name_at_lower_bound_passes():
    assert validate_table_group_fields(_tg(table_groups_name="abc")) == []


def test_validate_name_at_upper_bound_passes():
    assert validate_table_group_fields(_tg(table_groups_name="a" * 40)) == []


def test_validate_missing_schema():
    errors = validate_table_group_fields(_tg(table_group_schema=None))
    assert "`schema_name` is required." in errors


def test_validate_blank_schema():
    errors = validate_table_group_fields(_tg(table_group_schema="   "))
    assert "`schema_name` is required." in errors


@pytest.mark.parametrize("bad_delay", [-1, -100])
def test_validate_delay_days_negative(bad_delay):
    errors = validate_table_group_fields(_tg(profiling_delay_days=bad_delay))
    assert "`profiling_delay_days` must be a non-negative integer." in errors


def test_validate_delay_days_non_integer():
    errors = validate_table_group_fields(_tg(profiling_delay_days="abc"))
    assert "`profiling_delay_days` must be a non-negative integer." in errors


def test_validate_delay_days_zero_accepted():
    assert validate_table_group_fields(_tg(profiling_delay_days=0)) == []


@pytest.mark.parametrize("bad_pct", [0, 101, 200, -1])
def test_validate_sample_percent_out_of_range(bad_pct):
    errors = validate_table_group_fields(_tg(profile_sample_percent=bad_pct))
    assert "`profile_sample_percent` must be between 1 and 100." in errors


def test_validate_sample_percent_non_integer():
    errors = validate_table_group_fields(_tg(profile_sample_percent="abc"))
    assert "`profile_sample_percent` must be between 1 and 100." in errors


def test_validate_sample_percent_in_range_accepted():
    assert validate_table_group_fields(_tg(profile_sample_percent=50)) == []


def test_validate_sample_min_count_negative():
    errors = validate_table_group_fields(_tg(profile_sample_min_count=-5))
    assert "`profile_sample_min_count` must be a non-negative integer." in errors


def test_validate_aggregates_all_errors():
    """Multiple failures are collected and surfaced together — never one-at-a-time."""
    errors = validate_table_group_fields(_tg(
        table_groups_name="",
        table_group_schema="",
        profiling_delay_days=-1,
        profile_sample_percent=200,
        profile_sample_min_count=-5,
    ))
    joined = "\n".join(errors)
    assert "`table_group_name` is required." in joined
    assert "`schema_name` is required." in joined
    assert "`profiling_delay_days` must be a non-negative integer." in joined
    assert "`profile_sample_percent` must be between 1 and 100." in joined
    assert "`profile_sample_min_count` must be a non-negative integer." in joined


def test_validate_names_fields_by_their_public_names_by_default():
    errors = validate_table_group_fields(_tg(
        table_groups_name="",
        table_group_schema="",
        profiling_include_mask="x" * 2001,
    ))

    assert errors == [
        "`table_group_name` is required.",
        "`schema_name` is required.",
        "`include_masks` must be at most 2000 characters in total, counting a comma between entries.",
    ]


def test_validate_names_fields_by_the_supplied_mapping():
    errors = validate_table_group_fields(
        _tg(table_groups_name="", table_group_schema="", profile_sample_percent=0),
        field_names={"table_group_schema": "schema"},
    )

    assert errors == [
        "`table_group_name` is required.",
        "`schema` is required.",
        "`profile_sample_percent` must be between 1 and 100.",
    ]


def test_validate_name_length_counts_the_padding_it_is_stored_with():
    errors = validate_table_group_fields(_tg(table_groups_name=" " * 30 + "Sample TG" + " " * 30))

    assert errors == ["`table_group_name` must be between 3 and 40 characters."]


@pytest.mark.parametrize(
    ("attr", "max_length", "message_name"),
    [
        ("profile_id_column_mask", 2000, "profile_id_column_mask"),
        ("profile_sk_column_mask", 150, "profile_sk_column_mask"),
        ("description", 1000, "description"),
        ("data_source", 40, "data_source"),
        ("data_classification", 40, "data_classification"),
    ],
)
def test_validate_rejects_a_value_wider_than_its_column(attr, max_length, message_name):
    assert validate_table_group_fields(_tg(**{attr: "x" * max_length})) == []
    assert validate_table_group_fields(_tg(**{attr: "x" * (max_length + 1)})) == [
        f"`{message_name}` must be at most {max_length} characters.",
    ]


def test_validate_rejects_a_schema_wider_than_the_catalog_holds():
    """The schema is capped by its own rule rather than by the table_groups column, because the
    catalog columns it has to land in are narrower than that column."""
    errors = validate_table_group_fields(_tg(table_group_schema="a" * (SCHEMA_NAME_MAX_LENGTH + 1)))

    assert f"`schema_name` must be at most {SCHEMA_NAME_MAX_LENGTH} characters." in errors


def test_validate_rejects_a_schema_that_would_end_the_quoting():
    errors = validate_table_group_fields(_tg(table_group_schema='sales" OR 1=1--'))

    assert "`schema_name` must not contain quote characters or control characters." in errors


@pytest.mark.parametrize(
    ("attr", "message_name"),
    [
        ("profiling_table_set", "table_set"),
        ("profiling_include_mask", "include_masks"),
        ("profiling_exclude_mask", "exclude_masks"),
    ],
)
def test_validate_measures_a_list_column_as_stored(attr, message_name):
    """The list columns hold their entries comma-joined, so the width counts the commas."""
    tables = [f"client_table_{i:03d}" for i in range(120)]

    errors = validate_table_group_fields(_tg(**{attr: ",".join(tables)}))

    assert errors == [
        f"`{message_name}` must be at most 2000 characters in total, counting a comma between entries.",
    ]


def test_validate_rejects_integers_beyond_their_columns():
    errors = validate_table_group_fields(_tg(profiling_delay_days=2**31, profile_sample_min_count=2**63))

    assert errors == [
        f"`profiling_delay_days` must be at most {2**31 - 1}.",
        f"`profile_sample_min_count` must be at most {2**63 - 1}.",
    ]


def test_validate_accepts_integers_at_their_column_limits():
    assert validate_table_group_fields(_tg(profiling_delay_days=2**31 - 1, profile_sample_min_count=2**63 - 1)) == []


# ---------------------------------------------------------------------------
# table_group_defaults
# ---------------------------------------------------------------------------


def test_defaults_let_a_named_table_group_pass_validation():
    table_group = TableGroup(table_groups_name="Sample TG", table_group_schema="public", **table_group_defaults())

    assert validate_table_group_fields(table_group) == []


def test_defaults_mirror_the_model_column_defaults():
    defaults = table_group_defaults()

    assert defaults["profile_sample_percent"] == 30
    assert defaults["profile_sample_min_count"] == 100000
    assert defaults["profile_id_column_mask"] == "%_id"
    assert defaults["profile_sk_column_mask"] == "%_sk"
    assert defaults["profile_table_comparison"] is False
    assert "id" not in defaults


def test_defaults_carry_the_configured_table_and_column_masks():
    with (
        patch.object(settings, "DEFAULT_PROFILING_INCLUDE_MASK", "fact_%"),
        patch.object(settings, "DEFAULT_PROFILING_EXCLUDE_MASK", "stg_%"),
        patch.object(settings, "DEFAULT_PROFILING_ID_COLUMN_MASK", "%_key"),
        patch.object(settings, "DEFAULT_PROFILING_SK_COLUMN_MASK", "%_surrogate"),
    ):
        defaults = table_group_defaults()

    assert defaults["profiling_include_mask"] == "fact_%"
    assert defaults["profiling_exclude_mask"] == "stg_%"
    assert defaults["profile_id_column_mask"] == "%_key"
    assert defaults["profile_sk_column_mask"] == "%_surrogate"


def test_defaults_are_a_fresh_copy():
    table_group_defaults()["profile_sample_percent"] = 99

    assert table_group_defaults()["profile_sample_percent"] == 30


# ---------------------------------------------------------------------------
# is_duplicate_name_error
# ---------------------------------------------------------------------------


def _integrity_error(message: str) -> IntegrityError:
    return IntegrityError("stmt", {}, Exception(message))


def test_is_duplicate_name_error_matches_the_name_index():
    err = _integrity_error('duplicate key value violates unique constraint "table_groups_name_unique"')

    assert is_duplicate_name_error(err)


def test_is_duplicate_name_error_ignores_other_violations():
    err = _integrity_error('insert or update on table "table_groups" violates foreign key constraint')

    assert not is_duplicate_name_error(err)


# ---------------------------------------------------------------------------
# preview_table_group — lifted UI logic
# ---------------------------------------------------------------------------


def _column_row(
    table_name: str,
    column_name: str,
    approx_record_ct: int | None = None,
    column_type: str = "varchar",
) -> dict:
    return {
        "schema_name": "public",
        "table_name": table_name,
        "column_name": column_name,
        "ordinal_position": 1,
        "general_type": "A",
        "column_type": column_type,
        "db_data_type": "VARCHAR",
        "is_decimal": False,
        "approx_record_ct": approx_record_ct,
        "record_ct": None,
    }


def _session(mock_session, respond, declaration_failures=None):
    """Point the patched ``target_db_session`` at a runner answering with ``respond(query)``."""
    def run(query, _params=None):
        return respond(query)
    target = TargetQuery(run, declaration_failures or {}, MagicMock())
    mock_session.return_value.__enter__.return_value = target
    return target


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_returns_picklable_shape(mock_session, mock_sql_cls):
    """Contract: return ``(preview, data_chars, sql_generator)`` — three picklable values.

    A local ``save_data_chars`` closure as the second element would fail
    pickling (``Can't get local object 'preview_table_group.<locals>.save_data_chars'``)
    in any caller that caches the result. Closures are built by callers via
    ``make_save_data_chars``.
    """
    from inspect import isfunction

    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    _session(mock_session, lambda _query: [_column_row("customer", "id", approx_record_ct=100)])

    result = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert isinstance(result, tuple) and len(result) == 3, (
        "preview_table_group must return (preview, data_chars, sql_generator)"
    )
    preview, data_chars, sql_gen = result
    assert isinstance(preview, dict)
    assert not isfunction(data_chars), "data_chars must not be a local closure"
    assert not isfunction(sql_gen), "sql_generator must not be a local closure"


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_happy_path_aggregates_stats(mock_session, mock_sql_cls):
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    _session(mock_session, lambda _query: [
        _column_row("customer", "id", approx_record_ct=100),
        _column_row("customer", "email", approx_record_ct=100),
        _column_row("rental", "id", approx_record_ct=50),
    ])

    preview, data_chars, sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is True
    assert preview["message"] is None
    assert preview["stats"]["table_ct"] == 2
    assert preview["stats"]["column_ct"] == 3
    assert preview["stats"]["approx_record_ct"] == 150  # 100 + 50, counted once per table
    assert "customer" in preview["tables"]
    assert "rental" in preview["tables"]
    assert preview["tables"]["customer"]["column_ct"] == 2
    assert data_chars is not None and len(data_chars) == 3
    assert sql_gen is sql_generator


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_lists_each_database_tables_columns_in_catalog_order(mock_session, mock_sql_cls):
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    _session(mock_session, lambda _query: [
        _column_row("customer", "id", column_type="integer"),
        _column_row("customer", "email", column_type="character varying(255)"),
        _column_row("rental", "rented_at", column_type="timestamp"),
    ])

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["tables"]["customer"]["columns"] == [
        {"column_name": "id", "column_type": "integer"},
        {"column_name": "email", "column_type": "character varying(255)"},
    ]
    assert preview["tables"]["rental"]["columns"] == [{"column_name": "rented_at", "column_type": "timestamp"}]
    # Only a file declaration carries an `error` key; a database table's read access is reported through `can_access`.
    assert "error" not in preview["tables"]["customer"]


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_verify_access_marks_all_accessible(mock_session, mock_sql_cls):
    """When verify_access=True and every table is reachable, no footer message is set."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.return_value = ("SELECT 1", None)
    _session(mock_session, lambda query: (
        [_column_row("customer", "id", approx_record_ct=100)] if "SELECT ..." in query else [{"col": 1}]
    ))

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["message"] is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_verify_access_empty_table_is_accessible(mock_session, mock_sql_cls):
    """An empty table is accessible. The probe is ``SELECT 1 FROM <table> LIMIT 1``, which
    returns zero rows on a zero-row table; a permission failure raises instead. Judging
    access by row count reports every empty table as inaccessible."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.return_value = ("SELECT 1", None)
    _session(mock_session, lambda query: (
        [_column_row("customer", "id", approx_record_ct=0)] if "SELECT ..." in query else []
    ))

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["message"] is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_verify_access_partial_failure_sets_footer(mock_session, mock_sql_cls):
    """One inaccessible table → can_access=False AND the UI-verbatim footer message."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.side_effect = lambda name: (f"SELECT 1 FROM {name}", None)

    def respond(query):
        if "SELECT ..." in query:
            return [
                _column_row("customer", "id", approx_record_ct=100),
                _column_row("rental", "id", approx_record_ct=50),
            ]
        if "SELECT 1 FROM customer" in query:
            return [{"col": 1}]
        if "SELECT 1 FROM rental" in query:
            raise RuntimeError("permission denied")
        raise AssertionError(f"unexpected query: {query}")

    _session(mock_session, respond)

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["tables"]["rental"]["can_access"] is False
    assert preview["message"] == (
        "Some tables were not accessible. Check that TestGen has read access to them."
    )


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_connection_failure_marks_unsuccessful(mock_session, mock_sql_cls):
    """When the DDF query blows up, preview comes back ``success=False`` carrying the driver text."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    mock_session.return_value.__enter__.side_effect = RuntimeError("connection refused")

    preview, data_chars, sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is False
    assert "connection refused" in (preview["message"] or "")
    assert data_chars is None
    assert sql_gen is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_empty_result_uses_ui_verbatim_message(mock_session, mock_sql_cls):
    """Zero matching tables → UI-verbatim "No tables found matching the criteria." message."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    _session(mock_session, lambda _query: [])

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is False
    assert preview["message"] == (
        "No tables found matching the criteria. Please check the Table Group configuration"
        " or the database permissions."
    )


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_preview_empty_result_still_returns_generator(mock_session, mock_sql_cls):
    """Zero matching tables is signalled by ``success``, not by ``None`` elements.

    Only the no-connection and exception branches blank the second and third
    elements. A caller that reads them as the failure signal would build a save
    callback here, so ``success`` is the check that matters.
    """
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    _session(mock_session, lambda _query: [])

    preview, data_chars, sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is False
    assert data_chars == []
    assert sql_gen is sql_generator


def test_preview_no_connection_returns_failure_no_io():
    """No connection passed AND no ``table_group.connection_id`` → fail fast, no DB calls attempted."""
    tg = _tg(connection_id=None)
    preview, data_chars, sql_gen = preview_table_group(tg, connection=None, verify_access=False)

    assert preview["success"] is False
    assert preview["message"] is not None
    assert "connection" in preview["message"].lower()
    assert data_chars is None
    assert sql_gen is None


# ---------------------------------------------------------------------------
# apply_table_group_flavor_rules
# ---------------------------------------------------------------------------


def _files_conn(**overrides) -> Connection:
    return _conn(sql_flavor="duckdb", sql_flavor_code="files",
                 parameters={"base_path": "/data/claims"}, **overrides)


def test_a_file_connection_pins_the_schema_the_form_does_not_show():
    table_group = _tg(table_group_schema=None, file_declarations=[{"name": "claims", "uri": "c.csv", "format": "csv"}])

    apply_table_group_flavor_rules(table_group, _files_conn())

    assert table_group.table_group_schema == "main"


def test_a_file_connection_clears_the_criteria_it_does_not_use():
    table_group = _tg(
        profiling_table_set="a, b",
        profiling_include_mask="%",
        profiling_exclude_mask="tmp%",
        file_declarations=[{"name": "claims", "uri": "c.csv", "format": "csv"}],
    )

    apply_table_group_flavor_rules(table_group, _files_conn())

    assert table_group.profiling_table_set is None
    assert table_group.profiling_include_mask is None
    assert table_group.profiling_exclude_mask is None


def test_a_database_connection_clears_declarations_left_behind():
    table_group = _tg(file_declarations=[{"name": "claims", "uri": "c.csv", "format": "csv"}])

    apply_table_group_flavor_rules(table_group, _conn())

    assert table_group.file_declarations is None
    assert table_group.table_group_schema == "public"


def test_no_connection_settles_nothing():
    table_group = _tg(file_declarations=[{"name": "claims", "uri": "c.csv", "format": "csv"}])

    apply_table_group_flavor_rules(table_group, None)

    assert table_group.file_declarations == [{"name": "claims", "uri": "c.csv", "format": "csv"}]


def test_a_file_table_group_needs_no_schema_but_needs_declarations():
    errors = validate_table_group_fields(_tg(table_group_schema=None, file_declarations=[]), _files_conn())

    assert "`schema_name` is required." not in errors
    assert "Declare at least one table." in errors


def test_a_file_table_group_reports_a_declaration_that_breaks_a_rule():
    table_group = _tg(
        table_group_schema=None,
        file_declarations=[{"name": "9bad", "uri": "claims.csv", "format": "csv"}],
    )

    errors = validate_table_group_fields(table_group, _files_conn())

    assert any("must start with a letter or underscore" in error for error in errors)


# ---------------------------------------------------------------------------
# Preview of a table group whose tables are declared as files
# ---------------------------------------------------------------------------


def _files_preview(mock_session, mock_sql_cls, *, rows, declarations, failures=None):
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ddf", {})
    sql_generator.filter_schema_columns.side_effect = lambda columns: columns
    sql_generator.get_file_counts.return_value = []
    table_group = _tg(table_group_schema="main", file_declarations=declarations)
    sql_generator.table_group = table_group

    _session(mock_session, lambda _query: rows, failures)
    return table_group, sql_generator


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_a_declaration_that_failed_reports_why_it_failed(mock_session, mock_sql_cls):
    """The reason is computed when the view is built; without it every cause reads the same."""
    table_group, _ = _files_preview(
        mock_session,
        mock_sql_cls,
        rows=[_column_row("claims", "id")],
        declarations=[
            {"name": "claims", "uri": "claims.csv", "format": "csv"},
            {"name": "escapee", "uri": "../secret.csv", "format": "csv"},
        ],
        failures={"escapee": "This path is outside the connection base path."},
    )

    preview, _, _ = preview_table_group(table_group, connection=_files_conn(), verify_access=False)

    assert preview["tables"]["escapee"]["error"] == "This path is outside the connection base path."
    assert preview["tables"]["claims"]["error"] is None
    assert preview["tables"]["claims"]["columns"] == [{"column_name": "id", "column_type": "varchar"}]
    assert preview["tables"]["escapee"]["columns"] == []


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_a_declaration_with_no_reason_falls_back_to_no_files_matched(mock_session, mock_sql_cls):
    table_group, _ = _files_preview(
        mock_session,
        mock_sql_cls,
        rows=[_column_row("claims", "id")],
        declarations=[
            {"name": "claims", "uri": "claims.csv", "format": "csv"},
            {"name": "missing", "uri": "absent.csv", "format": "csv"},
        ],
    )

    preview, _, _ = preview_table_group(table_group, connection=_files_conn(), verify_access=False)

    assert preview["tables"]["missing"]["error"] == "No files matched this path."
    assert preview["message"] == "1 table could not be read. Check the highlighted paths."


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_each_file_table_reports_the_files_it_reads(mock_session, mock_sql_cls):
    table_group, sql_generator = _files_preview(
        mock_session,
        mock_sql_cls,
        rows=[],
        declarations=[{"name": "claims", "uri": "claims_*.csv", "format": "csv"}],
    )
    sql_generator.get_file_counts.return_value = [("SELECT file counts", None)]
    _session(mock_session, lambda query: (
        [{"table_name": "claims", "file_ct": 3}]
        if query == "SELECT file counts"
        else [_column_row("claims", "id"), _column_row("claims", "amount")]
    ))

    preview, data_chars, _ = preview_table_group(table_group, connection=_files_conn(), verify_access=False)

    assert preview["tables"]["claims"]["file_ct"] == 3
    # The columns saved from the preview carry it too, so the catalog written from it is complete.
    assert {(column.object_type, column.file_ct) for column in data_chars} == {(ObjectType.FILES, 3)}


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_a_declaration_whose_files_cannot_be_counted_still_previews(mock_session, mock_sql_cls):
    """Credentials that can read an object but not list its bucket fail only that declaration's count."""
    table_group, sql_generator = _files_preview(
        mock_session,
        mock_sql_cls,
        rows=[],
        declarations=[
            {"name": "claims", "uri": "claims.csv", "format": "csv"},
            {"name": "locked", "uri": "locked/data.csv", "format": "csv"},
        ],
    )
    sql_generator.get_file_counts.return_value = [("count claims", None), ("count locked", None)]

    def respond(query):
        if query == "count claims":
            return [{"table_name": "claims", "file_ct": 1}]
        if query == "count locked":
            raise RuntimeError("HTTP 403 listing locked/")
        return [_column_row("claims", "id"), _column_row("locked", "id")]

    _session(mock_session, respond)

    preview, _, _ = preview_table_group(table_group, connection=_files_conn(), verify_access=False)

    assert preview["success"] is True
    assert preview["tables"]["claims"]["file_ct"] == 1
    assert preview["tables"]["locked"]["file_ct"] is None
    assert preview["tables"]["locked"]["error"] is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.target_db_session")
def test_a_declaration_that_failed_is_not_counted(mock_session, mock_sql_cls):
    table_group, sql_generator = _files_preview(
        mock_session,
        mock_sql_cls,
        rows=[_column_row("claims", "id")],
        declarations=[
            {"name": "claims", "uri": "claims.csv", "format": "csv"},
            {"name": "missing", "uri": "absent.csv", "format": "csv"},
        ],
        failures={"missing": "No files matched this path."},
    )

    preview_table_group(table_group, connection=_files_conn(), verify_access=False)

    assert sql_generator.get_file_counts.call_args.kwargs["skip"] == {"missing": "No files matched this path."}


# --- write_table_group_catalog ---


@patch(f"{MODULE}.make_save_data_chars")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.preview_table_group")
def test_the_table_group_commits_before_the_target_is_read(mock_preview, mock_session, mock_make_save):
    steps = MagicMock()
    steps.attach_mock(mock_session.return_value.commit, "commit")
    steps.attach_mock(mock_preview, "preview")
    steps.attach_mock(mock_make_save.return_value, "write")
    data_chars, sql_generator = [MagicMock()], MagicMock()
    mock_preview.return_value = ({"success": True, "message": None}, data_chars, sql_generator)
    table_group = _tg()

    assert write_table_group_catalog(table_group, _conn()) is None

    assert [name for name, *_ in steps.mock_calls] == ["commit", "preview", "write"]
    mock_make_save.assert_called_once_with(data_chars, sql_generator)
    mock_make_save.return_value.assert_called_once_with(table_group.id)


@patch(f"{MODULE}.make_save_data_chars")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.preview_table_group")
def test_an_unreadable_target_writes_nothing_and_says_why(mock_preview, _session, mock_make_save):
    mock_preview.return_value = ({"success": False, "message": "connection refused"}, None, None)

    assert write_table_group_catalog(_tg(), _conn()) == "connection refused"

    mock_make_save.assert_not_called()


@patch(f"{MODULE}.make_save_data_chars")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.preview_table_group")
def test_a_scan_that_finds_no_tables_writes_nothing_and_says_why(mock_preview, _session, mock_make_save):
    mock_preview.return_value = ({"success": False, "message": "No tables found"}, [], MagicMock())

    assert write_table_group_catalog(_tg(), _conn()) == "No tables found"

    mock_make_save.assert_not_called()


@patch(f"{MODULE}.make_save_data_chars")
@patch(f"{MODULE}.get_current_session")
@patch(f"{MODULE}.preview_table_group")
def test_a_failed_write_says_why(mock_preview, _session, mock_make_save):
    mock_preview.return_value = ({"success": True, "message": None}, [MagicMock()], MagicMock())
    mock_make_save.return_value.side_effect = RuntimeError("deadlock detected")

    assert write_table_group_catalog(_tg(), _conn()) == "deadlock detected"


# --- catalog_membership ---


def test_an_empty_form_value_matches_the_null_it_replaces():
    stored = TableGroup(table_group_schema="sales", profiling_table_set=None, file_declarations=None)
    posted = TableGroup(table_group_schema="sales", profiling_table_set="", file_declarations=[])

    assert catalog_membership(posted) == catalog_membership(stored)


def test_a_changed_mask_changes_the_membership():
    before = TableGroup(table_group_schema="sales", profiling_include_mask="%")
    after = TableGroup(table_group_schema="sales", profiling_include_mask="order%")

    assert catalog_membership(after) != catalog_membership(before)


# --- update_catalog_for_edit ---


@patch(f"{MODULE}.write_table_group_catalog")
@patch(f"{MODULE}.apply_schema_move")
def test_a_schema_move_writes_the_catalog_through_the_move(mock_apply, mock_write):
    table_group = TableGroup(table_group_schema="staging", profiling_include_mask="order%")
    membership_before = catalog_membership(TableGroup(table_group_schema="sales", profiling_include_mask="%"))
    move = SchemaMove(previous_schema="sales", schema="staging", missing_tables=[], definitions_repointed=0)

    assert update_catalog_for_edit(table_group, membership_before, move) is None

    mock_apply.assert_called_once_with(move, table_group.id)
    mock_write.assert_not_called()


@patch(f"{MODULE}.write_table_group_catalog", return_value="connection refused")
@patch(f"{MODULE}.apply_schema_move")
def test_a_membership_change_rewrites_the_catalog_and_says_why_it_failed(mock_apply, mock_write):
    table_group = TableGroup(table_group_schema="sales", profiling_include_mask="order%")
    membership_before = catalog_membership(TableGroup(table_group_schema="sales", profiling_include_mask="%"))
    connection = _conn()

    assert update_catalog_for_edit(table_group, membership_before, None, connection) == "connection refused"

    mock_write.assert_called_once_with(table_group, connection)
    mock_apply.assert_not_called()


@patch(f"{MODULE}.write_table_group_catalog")
@patch(f"{MODULE}.apply_schema_move")
def test_an_edit_that_keeps_the_tables_leaves_the_catalog(mock_apply, mock_write):
    table_group = TableGroup(table_group_schema="sales", profiling_include_mask="%", description="Nightly load")
    membership_before = catalog_membership(TableGroup(table_group_schema="sales", profiling_include_mask="%"))

    assert update_catalog_for_edit(table_group, membership_before, None) is None

    mock_write.assert_not_called()
    mock_apply.assert_not_called()
