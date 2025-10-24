import dataclasses
from collections.abc import Iterable
from datetime import datetime

from testgen.common import read_template_sql_file
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.utils import chunk_queries


@dataclasses.dataclass
class ColumnChars:
    schema_name: str
    table_name: str
    column_name: str
    ordinal_position: int = None
    general_type: str = None
    column_type: str = None
    db_data_type: str = None
    is_decimal: bool = False
    approx_record_ct: int = None
    record_ct: int = None


class RefreshDataCharsSQL:

    staging_table = "stg_data_chars_updates"
    staging_columns = (
        "table_groups_id",
        "run_date",
        "schema_name",
        "table_name",
        "column_name",
        "position",
        "general_type",
        "column_type",
        "db_data_type",
        "approx_record_ct",
        "record_ct",
    )

    def __init__(self, connection: Connection, table_group: TableGroup):
        self.connection = connection
        self.table_group = table_group
        self.flavor = connection.sql_flavor
        self.flavor_service = get_flavor_service(self.flavor)

    def _get_query(
        self,
        template_file_name: str,
        sub_directory: str | None = "data_chars",
        extra_params: dict | None = None,
    ) -> tuple[str, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "DATA_SCHEMA": self.table_group.table_group_schema,
            "TABLE_GROUPS_ID": self.table_group.id,
        }
        if extra_params:
            params.update(extra_params)
        query = replace_params(query, params)
        return query, params

    def _get_table_criteria(self) -> str:
        table_criteria = ""
        ddf_table_ref = self.flavor_service.ddf_table_ref
        escaped_underscore = self.flavor_service.escaped_underscore
        escape_clause = self.flavor_service.escape_clause

        if self.table_group.profiling_table_set:
            quoted_table_names = ",".join(
                [f"'{item.strip()}'" for item in self.table_group.profiling_table_set.split(",")]
            )
            table_criteria += f" AND c.{ddf_table_ref} IN ({quoted_table_names})"

        if self.table_group.profiling_include_mask:
            include_table_names = [
                item.strip().replace("_", escaped_underscore)
                for item in self.table_group.profiling_include_mask.split(",")
            ]
            table_criteria += f"""
            AND (
                {" OR ".join([ f"(c.{ddf_table_ref} LIKE '{item}' {escape_clause})" for item in include_table_names ])}
            )
            """

        if self.table_group.profiling_exclude_mask:
            exclude_table_names = [
                item.strip().replace("_", escaped_underscore)
                for item in self.table_group.profiling_exclude_mask.split(",")
            ]
            table_criteria += f"""
            AND NOT (
                {" OR ".join([ f"(c.{ddf_table_ref} LIKE '{item}' {escape_clause})" for item in exclude_table_names ])}
            )
            """

        return table_criteria
    
    def get_schema_ddf(self) -> tuple[str, dict]:
        # Runs on Target database
        return self._get_query(
            "get_schema_ddf.sql",
            f"flavors/{self.flavor}/data_chars",
            extra_params={"TABLE_CRITERIA": self._get_table_criteria()},
        )
    
    def get_row_counts(self, table_names: Iterable[str]) -> list[tuple[str, None]]:
        # Runs on Target database
        schema = self.table_group.table_group_schema
        quote = self.flavor_service.quote_character
        count_queries = [
            f"SELECT '{table}', COUNT(*) FROM {quote}{schema}{quote}.{quote}{table}{quote}"
            for table in table_names
        ]
        chunked_queries = chunk_queries(count_queries, " UNION ALL ", self.connection.max_query_chars)
        return [ (query, None) for query in chunked_queries ]
    
    def verify_access(self, table_name: str) -> tuple[str, None]:
        # Runs on Target database
        schema = self.table_group.table_group_schema
        quote = self.flavor_service.quote_character
        query = (
            f"SELECT 1 FROM {quote}{schema}{quote}.{quote}{table_name}{quote} LIMIT 1"
            if not self.flavor_service.use_top
            else f"SELECT TOP 1 * FROM {quote}{schema}{quote}.{quote}{table_name}{quote}"
        )
        return (query, None)
    
    def get_staging_data_chars(self, data_chars: list[ColumnChars], run_date: datetime) -> list[list[str | bool | int]]:
        return [
            [
                self.table_group.id,
                run_date,
                column.schema_name,
                column.table_name,
                column.column_name,
                column.ordinal_position,
                column.general_type,
                column.column_type,
                column.db_data_type,
                column.approx_record_ct,
                column.record_ct,
            ]
            for column in data_chars
        ]
    
    def update_data_chars(self, run_date: str) -> list[tuple[str, dict]]:
        # Runs on App database
        params = {"RUN_DATE": run_date}
        return [
            self._get_query("data_chars_update.sql", extra_params=params),
            self._get_query("data_chars_staging_delete.sql", extra_params=params),
        ]
