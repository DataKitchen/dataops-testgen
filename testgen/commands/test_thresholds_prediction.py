import logging
from datetime import datetime
from typing import ClassVar

import pandas as pd

from testgen.common.database.database_service import (
    execute_db_queries,
    fetch_dict_from_db,
    replace_params,
    write_to_app_db,
)
from testgen.common.models.test_suite import PredictSensitivity, TestSuite
from testgen.common.read_file import read_template_sql_file
from testgen.common.time_series_service import NotEnoughData, get_sarimax_forecast
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
    num_forecast = 10
    # https://www.pindling.org/Math/Learning/Statistics/z_scores_table.htm
    z_score_map: ClassVar = {
        ("lower_tolerance", PredictSensitivity.low): -1.645, # 5th percentile
        ("lower_tolerance", PredictSensitivity.medium): -0.842, # 20th percentile
        ("lower_tolerance", PredictSensitivity.high): -0.253, # 40th percentile
        ("upper_tolerance", PredictSensitivity.high): 0.253, # 60th percentile
        ("upper_tolerance", PredictSensitivity.medium): 0.842, # 80th percentile
        ("upper_tolerance", PredictSensitivity.low): 1.645, # 95th percentile
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
                        forecast = get_sarimax_forecast(
                            history,
                            num_forecast=self.num_forecast,
                            exclude_weekends=self.test_suite.predict_exclude_weekends,
                            holiday_codes=[
                                code.strip() for code in self.test_suite.predict_holiday_codes.split(",")
                            ] if self.test_suite.predict_holiday_codes else None,
                        )

                        for key, z_score in self.z_score_map.items():
                            column = f"{key[0]}|{key[1].value}"
                            forecast[column] = forecast["mean"] + (z_score * forecast["se"])

                        next_date = forecast.index[0]
                        sensitivity = self.test_suite.predict_sensitivity or PredictSensitivity.medium
                        lower_tolerance = forecast.at[next_date, f"lower_tolerance|{sensitivity.value}"]
                        upper_tolerance = forecast.at[next_date, f"upper_tolerance|{sensitivity.value}"]

                        if pd.isna(lower_tolerance) or pd.isna(upper_tolerance):
                            test_prediction.extend([None, None, None])
                        else:
                            test_prediction.extend([lower_tolerance, upper_tolerance, forecast.to_json()])
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
