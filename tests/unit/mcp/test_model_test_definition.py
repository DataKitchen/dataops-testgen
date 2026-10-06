from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from testgen.common.models.test_definition import (
    TestDefinition,
    ThresholdMode,
)


@pytest.fixture
def session_mock():
    with (
        patch("testgen.common.models.test_definition.get_current_session") as td_mock,
        patch("testgen.common.models.entity.get_current_session") as entity_mock,
    ):
        entity_mock.return_value = td_mock.return_value
        yield td_mock.return_value


def _compiled_sql(captured_query) -> str:
    return str(captured_query.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
    ))


def test_get_for_project_excludes_monitor_suites(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    TestDefinition.get_for_project(uuid4())

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "test_suites.suite_type = 'regular'" in sql
    assert "JOIN test_suites" in sql


def test_get_for_project_excludes_monitor_suites_with_project_codes(session_mock):
    session_mock.execute.return_value.mappings.return_value.first.return_value = None

    TestDefinition.get_for_project(uuid4(), project_codes=["demo"])

    sql = _compiled_sql(session_mock.execute.call_args[0][0])
    assert "test_suites.suite_type = 'regular'" in sql
    assert "test_suites.project_code IN" in sql


def test_list_for_suite_excludes_monitor_suites(session_mock):
    session_mock.scalar.return_value = 0
    session_mock.execute.return_value.all.return_value = []

    TestDefinition.list_for_suite(test_suite_id=uuid4())

    # _paginate wraps the original query as a subquery for counting — the suite_type
    # filter is preserved in the compiled SQL for either call, so check both.
    queries = [call[0][0] for call in session_mock.scalar.call_args_list]
    queries += [call[0][0] for call in session_mock.execute.call_args_list]
    sql_joined = "\n".join(_compiled_sql(q) for q in queries)
    assert "test_suites.suite_type = 'regular'" in sql_joined
    assert "JOIN test_suites" in sql_joined


# ---------------------------------------------------------------------------
# _derive_threshold_mode — must match the UI form's detection at
# test_definition_form.js:274 (history_calculation == "PREDICT" → Prediction;
# any other non-empty value → Historical; empty → Static; schema → N/A).
# ``threshold_value`` must never leak into the returned bounds.
# ---------------------------------------------------------------------------


def _td(**overrides):
    defaults = {
        "test_type": "Volume_Trend",
        "history_calculation": None,
        "history_calculation_upper": None,
        "lower_tolerance": None,
        "upper_tolerance": None,
        "threshold_value": None,
        "prediction": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_derive_threshold_mode_schema_returns_none():
    td = _td(test_type="Schema_Drift", history_calculation="PREDICT", lower_tolerance="5")
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert (mode, lower, upper) == (ThresholdMode.NONE, None, None)


def test_derive_threshold_mode_prediction_keys_on_history_calculation_not_prediction_jsonb():
    """``history_calculation == "PREDICT"`` is the canonical signal — the
    ``prediction`` JSONB is empty during training or after a failed run, so
    keying off it would misreport prediction monitors as Static."""
    td = _td(test_type="Volume_Trend", history_calculation="PREDICT", prediction=None)
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert mode == ThresholdMode.PREDICTION
    assert lower is None and upper is None


def test_derive_threshold_mode_historical_for_non_freshness():
    td = _td(
        test_type="Volume_Trend",
        history_calculation="Minimum",
        history_calculation_upper="Maximum",
    )
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert (mode, lower, upper) == (ThresholdMode.HISTORICAL, "Minimum", "Maximum")


def test_derive_threshold_mode_historical_blocked_for_freshness():
    """Freshness does not support Historical mode — a stray
    ``history_calculation`` value falls through to Static."""
    td = _td(
        test_type="Freshness_Trend",
        history_calculation="Minimum",
        upper_tolerance="720",
    )
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert mode == ThresholdMode.STATIC
    assert lower is None  # Freshness has no lower bound
    assert upper == "720"


def test_derive_threshold_mode_static_freshness_uses_upper_only():
    td = _td(test_type="Freshness_Trend", lower_tolerance="60", upper_tolerance="720")
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert mode == ThresholdMode.STATIC
    assert lower is None  # lower is silently dropped for Freshness even if populated
    assert upper == "720"


def test_derive_threshold_mode_static_volume_uses_both_tolerances():
    td = _td(test_type="Volume_Trend", lower_tolerance="900", upper_tolerance="1100")
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert (mode, lower, upper) == (ThresholdMode.STATIC, "900", "1100")


def test_derive_threshold_mode_threshold_value_never_returned():
    """``threshold_value`` is not a monitor configuration — even when no
    tolerances are set it must not leak into the bounds."""
    td = _td(test_type="Volume_Trend", threshold_value="42")
    mode, lower, upper = TestDefinition._derive_threshold_mode(td)
    assert mode == ThresholdMode.STATIC
    assert lower is None
    assert upper is None


# ---------------------------------------------------------------------------
# forecast_points_from_prediction — extracts forecast rows from a monitor's
# stored prediction JSONB. Keys are epoch-millisecond integer strings; the
# helper must agree with the dashboard's reader at ``monitors_dashboard.py``.
# Standalone (not bound to the ORM class) so it works against either the
# ORM row or the ``TestDefinitionSummary`` dataclass.
# ---------------------------------------------------------------------------


def _epoch_ms(ts: datetime) -> str:
    return str(int(ts.timestamp() * 1000))


def test_forecast_points_returns_sorted_per_sensitivity_band():
    from testgen.common.models.test_definition import forecast_points_from_prediction

    t1 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
    t3 = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    prediction = {
        "lower_tolerance|medium": {_epoch_ms(t2): 90.0, _epoch_ms(t1): 100.0, _epoch_ms(t3): 80.0},
        "upper_tolerance|medium": {_epoch_ms(t1): 110.0, _epoch_ms(t2): 120.0, _epoch_ms(t3): 130.0},
        # Other sensitivities present but not selected:
        "lower_tolerance|low": {_epoch_ms(t1): 200.0},
    }

    points = forecast_points_from_prediction(prediction, "medium")

    assert [p.test_time for p in points] == [t1, t2, t3]
    assert [p.lower_bound for p in points] == [100.0, 90.0, 80.0]
    assert [p.upper_bound for p in points] == [110.0, 120.0, 130.0]


def test_forecast_points_returns_empty_when_no_prediction():
    from testgen.common.models.test_definition import forecast_points_from_prediction
    assert forecast_points_from_prediction(None, "medium") == []
    assert forecast_points_from_prediction({}, "medium") == []


def test_forecast_points_returns_empty_for_unknown_sensitivity():
    from testgen.common.models.test_definition import forecast_points_from_prediction
    prediction = {"lower_tolerance|medium": {_epoch_ms(datetime(2026, 7, 1, tzinfo=UTC)): 1.0}}
    assert forecast_points_from_prediction(prediction, "high") == []


def test_forecast_points_handles_one_sided_bounds():
    """When a sensitivity has only one of lower/upper stored, the other
    bound on each point should come through as ``None`` rather than skipping
    the point entirely."""
    from testgen.common.models.test_definition import forecast_points_from_prediction

    t1 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    prediction = {"upper_tolerance|medium": {_epoch_ms(t1): 130.0}}

    points = forecast_points_from_prediction(prediction, "medium")

    assert len(points) == 1
    assert points[0].test_time == t1
    assert points[0].lower_bound is None
    assert points[0].upper_bound == 130.0


# --- NON_PUBLIC_TEST_TYPES / TestType.is_public ---


def test_non_public_test_types_are_the_monitor_types():
    """Monitor suites own the monitor types, so the regular-test catalogs withhold every one of them."""
    from testgen.common.enums import MonitorType
    from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES

    assert NON_PUBLIC_TEST_TYPES == frozenset(monitor.value for monitor in MonitorType)


def test_is_public_clause_excludes_non_public_types():
    from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES, TestType

    sql = str(TestType.is_public().compile(compile_kwargs={"literal_binds": True}))

    assert "test_types.test_type NOT IN" in sql
    for code in NON_PUBLIC_TEST_TYPES:
        assert f"'{code}'" in sql


def _type_row(test_type: str, ai_redact_values):
    from testgen.common.models.test_definition import TestType

    return SimpleNamespace(
        test_type=test_type,
        ai_redact_values=ai_redact_values,
        redacts_values=TestType.redacts_values.fget(
            SimpleNamespace(ai_redact_values=ai_redact_values)
        ),
    )


def test_value_redacted_types_reads_the_column_not_a_name_list():
    """The classification comes from the flag, so editing a YAML is enough to change it."""
    from testgen.common.models.test_definition import TestType

    rows = [_type_row("Recency", True), _type_row("Required", False), _type_row("LOV_All", True)]
    with patch.object(TestType, "select_where", return_value=rows):
        assert TestType.value_redacted_types() == frozenset({"Recency", "LOV_All"})


def test_value_redacted_types_accepts_rows_already_in_hand():
    """Callers that already hold the catalog classify without a second query."""
    from testgen.common.models.test_definition import TestType

    rows = [_type_row("Recency", True), _type_row("Required", False)]
    with patch.object(TestType, "select_where") as select_mock:
        assert TestType.value_redacted_types(rows) == frozenset({"Recency"})
    select_mock.assert_not_called()


def test_null_flag_reads_as_redacted():
    """A column added without its backfill must not read as safe."""
    from testgen.common.models.test_definition import TestType

    rows = [_type_row("Mystery", None)]
    with patch.object(TestType, "select_where", return_value=rows):
        assert TestType.value_redacted_types() == frozenset({"Mystery"})


def test_value_redacted_types_is_empty_when_nothing_is_flagged():
    from testgen.common.models.test_definition import TestType

    with patch.object(TestType, "select_where", return_value=[]):
        assert TestType.value_redacted_types() == frozenset()


def test_packaged_flag_values_keep_the_migration_flags():
    """Every type the migration flags stays flagged in its packaged YAML.

    The YAML importer sets the flag on every install and upgrade, so a type added after the
    migration is flagged in its YAML alone.
    """
    import re
    from pathlib import Path

    import yaml

    dirs = [
        Path("testgen/testgen/template/dbsetup_test_types"),
        Path("plugins/testgen_medical_pharma/testgen_medical_pharma/template/medical_pharma_test_types"),
    ]
    flagged_in_yaml = set()
    for directory in dirs:
        for path in directory.glob("test_types_*.yaml"):
            parent = (yaml.safe_load(path.read_text()) or {}).get("test_types") or {}
            assert isinstance(parent.get("ai_redact_values"), bool), f"{path.name} missing the flag"
            if parent["ai_redact_values"]:
                flagged_in_yaml.add(parent["test_type"])

    migrations = [
        path
        for path in Path("testgen/testgen/template/dbupgrade").glob("*_incremental_upgrade.sql")
        if "ai_redact_values" in path.read_text()
    ]
    assert len(migrations) == 1, f"expected one migration to seed the flag, found {migrations}"

    update_clause = migrations[0].read_text().split("WHERE test_type IN", 1)[1]
    flagged_in_migration = set(re.findall(r"'([A-Za-z0-9_]+)'", update_clause))

    assert flagged_in_migration <= flagged_in_yaml
