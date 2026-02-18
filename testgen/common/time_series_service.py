import logging
from datetime import datetime

import holidays
import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

LOG = logging.getLogger("testgen")

# This is a heuristic minimum to get a reasonable prediction
# Not a hard limit of the model
MIN_TRAIN_VALUES = 20


class NotEnoughData(ValueError):
    pass


def get_sarimax_forecast(
    history: pd.DataFrame,
    num_forecast: int,
    exclude_weekends: bool = False,
    holiday_codes: list[str] | None = None,
    tz: str | None = None,
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

    # Return value
    Returns a Pandas dataframe with forecast DatetimeIndex, "mean" column, and "se" (standard error) column.
    """
    if len(history) < MIN_TRAIN_VALUES:
        raise NotEnoughData("Not enough data points in history.")

    # statsmodels requires DatetimeIndex with a regular frequency
    # Resample the data to get a regular time series
    datetimes = history.index.to_series()
    frequency = infer_frequency(datetimes)
    resampled_history = history.resample(frequency).mean().interpolate(method="linear")

    if len(resampled_history) < MIN_TRAIN_VALUES:
        raise NotEnoughData("Not enough data points after resampling.")

    # Generate DatetimeIndex with future dates
    forecast_start = resampled_history.index[-1] + pd.to_timedelta(frequency)
    forecast_index = pd.date_range(start=forecast_start, periods=num_forecast, freq=frequency)

    # Detect holidays in entire date range
    holiday_dates = None
    if holiday_codes:
        all_dates_index = resampled_history.index.append(forecast_index)
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

    exog_train = get_exog_flags(resampled_history.index)

    # When seasonal_order is not specified, this is effectively the ARIMAX model
    model = SARIMAX(
        resampled_history.iloc[:, 0],
        exog=exog_train,
        # This is a good starting point according to Gemini - tune if needed
        order=(1, 1, 1),
        # Prevent model from crashing when it encounters noisy/non-standard data
        enforce_stationarity=False,
        enforce_invertibility=False
    )
    fitted_model = model.fit(disp=False)

    forecast_index = pd.date_range(
        start=resampled_history.index[-1] + pd.to_timedelta(frequency),
        periods=num_forecast,
        freq=frequency
    )
    exog_forecast = get_exog_flags(forecast_index)
    forecast = fitted_model.get_forecast(steps=num_forecast, exog=exog_forecast)

    results = pd.DataFrame(index=forecast_index)
    results["mean"] = forecast.predicted_mean
    results["se"] = forecast.var_pred_mean ** 0.5
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


def get_holiday_dates(holiday_codes: list[str], datetime_index: pd.DatetimeIndex) -> set[datetime]:
    years = list(range(datetime_index.year.min(), datetime_index.year.max() + 1))

    holiday_dates = set()
    if holiday_codes:
        for code in holiday_codes:
            code = code.strip().upper()
            found = False

            try:
                country_holidays = holidays.country_holidays(code, years=years)
                holiday_dates.update(country_holidays.keys())
                found = True
            except NotImplementedError:
                pass # Not a valid country code

            if not found:
                try:
                    financial_holidays = holidays.financial_holidays(code, years=years)
                    holiday_dates.update(financial_holidays.keys())
                    found = True
                except NotImplementedError:
                    pass # Not a valid financial code

            if not found:
                LOG.warning(f"Holiday code '{code}' could not be resolved as a country or financial market")

    return holiday_dates
