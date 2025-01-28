from testgen.common import read_template_sql_file


class CRollupScoresSQL:
    run_id: str
    table_group_id: str

    def __init__(self, run_id: str, table_group_id: str | None = None):
        self.run_id = run_id
        self.table_group_id = table_group_id

    def _replace_params(self, sql_query: str) -> str:
        sql_query = sql_query.replace("{RUN_ID}", self.run_id)
        if self.table_group_id:
            sql_query = sql_query.replace("{TABLE_GROUPS_ID}", self.table_group_id)
        return sql_query
    
    def GetRollupScoresProfileRunQuery(self):
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("rollup_scores_profile_run.sql", sub_directory="rollup_scores"))
    
    def GetRollupScoresProfileTableGroupQuery(self):
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("rollup_scores_profile_table_group.sql", sub_directory="rollup_scores"))
    
    def GetRollupScoresTestRunQuery(self):
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("rollup_scores_test_run.sql", sub_directory="rollup_scores"))
    
    def GetRollupScoresTestTableGroupQuery(self):
        # Runs on DK Postgres Server
        return self._replace_params(read_template_sql_file("rollup_scores_test_table_group.sql", sub_directory="rollup_scores"))
