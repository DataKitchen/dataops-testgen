"""Tests for TestDefinition model methods."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_definition import (
    CUSTOM_METADATA_MAX_BYTES,
    CUSTOM_METADATA_MAX_KEYS,
    InvalidTestDefinitionFields,
    Severity,
    TestDefinition,
    TestDefinitionSummary,
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
    """Build a TestDefinition with the given fields set. table_name defaults to a non-empty value
    (required for most scopes) unless the caller overrides it."""
    td = TestDefinition()
    fields.setdefault("table_name", "orders")
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


def test_required_fields_custom_query_required_via_flag():
    # custom_query requiredness is driven by default_parm_required, not special-cased.
    tt = make_test_type(
        code="CUSTOM",
        scope="custom",
        param_columns={"custom_query", "match_column_names"},
        default_parm_columns="custom_query,match_column_names",
        default_parm_required="Y,N",
    )
    required = _required_fields_for(tt)
    assert "custom_query" in required
    assert "match_column_names" not in required


def test_required_fields_custom_query_optional_when_flag_off():
    # A test type may expose custom_query without requiring it when the flag says N.
    tt = make_test_type(
        code="Some_Type",
        scope="custom",
        param_columns={"custom_query"},
        default_parm_columns="custom_query",
        default_parm_required="N",
    )
    assert "custom_query" not in _required_fields_for(tt)


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


def test_required_fields_null_required_means_no_param_extras():
    # No default_parm_required flags → only the scope-implied fields (column_name + table_name).
    tt = make_test_type(scope="column", default_parm_required=None)
    assert _required_fields_for(tt) == {"column_name", "table_name"}


def test_required_fields_table_name_required_for_physical_scope():
    for scope in ("column", "table", "referential"):
        tt = make_test_type(scope=scope)
        assert "table_name" in _required_fields_for(tt), scope


def test_required_fields_table_name_not_required_for_tablegroup():
    tt = make_test_type(code="Schema_Drift", scope="tablegroup", param_columns=set(), default_parm_columns=None)
    assert "table_name" not in _required_fields_for(tt)


def test_required_fields_table_name_not_required_for_custom_type():
    tt = make_test_type(
        code="CUSTOM",
        scope="custom",
        param_columns={"custom_query"},
        default_parm_columns="custom_query",
    )
    assert "table_name" not in _required_fields_for(tt)


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


def test_editable_fields_includes_click_through_fields():
    tt = make_test_type(param_columns=set(), default_parm_columns=None)
    td = make_td()
    accepted = td.editable_fields(tt)
    assert {"external_url", "custom_metadata"} <= accepted


def test_editable_fields_includes_impact_dimension_only_for_custom_or_referential_scope():
    """impact_dimension is overridable only for user-defined-semantic scopes."""
    td = make_td()

    custom_tt = make_test_type(scope="custom", param_columns={"custom_query"})
    assert "impact_dimension" in td.editable_fields(custom_tt)

    referential_tt = make_test_type(scope="referential", param_columns={"match_column_names"})
    assert "impact_dimension" in td.editable_fields(referential_tt)

    column_tt = make_test_type(scope="column", param_columns={"threshold_value"})
    assert "impact_dimension" not in td.editable_fields(column_tt)

    table_tt = make_test_type(scope="table", param_columns=set())
    assert "impact_dimension" not in td.editable_fields(table_tt)


def test_editable_fields_includes_column_name_except_for_table_scope():
    """column_name is meaningful for column (column under test), custom (label), and referential
    (aggregate expression / categorical column list) scopes — but not table scope."""
    td = make_td()

    column_tt = make_test_type(scope="column", param_columns={"threshold_value"})
    assert "column_name" in td.editable_fields(column_tt)

    custom_tt = make_test_type(scope="custom", param_columns={"custom_query"})
    assert "column_name" in td.editable_fields(custom_tt)

    referential_tt = make_test_type(scope="referential", param_columns={"match_column_names"})
    assert "column_name" in td.editable_fields(referential_tt)

    table_tt = make_test_type(scope="table", param_columns=set())
    assert "column_name" not in td.editable_fields(table_tt)


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


def test_validate_missing_table_name_rejected():
    tt = make_test_type(scope="column")
    td = make_td(column_name="email", threshold_value="10", table_name=None)
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "table_name" in exc_info.value.errors


def test_validate_custom_type_accepts_missing_table_name():
    # CUSTOM supplies its own FROM via custom_query; the table is only an output label.
    tt = make_test_type(code="CUSTOM", scope="custom", param_columns={"custom_query"}, default_parm_columns="custom_query")
    td = make_td(custom_query="SELECT 1", table_name=None)
    td.validate(tt)  # no raise


def test_validate_tablegroup_accepts_missing_table_name():
    tt = make_test_type(code="Schema_Drift", scope="tablegroup", param_columns=set(), default_parm_columns=None)
    td = make_td(table_name=None)
    td.validate(tt)  # no raise — spans the whole table group


def test_validate_referential_scope_accepts_column_name():
    # Referential tests use column_name as the aggregate expression / categorical column list.
    tt = make_test_type(code="Aggregate_Balance", scope="referential", param_columns={"match_column_names"})
    td = make_td(column_name="SUM(total_amount)", match_column_names="SUM(total_amount)")
    td.validate(tt)  # no raise


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


def test_validate_custom_metadata_accepts_object_and_none():
    tt = make_test_type()
    make_td(column_name="email", threshold_value="10", custom_metadata={"pipeline": "p1"}).validate(tt)
    make_td(column_name="email", threshold_value="10", custom_metadata=None).validate(tt)
    make_td(column_name="email", threshold_value="10", custom_metadata={}).validate(tt)


@pytest.mark.parametrize("bad_value", ["a string", ["a", "b"], 42])
def test_validate_custom_metadata_rejects_non_object(bad_value):
    tt = make_test_type()
    td = make_td(column_name="email", threshold_value="10", custom_metadata=bad_value)
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "custom_metadata" in exc_info.value.errors


def test_validate_custom_metadata_rejects_too_many_keys():
    tt = make_test_type()
    too_many = {f"k{i}": "v" for i in range(CUSTOM_METADATA_MAX_KEYS + 1)}
    td = make_td(column_name="email", threshold_value="10", custom_metadata=too_many)
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "custom_metadata" in exc_info.value.errors


def test_validate_custom_metadata_rejects_oversized():
    tt = make_test_type()
    oversized = {"blob": "x" * (CUSTOM_METADATA_MAX_BYTES + 1)}
    td = make_td(column_name="email", threshold_value="10", custom_metadata=oversized)
    with pytest.raises(InvalidTestDefinitionFields) as exc_info:
        td.validate(tt)
    assert "custom_metadata" in exc_info.value.errors


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


# --- select_page ---

def _make_summary_row(table_name: str = "my_table") -> dict:
    return {
        "id": uuid4(),
        "table_groups_id": uuid4(),
        "profile_run_id": uuid4(),
        "test_type": "CUSTOM",
        "test_suite_id": uuid4(),
        "test_description": None,
        "schema_name": "public",
        "table_name": table_name,
        "column_name": "col1",
        "skip_errors": 0,
        "baseline_ct": None,
        "baseline_unique_ct": None,
        "baseline_value": None,
        "baseline_value_ct": None,
        "threshold_value": None,
        "baseline_sum": None,
        "baseline_avg": None,
        "baseline_sd": None,
        "lower_tolerance": None,
        "upper_tolerance": None,
        "subset_condition": None,
        "groupby_names": None,
        "having_condition": None,
        "window_date_column": None,
        "window_days": None,
        "match_schema_name": None,
        "match_table_name": None,
        "match_column_names": None,
        "match_subset_condition": None,
        "match_groupby_names": None,
        "match_having_condition": None,
        "custom_query": None,
        "history_calculation": None,
        "history_calculation_upper": None,
        "history_lookback": None,
        "test_active": True,
        "test_definition_status": None,
        "severity": None,
        "lock_refresh": False,
        "last_auto_gen_date": None,
        "profiling_as_of_date": None,
        "last_manual_update": datetime.now(),
        "export_to_observability": False,
        "prediction": None,
        "flagged": False,
        "impact_dimension": None,
        "external_url": None,
        "custom_metadata": None,
        "test_name_short": "Custom",
        "default_test_description": "A test",
        "measure_uom": "",
        "measure_uom_description": "",
        "default_parm_columns": "",
        "default_parm_prompts": "",
        "default_parm_help": "",
        "default_parm_required": "",
        "default_severity": "Warning",
        "test_scope": "column",
        "dq_dimension": "",
        "default_impact_dimension": "",
        "usage_notes": "",
    }


@patch("testgen.common.models.entity.get_current_session")
def test_select_page_returns_items_and_total(mock_get_session):
    rows = [_make_summary_row("table_a"), _make_summary_row("table_b"), _make_summary_row("table_c")]
    mock_session = mock_get_session.return_value
    mock_session.scalar.return_value = 3
    mock_session.execute.return_value.mappings.return_value.all.return_value = rows

    items, total = TestDefinition.select_page()

    assert total == 3
    assert len(items) == 3
    assert all(isinstance(item, TestDefinitionSummary) for item in items)
    assert items[0].table_name == "table_a"
    assert items[2].table_name == "table_c"


@patch("testgen.common.models.entity.get_current_session")
def test_select_page_empty_result_returns_zero_total(mock_get_session):
    mock_session = mock_get_session.return_value
    mock_session.scalar.return_value = 0
    mock_session.execute.return_value.mappings.return_value.all.return_value = []

    items, total = TestDefinition.select_page()

    assert items == []
    assert total == 0


@patch("testgen.common.models.entity.get_current_session")
def test_select_page_uses_correct_offset_and_limit(mock_get_session):
    mock_session = mock_get_session.return_value
    mock_session.scalar.return_value = 0
    mock_session.execute.return_value.mappings.return_value.all.return_value = []

    TestDefinition.select_page(page=3, limit=100)

    call_args = mock_session.execute.call_args
    query = call_args[0][0]
    compiled = query.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)

    assert "LIMIT 100" in sql
    assert "OFFSET 200" in sql


@patch("testgen.common.models.entity.get_current_session")
def test_select_page_first_page_has_no_offset(mock_get_session):
    mock_session = mock_get_session.return_value
    mock_session.scalar.return_value = 0
    mock_session.execute.return_value.mappings.return_value.all.return_value = []

    TestDefinition.select_page(page=1, limit=500)

    call_args = mock_session.execute.call_args
    query = call_args[0][0]
    compiled = query.compile(compile_kwargs={"literal_binds": True})
    sql = str(compiled)

    assert "LIMIT 500" in sql
    assert "OFFSET 0" in sql
