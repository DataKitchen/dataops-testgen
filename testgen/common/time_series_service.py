import logging

import numpy as np
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from testgen.common.holiday_service import get_holiday_dates

LOG = logging.getLogger("testgen")

# This is a heuristic minimum to get a reasonable prediction
# Not a hard limit of the model
MIN_TRAIN_VALUES = 8


class NotEnoughData(ValueError):
    pass


def get_sarimax_forecast(
    history: pd.DataFrame,
    num_forecast: int,
    exclude_weekends: bool = False,
    holiday_codes: list[str] | None = None,
    tz: str | None = None,
    event_space: bool = False,
) -> pd.DataFrame:
    """
    # Parameters
    :param history: Pandas dataframe containing time series data to be used for training the model.
                    It must have a DatetimeIndex and a column with the historical values.
                    Only the first column will be used for the model.
    :param num_forcast: Number of values to predict in the future.
    :param exclude_weekends: Whether weekends should be considered exogenous when training the model and forecasting.
    :param holiday_codes: List of country or financial market codes defining holidays to be considered exogenous when training the model and forecasting.
    :param tz: IANA timezone (e.g. "America/New_York") for day-of-week/holiday checks. Naive timestamps are treated as UTC and converted to this timezone before determining weekday/holiday status.
    :param event_space: When False (default), resample the series onto a regular calendar grid and
                    linearly interpolate gaps before fitting — appropriate for series sampled at a
                    steady cadence, and where weekend/holiday exogenous flags apply. When True, fit
                    in event-space: one model step per observation, no interpolation, no calendar
                    exog. Required for irregularly-spaced series (e.g. the freshness-update points of
                    a refresh-driven table) where interpolation would smooth multi-period jumps into
                    small uniform increments and collapse the very jump variance the forecast must
                    capture.

    # Return value
    Returns a Pandas dataframe with forecast DatetimeIndex, "mean" column, and "se" (standard error) column.
    """
    if len(history) < MIN_TRAIN_VALUES:
        raise NotEnoughData("Not enough data points in history.")

    if event_space:
        # Event-space: one step per observation. Map the values onto a synthetic regular grid
        # stepped by the median observed interval, so forecast timestamps remain realistic while
        # the model sees each observation as a single step (no interpolated points between them).
        median_step = history.index.to_series().diff().median()
        if pd.isna(median_step) or median_step <= pd.Timedelta(0):
            median_step = pd.Timedelta(days=1)
        step = median_step
        synthetic_index = pd.date_range(end=history.index[-1], periods=len(history), freq=step)
        train_history = pd.DataFrame(history.iloc[:, 0].values, index=synthetic_index, columns=[history.columns[0]])
    else:
        # statsmodels requires DatetimeIndex with a regular frequency
        # Resample the data to get a regular time series
        datetimes = history.index.to_series()
        frequency = infer_frequency(datetimes)
        train_history = history.resample(frequency).mean().interpolate(method="linear")
        if len(train_history) < MIN_TRAIN_VALUES:
            raise NotEnoughData("Not enough data points after resampling.")
        step = pd.to_timedelta(frequency)

    # Generate DatetimeIndex with future dates
    forecast_index = pd.date_range(start=train_history.index[-1] + step, periods=num_forecast, freq=step)

    # Detect holidays in entire date range (calendar-aware path only)
    holiday_dates = None
    if not event_space and holiday_codes:
        all_dates_index = train_history.index.append(forecast_index)
        holiday_dates = get_holiday_dates(holiday_codes, all_dates_index)

    def get_exog_flags(index: pd.DatetimeIndex) -> pd.DataFrame:
        exog = pd.DataFrame(index=index)
        exog["is_excluded"] = 0
        # Use local timezone for day-of-week and holiday checks when available
        check_index = index.tz_localize("UTC").tz_convert(tz) if tz else index
        if exclude_weekends:
            # .dayofweek: 5=Saturday, 6=Sunday
            exog.loc[check_index.dayofweek >= 5, "is_excluded"] = 1
        if holiday_dates:
            exog.loc[pd.Index(check_index.date).isin(holiday_dates), "is_excluded"] = 1
        return exog

    # Calendar exogenous flags only apply when fitting against real calendar time.
    exog_train = None if event_space else get_exog_flags(train_history.index)
    exog_forecast = None if event_space else get_exog_flags(forecast_index)

    # When seasonal_order is not specified, this is effectively the ARIMAX model
    model = SARIMAX(
        train_history.iloc[:, 0],
        exog=exog_train,
        # This is a good starting point according to Gemini - tune if needed
        order=(1, 1, 1),
        # Prevent model from crashing when it encounters noisy/non-standard data
        enforce_stationarity=False,
        enforce_invertibility=False
    )
    fitted_model = model.fit(disp=False)

    forecast = fitted_model.get_forecast(steps=num_forecast, exog=exog_forecast)

    results = pd.DataFrame(index=forecast_index)
    results["mean"] = forecast.predicted_mean

    # SE estimation: take the max of three sources to prevent overconfident bounds.
    # 1. Model SE (var_pred_mean): can be artificially small when AR/MA nearly cancel
    # 2. Residual SE: the model's actual 1-step prediction errors (after Kalman burn-in)
    # 3. Raw diff SE: std of first-differences of the original data — captures inherent
    #    point-to-point variability that the model may underestimate
    model_se = forecast.var_pred_mean ** 0.5
    order_sum = model.k_ar + model.k_diff + model.k_ma
    burn_in = max(order_sum, 3)
    usable_residuals = fitted_model.resid.iloc[burn_in:]
    resid_se = usable_residuals.std() if len(usable_residuals) >= 5 else 0.0
    raw_diffs = np.diff(history.iloc[:, 0].values)
    raw_diff_se = np.std(raw_diffs, ddof=1) if len(raw_diffs) > 1 else 0.0
    results["se"] = np.maximum(model_se, max(resid_se, raw_diff_se))

    return results


def infer_frequency(datetime_series: pd.Series) -> str:
    # Calculate the median frequency
    time_diffs = datetime_series.diff().dropna()
    median_diff = time_diffs.median()

    total_seconds = median_diff.total_seconds()

    # Close to an integer number of days
    days = total_seconds / 86400
    nearest_day = round(days)
    if nearest_day >= 1 and abs(days - nearest_day) / nearest_day < 0.05:
        return f"{int(nearest_day)}D"

    # Close to an integer number of hours
    hours = total_seconds / 3600
    nearest_hour = round(hours)
    if nearest_hour > 0 and abs(hours - nearest_hour) / nearest_hour < 0.05:
        return f"{int(nearest_hour)}h"

    # Fallback to minutes or seconds
    frequency = f"{int(total_seconds // 60)}min"
    return frequency if frequency != "0min" else f"{int(total_seconds)}S"


