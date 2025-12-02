import dataclasses
import re
from uuid import UUID

from testgen.commands.queries.refresh_data_chars_query import ColumnChars
from testgen.common import read_template_sql_file, read_template_yaml_file
from testgen.common.database.database_service import replace_params
from testgen.common.models.connection import Connection
from testgen.common.models.profiling_run import ProfilingRun
from testgen.common.models.table_group import TableGroup
from testgen.common.read_file import replace_templated_functions


@dataclasses.dataclass
class TableSampling:
    table_name: str
    sample_count: int
    sample_ratio: float
    sample_percent: float


@dataclasses.dataclass
class HygieneIssueType:
    id: str
    anomaly_type: str
    data_object: str
    anomaly_criteria: str
    detail_expression: str
    dq_score_prevalence_formula: str
    dq_score_risk_factor: str


class ProfilingSQL:

    profiling_results_table = "profile_results"
    frequency_staging_table = "stg_secondary_profile_updates"
    error_columns = (
        "project_code",
        "connection_id",
        "table_groups_id",
        "schema_name",
        "profile_run_id",
        "run_date",
        "table_name",
        "column_name",
        "position",
        "column_type",
        "general_type",
        "db_data_type",
        "record_ct",
        "query_error",
    )

    max_pattern_length = 25
    max_error_length = 2000

    def __init__(self, connection: Connection, table_group: TableGroup, profiling_run: ProfilingRun):
        self.connection = connection
        self.table_group = table_group
        self.profiling_run = profiling_run
        self.run_date = profiling_run.profiling_starttime.strftime("%Y-%m-%d %H:%M:%S")
        self.flavor = connection.sql_flavor
        self._profiling_template: dict = None

    def _get_params(self, column_chars: ColumnChars | None = None, table_sampling: TableSampling | None = None) -> dict:
        params = {
            "PROJECT_CODE": self.table_group.project_code,
            "CONNECTION_ID": self.connection.connection_id,
            "TABLE_GROUPS_ID": self.table_group.id,
            "PROFILE_RUN_ID": self.profiling_run.id,
            "RUN_DATE": self.run_date,
            "SQL_FLAVOR": self.flavor,
            "DATA_SCHEMA": self.table_group.table_group_schema,
            "PROFILE_ID_COLUMN_MASK": self.table_group.profile_id_column_mask,
            "PROFILE_SK_COLUMN_MASK": self.table_group.profile_sk_column_mask,
            "MAX_PATTERN_LENGTH": self.max_pattern_length,
        }
        if column_chars:
            params.update({
                "DATA_TABLE": column_chars.table_name,
                "COL_NAME": column_chars.column_name,
                "COL_NAME_SANITIZED": column_chars.column_name.replace("'", "''"),
                "COL_GEN_TYPE": column_chars.general_type,
                "COL_TYPE": column_chars.column_type,
                "DB_DATA_TYPE": column_chars.db_data_type,
                "COL_POS": column_chars.ordinal_position,
            })
        if table_sampling:
            params.update({
                "SAMPLING_TABLE": table_sampling.table_name,
                "SAMPLE_SIZE": table_sampling.sample_count,
                "PROFILE_SAMPLE_RATIO": table_sampling.sample_ratio,
                "SAMPLE_PERCENT_CALC": table_sampling.sample_percent,
            })
        return params

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "profiling",
        extra_params: dict | None = None,
        column_chars: ColumnChars | None = None,
        table_sampling: TableSampling | None = None,
    ) -> tuple[str | None, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {}

        if query:
            query = self._process_conditionals(query, extra_params)
            params.update(self._get_params(column_chars, table_sampling))
            if extra_params:
                params.update(extra_params)

            query = replace_params(query, params)
            query = replace_templated_functions(query, self.flavor)

        return query, params

    def _process_conditionals(self, query: str, extra_params: dict | None = None) -> str:
        re_pattern = re.compile(r"^--\s+TG-(IF|ELSE|ENDIF)(?:\s+(\w+))?\s*$")
        condition = None
        updated_query = []
        for line in query.splitlines(True):
            if re_match := re_pattern.match(line):
                match re_match.group(1):
                    case "IF" if condition is None and (variable := re_match.group(2)) is not None:
                        result = extra_params.get(variable)
                        if result is None:
                            result = getattr(self, variable, None)
                        condition = bool(result)
                    case "ELSE" if condition is not None:
                        condition = not condition
                    case "ENDIF" if condition is not None:
                        condition = None
                    case _:
                        raise ValueError("Template conditional misused")
            elif condition is not False:
                updated_query.append(line)

        if condition is not None:
            raise ValueError("Template conditional misused")

        return "".join(updated_query)

    def _get_profiling_template(self) -> dict:
        if not self._profiling_template:
            self._profiling_template = read_template_yaml_file(
                "project_profiling_query.yaml",
                sub_directory=f"flavors/{self.flavor}/profiling",
            )
        return self._profiling_template

    def get_frequency_analysis_columns(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("secondary_profiling_columns.sql")

    def update_frequency_analysis_results(self) -> list[tuple[str, dict]]:
        # Runs on App database
        return [
            self._get_query("secondary_profiling_update.sql"),
            self._get_query("secondary_profiling_delete.sql"),
        ]

    def update_profiling_results(self) -> list[tuple[str, dict]]:
        # Runs on App database
        queries = [
            self._get_query("datatype_suggestions.sql"),
            self._get_query("functional_datatype.sql"),
            self._get_query("functional_tabletype_stage.sql"),
            self._get_query("functional_tabletype_update.sql"),
            self._get_query("pii_flag.sql"),
        ]
        if self.table_group.profile_flag_cdes:
            queries.append(self._get_query("cde_flagger_query.sql"))
        return queries

    def update_hygiene_issue_counts(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("refresh_anomalies.sql")

    def get_hygiene_issue_types(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("profile_anomaly_types_get.sql")

    def detect_hygiene_issue(self, issue_type: HygieneIssueType) -> tuple[str, dict] | None:
        # Runs on App database
        extra_params = {
            "ANOMALY_ID": issue_type.id,
            "DETAIL_EXPRESSION": issue_type.detail_expression,
            "ANOMALY_CRITERIA": issue_type.anomaly_criteria,
        }

        match issue_type.data_object:
            case "Column":
                query, params = self._get_query("profile_anomalies_screen_column.sql", extra_params=extra_params)
            case "Multi-Col":
                query, params = self._get_query("profile_anomalies_screen_multi_column.sql", extra_params=extra_params)
            case "Dates":
                query, params = self._get_query("profile_anomalies_screen_table_dates.sql", extra_params=extra_params)
            case "Table":
                query, params = self._get_query("profile_anomalies_screen_table.sql", extra_params=extra_params)
            case "Variant":
                query, params = self._get_query("profile_anomalies_screen_variants.sql", extra_params=extra_params)
            case _:
                return None

        return query, params

    def update_hygiene_issue_prevalence(self, issue_type: HygieneIssueType) -> tuple[str, dict]:
        # Runs on App database
        query = read_template_sql_file("profile_anomaly_scoring.sql", sub_directory="profiling")
        params = {
            "PROFILE_RUN_ID": self.profiling_run.id,
            "ANOMALY_ID": issue_type.id,
            "PREV_FORMULA": issue_type.dq_score_prevalence_formula,
            "RISK": issue_type.dq_score_risk_factor,
        }
        query = replace_params(query, params)
        return query, params

    def run_column_profiling(self, column_chars: ColumnChars, table_sampling: TableSampling | None = None) -> tuple[str, dict]:
        # Runs on Target database
        template = self._get_profiling_template()
        general_type = column_chars.general_type

        query = ""
        query += template["01_sampling" if table_sampling else "01_else"]
        query += template["01_all"]
        query += template["02_X" if general_type == "X" else "02_else"]
        query += template["03_ADN" if general_type in ["A", "D", "N"] else "03_else"]

        if general_type == "A":
            query += template["04_A"]
        elif general_type == "N":
            query += template["04_N"]
        else:
            query += template["04_else"]

        query += template["05_A" if general_type == "A" else "05_else"]
        query += template["06_A" if general_type == "A" else "06_else"]
        query += template["08_N" if general_type == "N" else "08_else"]
        query += template["10_N_dec" if general_type == "N" and column_chars.is_decimal == True else "10_else"]
        query += template["11_D" if general_type == "D" else "11_else"]
        query += template["12_B" if general_type == "B" else "12_else"]
        query += template["14_A" if general_type == "A" else "14_else"]
        query += template["16_all"]
        query += template["98_all"]

        if general_type == "N":
            query += template["99_N_sampling" if table_sampling else "99_N"]
        else:
            query += template["99_else"]

        params = self._get_params(column_chars, table_sampling)
        query = replace_params(query, params)
        query = replace_templated_functions(query, self.flavor)

        return query, params

    def get_profiling_errors(self, column_errors: list[tuple[ColumnChars, str]]) -> list[list[str | UUID | int]]:
        return [
            [
                self.table_group.project_code,
                self.connection.connection_id,
                self.table_group.id,
                self.table_group.table_group_schema,
                self.profiling_run.id,
                self.profiling_run.profiling_starttime,
                column_chars.table_name,
                column_chars.column_name.replace("'", "''"),
                column_chars.ordinal_position,
                column_chars.column_type,
                "X",
                column_chars.db_data_type,
                column_chars.record_ct,
                error[:self.max_error_length],
            ] for column_chars, error in column_errors
        ]

    def run_frequency_analysis(self, column_chars: ColumnChars, table_sampling: TableSampling | None = None) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query(
            "project_secondary_profiling_query.sql",
            f"flavors/{self.flavor}/profiling",
            extra_params={"do_sample_bool": table_sampling is not None},
            column_chars=column_chars,
            table_sampling=table_sampling,
        )

    def update_sampled_profiling_results(self, table_sampling: TableSampling) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("project_update_profile_results_to_estimates.sql", table_sampling=table_sampling)
