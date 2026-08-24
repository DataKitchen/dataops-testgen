import re
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from testgen.common import read_template_sql_file
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service, replace_params
from testgen.common.models.connection import DEFAULT_MAX_QUERY_CHARS, Connection
from testgen.common.models.table_group import TableGroup
from testgen.utils import chunk_queries, to_sql_timestamp


def _like_to_regex(pattern: str) -> re.Pattern[str]:
    # Mirrors SQL LIKE semantics used in _get_table_criteria: `%` is the only
    # wildcard; `_` is treated as a literal character (escaped to `\_` in the
    # SQL path). Anything else is literal.
    return re.compile("^" + re.escape(pattern.strip()).replace("%", ".*") + "$")


class RefreshDataCharsSQL:

    staging_table = "stg_data_chars_updates"
    staging_columns = (
        "refresh_id",
        "table_groups_id",
        "run_date",
        "schema_name",
        "table_name",
        "column_name",
        "position",
        "general_type",
        "column_type",
        "db_data_type",
        "object_type",
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

    def filter_schema_columns(self, columns: list[ColumnChars]) -> list[ColumnChars]:
        """Apply the table group's filters (table set, include/exclude masks) to a column list.

        Mirrors `_get_table_criteria` for flavors that bypass the SQL template path
        (e.g., Salesforce Data 360, where columns come from the metadata API).
        """
        result = columns

        if self.table_group.profiling_table_set:
            allowed = {item.strip() for item in self.table_group.profiling_table_set.split(",")}
            result = [c for c in result if c.table_name in allowed]

        if self.table_group.profiling_include_mask:
            include_patterns = [
                _like_to_regex(item) for item in self.table_group.profiling_include_mask.split(",")
            ]
            result = [c for c in result if any(p.match(c.table_name) for p in include_patterns)]

        if self.table_group.profiling_exclude_mask:
            exclude_patterns = [
                _like_to_regex(item) for item in self.table_group.profiling_exclude_mask.split(",")
            ]
            result = [c for c in result if not any(p.match(c.table_name) for p in exclude_patterns)]

        return result

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
        count_queries = [
            f"SELECT '{table}' AS table_name, COUNT(*) AS row_count FROM {self.flavor_service.get_table_ref(schema, table)}"
            for table in table_names
        ]
        max_query_chars = self.connection.max_query_chars or DEFAULT_MAX_QUERY_CHARS
        chunked_queries = chunk_queries(count_queries, " UNION ALL ", max_query_chars)
        return [ (query, None) for query in chunked_queries ]

    def verify_access(self, table_name: str) -> tuple[str, None]:
        # Runs on Target database
        schema = self.table_group.table_group_schema
        table_ref = self.flavor_service.get_table_ref(schema, table_name)
        prefix, suffix = self.flavor_service.row_limit_clauses(1)
        query = f"SELECT {prefix} 1 FROM {table_ref} {suffix}".strip()
        return (query, None)

    def get_staging_data_chars(
        self, data_chars: list[ColumnChars], run_date: datetime, refresh_id: UUID,
    ) -> list[list[str | bool | int | UUID | None]]:
        return [
            [
                refresh_id,
                self.table_group.id,
                to_sql_timestamp(run_date),
                column.schema_name,
                column.table_name,
                column.column_name,
                column.ordinal_position,
                column.general_type,
                column.column_type,
                column.db_data_type,
                column.object_type,
                column.approx_record_ct,
                column.record_ct,
            ]
            for column in data_chars
        ]

    def update_data_chars(self, run_date: datetime, refresh_id: UUID) -> list[tuple[str, dict]]:
        # Runs on App database
        params = {"RUN_DATE": to_sql_timestamp(run_date), "REFRESH_ID": refresh_id}
        return [
            self._get_query("data_chars_update.sql", extra_params=params),
            self._get_query("data_chars_staging_delete.sql", extra_params=params),
        ]
