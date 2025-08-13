from testgen.common import read_template_sql_file
from testgen.common.database.database_service import replace_params
from testgen.common.database.flavor.flavor_service import SQLFlavor
from testgen.utils import chunk_queries


class CRefreshDataCharsSQL:
    run_date: str
    source_table: str

    project_code: str
    sql_flavor: SQLFlavor
    table_group_schema: str
    table_group_id: str

    max_query_chars: int
    profiling_table_set: str
    profiling_include_mask: str
    profiling_exclude_mask: str

    def __init__(self, params: dict, run_date: str, source_table: str):
        self.run_date = run_date
        self.source_table = source_table

        self.project_code = params["project_code"]
        self.sql_flavor = params["sql_flavor"]
        self.table_group_schema = params["table_group_schema"]
        self.table_group_id = params["table_groups_id"]

        self.max_query_chars = params["max_query_chars"]
        self.profiling_table_set = params["profiling_table_set"]
        self.profiling_include_mask = params["profiling_include_mask"]
        self.profiling_exclude_mask = params["profiling_exclude_mask"]

    def _get_query(self, template_file_name: str, sub_directory: str | None = "data_chars") -> tuple[str, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "PROJECT_CODE": self.project_code,
            "DATA_SCHEMA": self.table_group_schema,
            "TABLE_GROUPS_ID": self.table_group_id,
            "RUN_DATE": self.run_date,
            "SOURCE_TABLE": self.source_table,
        }
        query = replace_params(query, params)
        return query, params

    def _get_mask_query(self, mask: str, is_include: bool) -> str:
        escape = ""
        if self.sql_flavor.startswith("mssql"):
            escaped_underscore = "[_]"
        elif self.sql_flavor == "snowflake":
            escaped_underscore = "\\\\_"
            escape = "ESCAPE '\\\\'"
        elif self.sql_flavor == "redshift":
            escaped_underscore = "\\\\_"
        else:
            escaped_underscore = "\\_"

        table_names = [ item.strip().replace("_", escaped_underscore) for item in mask.split(",") ]
        sub_query = f"""
            AND {"NOT" if not is_include else ""} (
                {" OR ".join([ f"(c.table_name LIKE '{item}' {escape})" for item in table_names ])}
            )
        """

        return sub_query
    
    def GetDDFQuery(self) -> tuple[str, dict]:
        # Runs on Target database
        query, params = self._get_query(f"schema_ddf_query_{self.sql_flavor}.sql", f"flavors/{self.sql_flavor}/data_chars")

        table_criteria = ""
        if self.profiling_table_set:
            table_criteria += f" AND c.table_name IN ({self.profiling_table_set})"

        if self.profiling_include_mask:
            table_criteria += self._get_mask_query(self.profiling_include_mask, is_include=True)

        if self.profiling_exclude_mask:
            table_criteria += self._get_mask_query(self.profiling_exclude_mask, is_include=False)

        query = query.replace("{TABLE_CRITERIA}", table_criteria)

        return query, params
    
    def GetRecordCountQueries(self, schema_tables: list[str]) -> list[tuple[str, None]]:
        # Runs on Target database
        count_queries = [
            f"SELECT '{item}', COUNT(*) FROM {item}"
            for item in schema_tables
        ]
        chunked_queries = chunk_queries(count_queries, " UNION ALL ", self.max_query_chars)
        return [ (query, None) for query in chunked_queries ]
    
    def GetDataCharsUpdateQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("data_chars_update.sql")
    
    def GetStagingDeleteQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("data_chars_staging_delete.sql")
