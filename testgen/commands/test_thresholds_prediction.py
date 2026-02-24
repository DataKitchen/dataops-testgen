import json
import logging
from datetime import datetime

import pandas as pd
from scipy import stats

from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    replace_params,
    write_to_app_db,
)
from testgen.common.freshness_service import (
    get_freshness_gap_threshold,
    infer_schedule,
    minutes_to_next_deadline,
    resolve_holiday_dates,
)
from testgen.common.models import with_database_session
from testgen.common.models.scheduler import JobSchedule
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.common.time_series_service import (
    NotEnoughData,
    get_sarimax_forecast,
)
from testgen.utils import to_dataframe, to_sql_timestamp

LOG = logging.getLogger("testgen")

NUM_FORECAST = 10
T_DISTRIBUTION_THRESHOLD = 20

Z_SCORE_MAP = {
    ("lower_tolerance", PredictSensitivity.low): -3.0,    # 0.13th percentile
    ("lower_tolerance", PredictSensitivity.medium): -2.5,  # 0.62nd percentile
    ("lower_tolerance", PredictSensitivity.high): -2.0,    # 2.3rd percentile
    ("upper_tolerance", PredictSensitivity.high): 2.0,     # 97.7th percentile
    ("upper_tolerance", PredictSensitivity.medium): 2.5,   # 99.4th percentile
    ("upper_tolerance", PredictSensitivity.low): 3.0,      # 99.87th percentile
}

FRESHNESS_THRESHOLD_MAP = {
    #                        upper_pct  floor_mult  lower_pct
    PredictSensitivity.high: (80,       1.0,        20),
    PredictSensitivity.medium: (95,     1.25,       10),
    PredictSensitivity.low: (99,        1.5,        5),
}

SCHEDULE_DEADLINE_BUFFER_HOURS = {
    PredictSensitivity.high: 1.5,
    PredictSensitivity.medium: 3.0,
    PredictSensitivity.low: 5.0,
}

STALENESS_FACTOR_MAP = {
    PredictSensitivity.high: 0.75,
    PredictSensitivity.medium: 0.85,
    PredictSensitivity.low: 0.95,
}


class TestThresholdsPrediction:
    staging_table = "stg_test_definition_updates"
    staging_columns = (
        "test_suite_id",
        "test_definition_id",
        "run_date",
        "lower_tolerance",
        "upper_tolerance",
        "threshold_value",
        "prediction",
    )

    @with_database_session
    def __init__(self, test_suite: TestSuite, run_date: datetime):
        self.test_suite = test_suite
        self.run_date = run_date
        schedule = JobSchedule.get(JobSchedule.kwargs["test_suite_id"].astext == str(test_suite.id))
        self.tz = schedule.cron_tz or "UTC" if schedule else None

    def run(self) -> None:
        LOG.info("Retrieving historical test results for training prediction models")
        test_results = fetch_dict_from_db(*self._get_query("get_historical_test_results.sql"))
        if test_results:
            df = to_dataframe(test_results, coerce_float=True)
            grouped_dfs = df.groupby("test_definition_id", group_keys=False)

            LOG.info(f"Training prediction models for tests: {len(grouped_dfs)}")
            prediction_results = []
            for test_def_id, group in grouped_dfs:
                test_type = group["test_type"].iloc[0]
                history = group[["test_time", "result_signal"]]
                history = history.set_index("test_time")

                test_prediction = [
                    self.test_suite.id,
                    test_def_id,
                    to_sql_timestamp(self.run_date),
                ]
                if test_type == "Freshness_Trend":
                    lower, upper, staleness, prediction = compute_freshness_threshold(
                        history,
                        sensitivity=self.test_suite.predict_sensitivity or PredictSensitivity.medium,
                        min_lookback=self.test_suite.predict_min_lookback or 1,
                        exclude_weekends=self.test_suite.predict_exclude_weekends,
                        holiday_codes=self.test_suite.holiday_codes_list,
                        schedule_tz=self.tz,
                    )
                    test_prediction.extend([lower, upper, staleness, prediction])
                else:
                    lower, upper, prediction = compute_sarimax_threshold(
                        history,
                        sensitivity=self.test_suite.predict_sensitivity or PredictSensitivity.medium,
                        min_lookback=self.test_suite.predict_min_lookback or 1,
                        exclude_weekends=self.test_suite.predict_exclude_weekends,
                        holiday_codes=self.test_suite.holiday_codes_list,
                        schedule_tz=self.tz,
                    )
                    if test_type == "Volume_Trend":
                        if lower is not None: 
                            lower = max(lower, 0.0)
                        if upper is not None:
                            upper = max(upper, 0.0)
                    test_prediction.extend([lower, upper, None, prediction])

                prediction_results.append(test_prediction)

            LOG.info("Writing predicted test thresholds to staging")
            write_to_app_db(prediction_results, self.staging_columns, self.staging_table)

            LOG.info("Updating predicted test thresholds and deleting staging")
            execute_db_queries([
                self._get_query("update_predicted_test_thresholds.sql"),
                self._get_query("delete_staging_test_definitions.sql"),
            ])

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "prediction",
    ) -> tuple[str, dict]:
        params = {
            "TEST_SUITE_ID": self.test_suite.id,
            "RUN_DATE": to_sql_timestamp(self.run_date),
        }
        query = read_template_sql_file(template_file_name, sub_directory)
        query = replace_params(query, params)
        return query, params


def compute_freshness_threshold(
    history: pd.DataFrame,
    sensitivity: PredictSensitivity,
    min_lookback: int = 1,
    exclude_weekends: bool = False,
    holiday_codes: list[str] | None = None,
    schedule_tz: str | None = None,
) -> tuple[float | None, float | None, float | None, str | None]:
    """Compute freshness gap thresholds in business minutes.

    Returns (lower, upper, staleness_threshold, prediction_json) in business minutes,
    or (None, None, None, None) if not enough data.
    """
    if len(history) < min_lookback:
        return None, None, None, None

    upper_percentile, floor_multiplier, lower_percentile = FRESHNESS_THRESHOLD_MAP[sensitivity]
    staleness_factor = STALENESS_FACTOR_MAP[sensitivity]

    try:
        result = get_freshness_gap_threshold(
            history,
            upper_percentile=upper_percentile,
            floor_multiplier=floor_multiplier,
            lower_percentile=lower_percentile,
            exclude_weekends=exclude_weekends,
            holiday_codes=holiday_codes,
            tz=schedule_tz,
            staleness_factor=staleness_factor,
        )
    except NotEnoughData:
        return None, None, None, None

    lower, upper = result.lower, result.upper
    staleness: float | None = None
    prediction_data: dict = {}

    if not schedule_tz:
        return lower, upper, staleness, json.dumps(prediction_data)

    # --- Schedule inference ---
    deadline_buffer = SCHEDULE_DEADLINE_BUFFER_HOURS[sensitivity]

    schedule = infer_schedule(history, schedule_tz)
    if not schedule:
        return lower, upper, staleness, json.dumps(prediction_data)

    prediction_data.update({
        "schedule_stage": schedule.stage,
        "frequency": schedule.frequency,
        "active_days": sorted(schedule.active_days) if schedule.active_days else None,
        "window_start": schedule.window_start,
        "window_end": schedule.window_end,
        # Metadata stored for debugging purposes
        "confidence": round(schedule.confidence, 4),
        "num_events": schedule.num_events,
        "sensitivity": sensitivity.value,
        "deadline_buffer_hours": deadline_buffer,
    })

    if schedule.stage == "active":
        excluded_days = frozenset(range(7)) - schedule.active_days if schedule.active_days else None

        # For sub-daily schedules, apply window exclusion for overnight gaps
        has_window = (
            schedule.frequency == "sub_daily"
            and schedule.window_start is not None
            and schedule.window_end is not None
        )

        # Recompute gap thresholds with schedule-aware exclusion
        if excluded_days or has_window:
            try:
                result = get_freshness_gap_threshold(
                    history,
                    upper_percentile=upper_percentile,
                    floor_multiplier=floor_multiplier,
                    lower_percentile=lower_percentile,
                    exclude_weekends=exclude_weekends,
                    holiday_codes=holiday_codes,
                    tz=schedule_tz,
                    staleness_factor=staleness_factor,
                    excluded_days=excluded_days,
                    window_start=schedule.window_start if has_window else None,
                    window_end=schedule.window_end if has_window else None,
                )
                lower, upper = result.lower, result.upper
                staleness = result.staleness
            except NotEnoughData:
                pass  # Keep first-pass thresholds

        # Override upper threshold with schedule-based deadline (daily/weekly only)
        if schedule.frequency != "sub_daily":
            holiday_dates = resolve_holiday_dates(holiday_codes, history.index) if holiday_codes else None
            schedule_upper = minutes_to_next_deadline(
                result.last_update, schedule,
                exclude_weekends, holiday_dates, schedule_tz,
                deadline_buffer, excluded_days=excluded_days,
            )
            if schedule_upper is not None:
                upper = schedule_upper

    return lower, upper, staleness, json.dumps(prediction_data)


def compute_sarimax_threshold(
    history: pd.DataFrame,
    sensitivity: PredictSensitivity,
    num_forecast: int = NUM_FORECAST,
    min_lookback: int = 1,
    exclude_weekends: bool = False,
    holiday_codes: list[str] | None = None,
    schedule_tz: str | None = None,
) -> tuple[float | None, float | None, str | None]:
    """Compute SARIMAX-based thresholds for the next forecast point.

    Returns (lower, upper, forecast_json) or (None, None, None) if insufficient data.
    """
    if len(history) < min_lookback:
        return None, None, None

    try:
        forecast = get_sarimax_forecast(
            history,
            num_forecast=num_forecast,
            exclude_weekends=exclude_weekends,
            holiday_codes=holiday_codes,
            tz=schedule_tz,
        )

        num_points = len(history)
        for key, z_score in Z_SCORE_MAP.items():
            if num_points < T_DISTRIBUTION_THRESHOLD:
                percentile = stats.norm.cdf(z_score)
                multiplier = stats.t.ppf(percentile, df=num_points - 1)
            else:
                multiplier = z_score
            column = f"{key[0]}|{key[1].value}"
            forecast[column] = forecast["mean"] + (multiplier * forecast["se"])

        next_date = forecast.index[0]
        lower_tolerance = forecast.at[next_date, f"lower_tolerance|{sensitivity.value}"]
        upper_tolerance = forecast.at[next_date, f"upper_tolerance|{sensitivity.value}"]

        if pd.isna(lower_tolerance) or pd.isna(upper_tolerance):
            return None, None, None
        else:
            return float(lower_tolerance), float(upper_tolerance), forecast.to_json()
    except NotEnoughData:
        return None, None, None
