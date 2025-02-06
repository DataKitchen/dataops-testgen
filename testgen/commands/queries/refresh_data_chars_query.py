from testgen.common import read_template_sql_file
from testgen.utils import chunk_queries


class CRefreshDataCharsSQL:
    run_date: str
    source_table: str

    project_code: str
    sql_flavor: str
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

    def _replace_params(self, sql_query: str) -> str:
        sql_query = sql_query.replace("{PROJECT_CODE}", self.project_code)
        sql_query = sql_query.replace("{DATA_SCHEMA}", self.table_group_schema)
        sql_query = sql_query.replace("{TABLE_GROUPS_ID}", self.table_group_id)
        sql_query = sql_query.replace("{RUN_DATE}", self.run_date)
        sql_query = sql_query.replace("{SOURCE_TABLE}", self.source_table)
        return sql_query
    
    def _get_mask_query(self, mask: str, is_include: bool) -> str:
        sub_query = ""
        if mask:
            sub_query += " AND (" if is_include else " AND NOT ("
            is_first = True
            for item in mask.split(","):
                if not is_first:
                    sub_query += " OR "
                sub_query += "(c.table_name LIKE '" + item.strip() + "')"
                is_first = False
            sub_query += ")"
        return sub_query
    
    def GetDDFQuery(self) -> str:
        # Runs on Project DB
        sql_query = self._replace_params(
            read_template_sql_file(
                f"schema_ddf_query_{self.sql_flavor}.sql", sub_directory=f"flavors/{self.sql_flavor}/data_chars"
            )
        )

        table_criteria = ""
        if self.profiling_table_set:
            table_criteria += f" AND c.table_name IN ({self.profiling_table_set})"
        table_criteria += self._get_mask_query(self.profiling_include_mask, is_include=True)
        table_criteria += self._get_mask_query(self.profiling_exclude_mask, is_include=False)
        sql_query = sql_query.replace("{TABLE_CRITERIA}", table_criteria)

        return sql_query
    
    def GetRecordCountQueries(self, schema_tables: list[str]) -> list[str]:
        count_queries = [
            f"SELECT '{item}', COUNT(*) FROM {item}"
            for item in schema_tables
        ]
        return chunk_queries(count_queries, " UNION ALL ", self.max_query_chars)
    
    def GetDataCharsUpdateQuery(self) -> str:
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("data_chars_update.sql", sub_directory="data_chars"))
    
    def GetStagingDeleteQuery(self) -> str:
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("data_chars_staging_delete.sql", sub_directory="data_chars"))
