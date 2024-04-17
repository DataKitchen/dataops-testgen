DELETE FROM stg_secondary_profile_updates s
             WHERE s.project_code = '{PROJECT_CODE}'
               AND s.schema_name = '{DATA_SCHEMA}'
               AND s.run_date = '{RUN_DATE}';
