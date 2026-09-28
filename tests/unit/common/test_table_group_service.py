"""Tests for the table_group_service common-layer module.

Covers ``validate_table_group_fields`` and ``preview_table_group`` (happy path,
verify-access flag, partial-inaccessible footer, no-connection branch,
connection failure, empty result).
"""

from unittest.mock import patch

import pytest

from testgen.common.database.column_chars import ObjectType
from testgen.common.database.table_group_service import (
    apply_table_group_flavor_rules,
    preview_table_group,
    validate_table_group_fields,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
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
    assert "`schema` is required." in errors


def test_validate_blank_schema():
    errors = validate_table_group_fields(_tg(table_group_schema="   "))
    assert "`schema` is required." in errors


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
    assert "`schema` is required." in joined
    assert "`profiling_delay_days` must be a non-negative integer." in joined
    assert "`profile_sample_percent` must be between 1 and 100." in joined
    assert "`profile_sample_min_count` must be a non-negative integer." in joined


# ---------------------------------------------------------------------------
# preview_table_group — lifted UI logic
# ---------------------------------------------------------------------------


def _column_row(table_name: str, column_name: str, approx_record_ct: int | None = None) -> dict:
    return {
        "schema_name": "public",
        "table_name": table_name,
        "column_name": column_name,
        "ordinal_position": 1,
        "general_type": "A",
        "column_type": "varchar",
        "db_data_type": "VARCHAR",
        "is_decimal": False,
        "approx_record_ct": approx_record_ct,
        "record_ct": None,
    }


def _session(mock_session, respond, declaration_failures=None):
    """Point the patched ``target_db_session`` at a runner answering with ``respond(query)``."""
    def run(query, _params=None):
        return respond(query)
    target = TargetQuery(run, declaration_failures or {})
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
        "Some tables were not accessible. Please check the database permissions."
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

    assert "`schema` is required." not in errors
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
