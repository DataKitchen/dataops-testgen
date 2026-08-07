"""Tests for the table_group_service common-layer module.

Covers ``validate_table_group_fields`` and ``preview_table_group`` (happy path,
verify-access flag, partial-inaccessible footer, no-connection branch,
connection failure, empty result).
"""

from unittest.mock import patch

import pytest

from testgen.common.database.table_group_service import (
    preview_table_group,
    validate_table_group_fields,
)
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup

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
        "profile_sample_percent": "30",
        "profile_sample_min_count": 100000,
        "profiling_delay_days": "0",
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


@pytest.mark.parametrize("bad_delay", ["-1", "-100"])
def test_validate_delay_days_negative(bad_delay):
    errors = validate_table_group_fields(_tg(profiling_delay_days=bad_delay))
    assert "`profiling_delay_days` must be a non-negative integer." in errors


def test_validate_delay_days_non_integer():
    errors = validate_table_group_fields(_tg(profiling_delay_days="abc"))
    assert "`profiling_delay_days` must be a non-negative integer." in errors


def test_validate_delay_days_int_input_accepted():
    """Validator accepts int input as well — apply-args casts but validators should be tolerant."""
    assert validate_table_group_fields(_tg(profiling_delay_days=0)) == []


@pytest.mark.parametrize("bad_pct", ["0", "101", "200", "-1"])
def test_validate_sample_percent_out_of_range(bad_pct):
    errors = validate_table_group_fields(_tg(profile_sample_percent=bad_pct))
    assert "`profile_sample_percent` must be between 1 and 100." in errors


def test_validate_sample_percent_non_integer():
    errors = validate_table_group_fields(_tg(profile_sample_percent="abc"))
    assert "`profile_sample_percent` must be between 1 and 100." in errors


def test_validate_sample_percent_int_input_accepted():
    assert validate_table_group_fields(_tg(profile_sample_percent=50)) == []


def test_validate_sample_min_count_negative():
    errors = validate_table_group_fields(_tg(profile_sample_min_count=-5))
    assert "`profile_sample_min_count` must be a non-negative integer." in errors


def test_validate_aggregates_all_errors():
    """Multiple failures are collected and surfaced together — never one-at-a-time."""
    errors = validate_table_group_fields(_tg(
        table_groups_name="",
        table_group_schema="",
        profiling_delay_days="-1",
        profile_sample_percent="200",
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


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db")
def test_preview_returns_picklable_shape(mock_fetch, mock_sql_cls):
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
    mock_fetch.return_value = [_column_row("customer", "id", approx_record_ct=100)]

    result = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert isinstance(result, tuple) and len(result) == 3, (
        "preview_table_group must return (preview, data_chars, sql_generator)"
    )
    preview, data_chars, sql_gen = result
    assert isinstance(preview, dict)
    assert not isfunction(data_chars), "data_chars must not be a local closure"
    assert not isfunction(sql_gen), "sql_generator must not be a local closure"


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db")
def test_preview_happy_path_aggregates_stats(mock_fetch, mock_sql_cls):
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    mock_fetch.return_value = [
        _column_row("customer", "id", approx_record_ct=100),
        _column_row("customer", "email", approx_record_ct=100),
        _column_row("rental", "id", approx_record_ct=50),
    ]

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
@patch(f"{MODULE}.fetch_from_target_db")
def test_preview_verify_access_marks_all_accessible(mock_fetch, mock_sql_cls):
    """When verify_access=True and every table is reachable, no footer message is set."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.return_value = ("SELECT 1", None)
    mock_fetch.side_effect = [
        [_column_row("customer", "id", approx_record_ct=100)],  # initial DDF
        [{"col": 1}],  # verify customer
    ]

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["message"] is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db")
def test_preview_verify_access_empty_table_is_accessible(mock_fetch, mock_sql_cls):
    """An empty table is accessible. The probe is ``SELECT 1 FROM <table> LIMIT 1``, which
    returns zero rows on a zero-row table; a permission failure raises instead. Judging
    access by row count reports every empty table as inaccessible."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.return_value = ("SELECT 1", None)
    mock_fetch.side_effect = [
        [_column_row("customer", "id", approx_record_ct=0)],  # initial DDF
        [],  # verify customer — empty table, query succeeded
    ]

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["message"] is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db")
def test_preview_verify_access_partial_failure_sets_footer(mock_fetch, mock_sql_cls):
    """One inaccessible table → can_access=False AND the UI-verbatim footer message."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})
    sql_generator.verify_access.side_effect = lambda name: (f"SELECT 1 FROM {name}", None)

    def fetch_side_effect(_conn_arg, query, *_args, **_kwargs):
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

    mock_fetch.side_effect = fetch_side_effect

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=True)

    assert preview["success"] is True
    assert preview["tables"]["customer"]["can_access"] is True
    assert preview["tables"]["rental"]["can_access"] is False
    assert preview["message"] == (
        "Some tables were not accessible. Please check the database permissions."
    )


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db", side_effect=RuntimeError("connection refused"))
def test_preview_connection_failure_marks_unsuccessful(mock_fetch, mock_sql_cls):
    """When the DDF query blows up, preview comes back ``success=False`` carrying the driver text."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})

    preview, data_chars, sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is False
    assert "connection refused" in (preview["message"] or "")
    assert data_chars is None
    assert sql_gen is None


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db", return_value=[])
def test_preview_empty_result_uses_ui_verbatim_message(mock_fetch, mock_sql_cls):
    """Zero matching tables → UI-verbatim "No tables found matching the criteria." message."""
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})

    preview, _data_chars, _sql_gen = preview_table_group(_tg(), connection=_conn(), verify_access=False)

    assert preview["success"] is False
    assert preview["message"] == (
        "No tables found matching the criteria. Please check the Table Group configuration"
        " or the database permissions."
    )


@patch(f"{MODULE}.RefreshDataCharsSQL")
@patch(f"{MODULE}.fetch_from_target_db", return_value=[])
def test_preview_empty_result_still_returns_generator(mock_fetch, mock_sql_cls):
    """Zero matching tables is signalled by ``success``, not by ``None`` elements.

    Only the no-connection and exception branches blank the second and third
    elements. A caller that reads them as the failure signal would build a save
    callback here, so ``success`` is the check that matters.
    """
    sql_generator = mock_sql_cls.return_value
    sql_generator.flavor_service.metadata_via_api = False
    sql_generator.get_schema_ddf.return_value = ("SELECT ...", {})

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
