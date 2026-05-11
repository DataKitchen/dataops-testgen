"""Tests for TestDefinition.validate() and TestDefinition.editable_fields()."""

from unittest.mock import MagicMock

import pytest

from testgen.common.models.test_definition import (
    InvalidTestDefinitionFields,
    Severity,
    TestDefinition,
    _required_fields_for,
)


def make_test_type(
    code: str = "Alpha_Trunc",
    scope: str = "column",
    param_columns: set[str] | None = None,
    default_parm_columns: str | None = "threshold_value",
    default_parm_required: str | None = None,
) -> MagicMock:
    """Build a TestType-shaped mock with the attributes the validator reads."""
    tt = MagicMock()
    tt.test_type = code
    tt.test_scope = scope
    tt.param_columns = param_columns if param_columns is not None else {"threshold_value"}
    tt.default_parm_columns = default_parm_columns
    tt.default_parm_required = default_parm_required
    return tt


def make_td(**fields) -> TestDefinition:
    """Build a TestDefinition with the given fields set, nothing else."""
    td = TestDefinition()
    for key, value in fields.items():
        setattr(td, key, value)
    return td


# -- _required_fields_for -----------------------------------------------------


def test_required_fields_column_scope_adds_column_name():
    tt = make_test_type(scope="column")
    assert "column_name" in _required_fields_for(tt)


def test_required_fields_table_scope_no_column_name():
    tt = make_test_type(code="Row_Ct", scope="table", param_columns=set(), default_parm_columns=None)
    assert "column_name" not in _required_fields_for(tt)


def test_required_fields_custom_query_when_in_param_columns():
    tt = make_test_type(
        code="CUSTOM",
        scope="custom",
        param_columns={"custom_query", "match_column_names"},
        default_parm_columns="custom_query,match_column_names",
    )
    assert "custom_query" in _required_fields_for(tt)


def test_required_fields_parses_default_parm_required():
    tt = make_test_type(
        code="Metric_Trend",
        scope="custom",
        param_columns={"custom_query", "threshold_value", "baseline_value"},
        default_parm_columns="custom_query,threshold_value,baseline_value",
        default_parm_required="Y,Y,N",
    )
    required = _required_fields_for(tt)
    assert "custom_query" in required
    assert "threshold_value" in required
    assert "baseline_value" not in required


def test_required_fields_null_required_means_no_extras():
    tt = make_test_type(scope="column", default_parm_required=None)
    assert _required_fields_for(tt) == {"column_name"}


# -- TestDefinition.editable_fields -------------------------------------------


def test_editable_fields_includes_base_set():
    tt = make_test_type(param_columns=set(), default_parm_columns=None)
    td = make_td()
    accepted = td.editable_fields(tt)
    assert {"test_active", "severity", "lock_refresh", "flagged", "test_description"} <= accepted


def test_editable_fields_includes_param_columns():
    tt = make_test_type(param_columns={"threshold_value", "baseline_value"})
    td = make_td()
    accepted = td.editable_fields(tt)
    assert {"threshold_value", "baseline_value"} <= accepted


def test_editable_fields_does_not_leak_identity_or_internal_columns():
    tt = make_test_type(param_columns={"threshold_value"})
    td = make_td()
    accepted = td.editable_fields(tt)
    # Identity fields — callers must never set these via fields/extra_params
    for forbidden in ("test_suite_id", "table_groups_id", "test_type", "schema_name"):
        assert forbidden not in accepted
    # Internal/system-managed columns
    for forbidden in ("profile_run_id", "external_id", "prediction", "last_auto_gen_date"):
        assert forbidden not in accepted


# -- TestDefinition.validate --------------------------------------------------


def test_validate_happy_path():
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10")
    td.validate(tt)  # no raise


def test_validate_missing_required_column_name():
    tt = make_test_type(scope="column")
    td = make_td(threshold_value="10")  # no column_name
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "column_name" in exc_info.value.errors


def test_validate_wrong_scope_column_name_rejected():
    tt = make_test_type(code="Row_Ct", scope="table", param_columns=set())
    td = make_td(column_name="email")
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "column_name" in exc_info.value.errors


def test_validate_custom_scope_accepts_column_name_as_label():
    # CUSTOM uses column_name as a "Test Focus" label — must be accepted.
    tt = make_test_type(
        code="CUSTOM",
        scope="custom",
        param_columns={"custom_query"},
        default_parm_columns="custom_query",
    )
    td = make_td(column_name="Negative Total Check", custom_query="SELECT 1")
    td.validate(tt)  # no raise


def test_validate_custom_query_not_accepted():
    tt = make_test_type()  # param_columns = {threshold_value}; no custom_query allowed
    td = make_td(column_name="email", threshold_value="10", custom_query="SELECT 1")
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "custom_query" in exc_info.value.errors


def test_validate_severity_accepts_valid_strenum_values():
    tt = make_test_type()
    for value in ("Fail", "Warning"):
        td = make_td(column_name="email", threshold_value="10", severity=value)
        td.validate(tt)


def test_validate_severity_rejects_invalid():
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10", severity="critical")
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "severity" in exc_info.value.errors


def test_validate_severity_case_sensitive():
    # Per CLAUDE.md, case-sensitive — "fail" must be rejected.
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10", severity="fail")
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "severity" in exc_info.value.errors


def test_validate_severity_empty_string_treated_as_unset():
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10", severity="")
    td.validate(tt)  # empty severity is OK — falls back to test type default


def test_validate_aggregates_errors():
    tt = make_test_type(scope="column")
    td = make_td(severity="critical", custom_query="SELECT 1")  # no column_name
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    errors = exc_info.value.errors
    assert {"column_name", "severity", "custom_query"} <= errors.keys()


def test_validate_empty_string_treats_required_field_as_cleared():
    tt = make_test_type(scope="column")
    td = make_td(column_name="", threshold_value="10")
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "column_name" in exc_info.value.errors


def test_severity_enum_value_accepted():
    # StrEnum subclasses str, so setting severity to the enum should pass validate.
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10", severity=Severity.FAIL)
    td.validate(tt)
