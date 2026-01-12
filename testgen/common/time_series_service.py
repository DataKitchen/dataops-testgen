import pandas as pd
from darts import TimeSeries
from darts.models import ARIMA

DEFAULT_SAMPLES = 100


class NotEnoughData(ValueError):
    pass


# https://unit8co.github.io/darts/quickstart/00-quickstart.html#Training-forecasting-models-and-making-predictions
def get_arima_forecast(
    history: pd.DataFrame,
    num_forecast: int,
    quantiles: list[float],
    num_samples: int = DEFAULT_SAMPLES,
) -> pd.DataFrame:
    # https://unit8co.github.io/darts/generated_api/darts.models.forecasting.arima.html
    model = ARIMA()

    # Darts expects regular time series and cannot always infer frequency
    # Resample the data to get a regular time series
    datetimes = history.index.to_series()
    frequency = infer_frequency(datetimes)

    if (datetimes.max() - datetimes.min()) / pd.to_timedelta(frequency) < model.min_train_series_length:
        raise NotEnoughData(f"ARIMA needs at least {model.min_train_series_length} data points.")

    resampled_history = history.resample(frequency).mean().interpolate(method="linear")
    series = TimeSeries.from_dataframe(resampled_history)
    model.fit(series)
    forecast = model.predict(num_forecast, num_samples=num_samples, show_warnings=False)

    return forecast.to_dataframe().quantile(quantiles, axis=1).transpose()


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
