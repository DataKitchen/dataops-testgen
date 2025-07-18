from uuid import UUID

from testgen.common import read_template_sql_file
from testgen.common.database.database_service import replace_params


class CRollupScoresSQL:
    run_id: str
    table_group_id: str

    def __init__(self, run_id: str, table_group_id: str | UUID | None = None):
        self.run_id = run_id
        self.table_group_id = str(table_group_id)

    def _get_query(self, template_file_name: str, sub_directory: str | None = "rollup_scores") -> tuple[str, dict]:
        query = read_template_sql_file(template_file_name, sub_directory)
        params = {
            "RUN_ID": self.run_id,
            "TABLE_GROUPS_ID": self.table_group_id or ""
        }
        query = replace_params(query, params)
        return query, params
    
    def GetRollupScoresProfileRunQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("rollup_scores_profile_run.sql")
    
    def GetRollupScoresProfileTableGroupQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("rollup_scores_profile_table_group.sql")
    
    def GetRollupScoresTestRunQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("rollup_scores_test_run.sql")
    
    def GetRollupScoresTestTableGroupQuery(self) -> tuple[str, dict]:
        # Runs on App database
        return self._get_query("rollup_scores_test_table_group.sql")
