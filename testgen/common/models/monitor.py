"""Monitor read-model façade and shared series parsing.

A "monitor" is the public concept backing the monitors dashboard. Internally it is a
``TestDefinition`` in a monitor ``TestSuite`` (``is_monitor`` = True); that fact is never
exposed. This module owns the single-monitor series read (the ``Monitor`` façade) plus the
shared SQL builder and row→event parsers reused by the per-table dashboard wrapper.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from testgen.common.enums import MonitorType
from testgen.common.models import get_current_session
from testgen.common.models.test_definition import ThresholdMode, derive_threshold_mode
from testgen.utils import dict_from_kv


def _as_float(value) -> float | None:
    return float(value) if value not in (None, "") else None


def _as_int(value) -> int | None:
    """Parse an integer signal; None for missing or non-numeric values.

    The Freshness_Trend template emits ``result_signal = 'Unknown'`` on its no-change
    branch when the update interval can't be computed, and error rows may carry other
    non-numeric text — neither should raise.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(result_code, target: int) -> bool | None:
    """Tri-state flag: None when the result is missing (no run produced a row)."""
    return int(result_code) == target if result_code is not None else None


def _is_error(row: dict) -> bool:
    return row.get("result_status") == "Error"


def parse_value_event(row: dict) -> dict:
    """Volume / Metric point: measured value + per-point bands from input_parameters."""
    params = dict_from_kv(row.get("input_parameters") or "")
    pending = not bool(row.get("result_id"))
    return {
        "time": row["test_time"],
        "value": _as_float(row.get("result_signal")),
        "lower_bound": _as_float(params.get("lower_tolerance")),
        "upper_bound": _as_float(params.get("upper_tolerance")),
        "threshold_value": _as_float(params.get("threshold_value")),
        "is_anomaly": _flag(row.get("result_code"), 0),
        "is_training": _flag(row.get("result_code"), -1),
        "is_error": _is_error(row),
        "is_pending": pending,
    }


def parse_freshness_event(row: dict) -> dict:
    """Freshness point: minutes-since-update + staleness, sourced like the value bands."""
    params = dict_from_kv(row.get("input_parameters") or "")
    minutes = _as_int(row.get("result_signal"))
    return {
        "time": row["test_time"],
        "minutes_since_update": minutes,
        "staleness_threshold": _as_float(params.get("threshold_value")),
        "lower_bound": _as_float(params.get("lower_tolerance")),
        "upper_bound": _as_float(params.get("upper_tolerance")),
        "update_detected": minutes == 0,
        "is_anomaly": _flag(row.get("result_code"), 0),
        "is_training": _flag(row.get("result_code"), -1),
        "is_error": _is_error(row),
        "is_pending": not bool(row.get("result_id")),
    }


def parse_schema_event(row: dict) -> dict:
    """Schema point: structural-change counts parsed from the pipe-delimited result_signal."""
    parts = (row.get("result_signal") or "|0|0|0|").split("|")
    # Pad so missing trailing fields (e.g. window_start) don't IndexError.
    parts += [""] * (5 - len(parts))
    return {
        "time": row["test_time"],
        "table_change": parts[0] or None,
        "additions": int(parts[1]) if parts[1] else 0,
        "deletions": int(parts[2]) if parts[2] else 0,
        "modifications": int(parts[3]) if parts[3] else 0,
        "window_start": datetime.fromisoformat(parts[4]) if parts[4] else None,
        "is_error": _is_error(row),
    }


def current_bands(
    test_type: str,
    history_calculation: str | None,
    prediction: dict | None,
    predict_sensitivity: str,
    lower_tolerance: str | None,
    upper_tolerance: str | None,
    threshold_value: str | None,
    *,
    is_training: bool,
) -> dict | None:
    """Latest bands for the series header. None while training or for schema (no bands)."""
    if is_training or test_type == MonitorType.SCHEMA.value:
        return None

    if test_type == MonitorType.FRESHNESS.value:
        return {
            "staleness_threshold": _as_float(threshold_value or upper_tolerance),
            "expected_gap": {"lower_bound": _as_float(lower_tolerance), "upper_bound": _as_float(upper_tolerance)},
        }

    # Volume / Metric
    if history_calculation == "PREDICT" and prediction and (mean := prediction.get("mean")):
        latest = max(mean.keys())  # ms-epoch string keys; lexicographic == chronological for equal width
        lower = prediction.get(f"lower_tolerance|{predict_sensitivity}", {}).get(latest)
        upper = prediction.get(f"upper_tolerance|{predict_sensitivity}", {}).get(latest)
        return {"lower_bound": _as_float(lower), "upper_bound": _as_float(upper)}
    return {"lower_bound": _as_float(lower_tolerance), "upper_bound": _as_float(upper_tolerance)}


_PARSERS = {
    MonitorType.FRESHNESS.value: parse_freshness_event,
    MonitorType.VOLUME.value: parse_value_event,
    MonitorType.METRIC.value: parse_value_event,
    MonitorType.SCHEMA.value: parse_schema_event,
}


_TABLE_SCOPE_TYPES = (
    MonitorType.FRESHNESS.value,
    MonitorType.VOLUME.value,
    MonitorType.SCHEMA.value,
    MonitorType.METRIC.value,
)


def build_series_sql(
    *,
    test_suite_id,
    monitor_id=None,
    table_name=None,
    lookback_override: int | None = None,
    lookback_multiplier: int = 1,
) -> tuple[str, dict]:
    """Build the lookback series SQL, scoped to one monitor (monitor_id) or one table.

    Returns rows oldest→newest. Pending runs (no matching result) yield a NULL result_id.

    For the table scope (``monitor_id is None``), the query CROSS JOINs the four monitor
    types and includes ``results.test_type`` in the SELECT so callers can route each row
    to its parser. ``lookback_multiplier`` scales the suite-configured lookback for the
    table scope (default 1, ignored for the monitor scope).
    """
    if monitor_id is not None:
        # Monitor scope: single definition LEFT JOIN, no type routing needed.
        lookback_expr = ":lookback_override" if lookback_override is not None else "COALESCE(test_suites.monitor_lookback, 1)"
        query = f"""
        WITH ranked_test_runs AS (
            SELECT test_runs.id, test_runs.test_starttime,
                   {lookback_expr} AS lookback,
                   ROW_NUMBER() OVER (ORDER BY test_runs.test_starttime DESC) AS position
            FROM test_suites
            INNER JOIN test_runs ON test_suites.id = test_runs.test_suite_id
            WHERE test_suites.id = :test_suite_id
        ),
        active_runs AS (
            SELECT id, test_starttime FROM ranked_test_runs WHERE position <= lookback
        )
        SELECT
            COALESCE(results.test_time, active_runs.test_starttime) AS test_time,
            results.id AS result_id,
            results.result_code,
            COALESCE(results.result_status, 'Log') AS result_status,
            results.result_signal,
            results.result_message,
            COALESCE(results.input_parameters, '') AS input_parameters,
            results.column_names,
            results.test_type
        FROM active_runs
        LEFT JOIN test_results AS results
            ON results.test_run_id = active_runs.id AND results.test_definition_id = :monitor_id
        ORDER BY active_runs.test_starttime ASC
        """
        params: dict = {"test_suite_id": str(test_suite_id), "monitor_id": str(monitor_id)}
        if lookback_override is not None:
            params["lookback_override"] = lookback_override
        return query, params

    # Table scope: CROSS JOIN over four monitor types, scaled lookback.
    if lookback_override is not None:
        lookback_expr = ":lookback_override"
    elif lookback_multiplier != 1:
        lookback_expr = "COALESCE(test_suites.monitor_lookback, 1) * :lookback_multiplier"
    else:
        lookback_expr = "COALESCE(test_suites.monitor_lookback, 1)"

    type_union = "\n        UNION ALL ".join(f"SELECT '{t}' AS test_type" for t in _TABLE_SCOPE_TYPES)
    query = f"""
    WITH ranked_test_runs AS (
        SELECT
            test_runs.id,
            test_runs.test_starttime,
            {lookback_expr} AS lookback,
            ROW_NUMBER() OVER (PARTITION BY test_runs.test_suite_id ORDER BY test_runs.test_starttime DESC) AS position
        FROM test_suites
        INNER JOIN test_runs
            ON (test_suites.id = test_runs.test_suite_id)
        WHERE test_suites.id = :test_suite_id
    ),
    active_runs AS (
        SELECT id, test_starttime FROM ranked_test_runs
        WHERE position <= lookback
    ),
    target_tests AS (
        {type_union}
    )
    SELECT
        COALESCE(results.test_time, active_runs.test_starttime) AS test_time,
        tt.test_type,
        results.id AS result_id,
        results.result_code,
        COALESCE(results.result_status, 'Log') AS result_status,
        results.result_signal,
        results.result_message,
        results.test_definition_id::TEXT AS test_definition_id,
        COALESCE(results.input_parameters, '') AS input_parameters,
        results.column_names
    FROM active_runs
    CROSS JOIN target_tests tt
    LEFT JOIN test_results AS results
        ON (
            results.test_run_id = active_runs.id
            AND results.test_type = tt.test_type
            AND results.table_name = :table_name
        )
    ORDER BY active_runs.test_starttime, tt.test_type;
    """
    params = {"test_suite_id": str(test_suite_id), "table_name": table_name}
    if lookback_override is not None:
        params["lookback_override"] = lookback_override
    elif lookback_multiplier != 1:
        params["lookback_multiplier"] = lookback_multiplier
    return query, params


@dataclass
class MonitorSeries:
    monitor_id: UUID
    type: str
    threshold_mode: ThresholdMode
    table_name: str
    column_name: str | None
    lookback: int
    is_training: bool
    bands: dict | None
    points: list[dict]


@dataclass
class Monitor:
    monitor_id: UUID
    test_type: str
    table_group_id: UUID
    table_name: str
    column_name: str | None
    history_calculation: str | None
    history_calculation_upper: str | None
    project_code: str
    test_suite_id: UUID
    monitor_lookback: int | None
    predict_sensitivity: str | None
    prediction: dict | None
    lower_tolerance: str | None
    upper_tolerance: str | None
    threshold_value: str | None

    @classmethod
    def get(cls, monitor_id: UUID) -> "Monitor | None":
        """Resolve a monitor by its public id. None when missing or not a monitor suite."""
        query = """
        SELECT
            td.id AS monitor_id, td.test_type, td.table_name, td.column_name,
            td.history_calculation, td.history_calculation_upper,
            td.prediction, td.lower_tolerance, td.upper_tolerance, td.threshold_value,
            ts.id AS test_suite_id, ts.project_code, ts.table_groups_id AS table_group_id,
            ts.monitor_lookback, ts.predict_sensitivity
        FROM test_definitions td
        INNER JOIN test_suites ts ON ts.id = td.test_suite_id
        WHERE td.id = :monitor_id AND ts.is_monitor IS TRUE
        """
        row = get_current_session().execute(text(query), {"monitor_id": str(monitor_id)}).mappings().first()
        return cls(**row) if row else None

    def series(self, *, lookback_override: int | None = None) -> MonitorSeries:
        query, params = build_series_sql(
            test_suite_id=self.test_suite_id, monitor_id=self.monitor_id, lookback_override=lookback_override,
        )
        rows = get_current_session().execute(text(query), params).mappings().all()
        parser = _PARSERS[self.test_type]
        points = [parser(dict(row)) for row in rows]
        # Rows are ordered oldest→newest; "training" is a property of the latest run only.
        # Old -1 rows linger in the lookback window long after the monitor starts predicting,
        # so any() would keep the header (and bands) stuck in training. Matches the dashboard's
        # per-monitor FILTER (WHERE position = 1) semantics.
        is_training = bool(points and points[-1].get("is_training"))
        bands = current_bands(
            self.test_type, self.history_calculation, self.prediction,
            self.predict_sensitivity or "medium", self.lower_tolerance, self.upper_tolerance, self.threshold_value,
            is_training=is_training,
        )
        threshold_mode, _lower, _upper = derive_threshold_mode(
            self.test_type, self.history_calculation, self.history_calculation_upper,
            self.lower_tolerance, self.upper_tolerance,
        )
        return MonitorSeries(
            monitor_id=self.monitor_id,
            type=self.test_type,
            threshold_mode=threshold_mode,
            table_name=self.table_name,
            column_name=self.column_name,
            lookback=self.monitor_lookback or 1,
            is_training=is_training,
            bands=bands,
            points=points,
        )
