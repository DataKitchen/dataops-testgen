# UNUSED CODE - TO BE REVIVED LATER

import dataclasses
from uuid import UUID

from testgen.common import read_template_sql_file
from testgen.common.database.database_service import quote_csv_items, replace_params


@dataclasses.dataclass
class ContingencyTable:
    schema_name: str
    table_name: str
    contingency_columns: str


class ContingencySQL:

    contingency_max_values = 6

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "contingency",
        params: dict | None = None,
    ) -> tuple[str | None, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        query = replace_params(query, params or {})

        return query, params

    def get_contingency_columns(self, profiling_run_id: UUID) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query(
            "contingency_columns.sql",
            params={
                "PROFILE_RUN_ID": profiling_run_id,
                "CONTINGENCY_MAX_VALUES": self.contingency_max_values,
            },
        )

    def get_contingency_counts(self, contingency_table: ContingencyTable) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query(
            "contingency_counts.sql",
            params={
                "DATA_SCHEMA": contingency_table.schema_name,
                "DATA_TABLE": contingency_table.table_name,
                "CONTINGENCY_COLUMNS": quote_csv_items(contingency_table.contingency_columns),
            },
        )
