UPDATE profiling_runs
SET status = CASE WHEN length('{EXCEPTION_MESSAGE}') = 0 then 'Complete' else 'Error' end,
    profiling_endtime = '{NOW}',
    log_message = '{EXCEPTION_MESSAGE}'
where id = '{PROFILE_RUN_ID}' :: UUID;
