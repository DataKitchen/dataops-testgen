SET SEARCH_PATH TO {SCHEMA_NAME};


WITH last_test_run_dates AS (
    SELECT test_suite_id,
        MAX(test_starttime) AS test_starttime
    FROM test_runs
    WHERE status = 'Complete'
    GROUP BY test_suite_id
)
UPDATE test_suites
SET last_complete_test_run_id = tr.id
FROM last_test_run_dates ltd
    LEFT JOIN test_runs tr ON (
        ltd.test_suite_id = tr.test_suite_id
        AND ltd.test_starttime = tr.test_starttime
    )
WHERE test_suites.id = ltd.test_suite_id;


WITH last_profile_dates AS (
    SELECT table_groups_id,
        MAX(profiling_starttime) AS profiling_starttime
    FROM profiling_runs
    WHERE status = 'Complete'
    GROUP BY table_groups_id
)
UPDATE table_groups
SET last_complete_profile_run_id = pr.id
FROM last_profile_dates lpd
    LEFT JOIN profiling_runs pr ON (
        lpd.table_groups_id = pr.table_groups_id
        AND lpd.profiling_starttime = pr.profiling_starttime
    )
WHERE table_groups.id = lpd.table_groups_id;


WITH last_profile_dates AS (
    SELECT profiling_runs.table_groups_id,
        table_name,
        MAX(profiling_starttime) AS profiling_starttime
    FROM profile_results
        LEFT JOIN profiling_runs ON (
            profile_results.profile_run_id = profiling_runs.id
        )
    WHERE status = 'Complete'
    GROUP BY profiling_runs.table_groups_id,
        table_name
)
UPDATE data_table_chars
SET last_complete_profile_run_id = pr.id
FROM last_profile_dates lpd
    LEFT JOIN profiling_runs pr ON (
        lpd.table_groups_id = pr.table_groups_id
        AND lpd.profiling_starttime = pr.profiling_starttime
    )
WHERE data_table_chars.table_groups_id = lpd.table_groups_id
    AND data_table_chars.table_name = lpd.table_name;


WITH last_profile_dates AS (
    SELECT profiling_runs.table_groups_id,
        table_name,
        column_name,
        MAX(profiling_starttime) AS profiling_starttime
    FROM profile_results
        LEFT JOIN profiling_runs ON (
            profile_results.profile_run_id = profiling_runs.id
        )
    WHERE status = 'Complete'
    GROUP BY profiling_runs.table_groups_id,
        table_name,
        column_name
)
UPDATE data_column_chars
SET last_complete_profile_run_id = pr.id
FROM last_profile_dates lpd
    LEFT JOIN profiling_runs pr ON (
        lpd.table_groups_id = pr.table_groups_id
        AND lpd.profiling_starttime = pr.profiling_starttime
    )
WHERE data_column_chars.table_groups_id = lpd.table_groups_id
    AND data_column_chars.table_name = lpd.table_name
    AND data_column_chars.column_name = lpd.column_name;
