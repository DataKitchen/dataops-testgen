import logging
from datetime import datetime
from typing import ClassVar

from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    replace_params,
    write_to_app_db,
)
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.common.time_series_service import NotEnoughData, get_arima_forecast
from testgen.utils import to_dataframe, to_sql_timestamp

LOG = logging.getLogger("testgen")


class TestThresholdsPrediction:
    staging_table = "stg_test_definition_updates"
    staging_columns = (
        "test_suite_id",
        "test_definition_id",
        "run_date",
        "lower_tolerance",
        "upper_tolerance",
        "prediction",
    )
    num_forecast = 20
    quantile_map: ClassVar = {
        ("lower_tolerance", PredictSensitivity.low): 0,
        ("lower_tolerance", PredictSensitivity.medium): 0.2,
        ("lower_tolerance", PredictSensitivity.high): 0.4,
        "median": 0.5,
        ("upper_tolerance", PredictSensitivity.high): 0.6,
        ("upper_tolerance", PredictSensitivity.medium): 0.8,
        ("upper_tolerance", PredictSensitivity.low): 1,
    }

    def __init__(self, test_suite: TestSuite, run_date: datetime):
        self.test_suite = test_suite
        self.run_date = run_date

    def run(self) -> None:
        LOG.info("Retrieving historical test results for training prediction models")
        test_results = fetch_dict_from_db(*self._get_query("get_historical_test_results.sql"))
        if test_results:
            df = to_dataframe(test_results, coerce_float=True)
            grouped_dfs = df.groupby("test_definition_id", group_keys=False)

            LOG.info(f"Training prediction models for tests: {len(grouped_dfs)}")
            prediction_results = []
            for test_def_id, group in grouped_dfs:
                history = group[["test_time", "result_signal"]]
                history = history.set_index("test_time")

                test_prediction = [
                    self.test_suite.id,
                    test_def_id,
                    to_sql_timestamp(self.run_date),
                ]
                if len(history) >= (self.test_suite.predict_min_lookback or 1):
                    try:
                        forecast = get_arima_forecast(
                            history,
                            num_forecast=self.num_forecast,
                            quantiles=list(self.quantile_map.values()),
                        )

                        next_date = forecast.index[0]
                        sensitivity = self.test_suite.predict_sensitivity or PredictSensitivity.medium
                        test_prediction.extend([
                            forecast.at[next_date, self.quantile_map[("lower_tolerance", sensitivity)]],
                            forecast.at[next_date, self.quantile_map[("upper_tolerance", sensitivity)]],
                            forecast.to_json(),
                        ])
                    except NotEnoughData:
                        test_prediction.extend([None, None, None])
                else:
                    test_prediction.extend([None, None, None])

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
