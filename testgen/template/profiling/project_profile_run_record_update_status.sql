UPDATE profiling_runs
SET status = '{STATUS}',
    profiling_endtime = '{NOW}',
    log_message = '{EXCEPTION_MESSAGE}'
where id = '{PROFILE_RUN_ID}' :: UUID;
