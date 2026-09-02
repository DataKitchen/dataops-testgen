SET SEARCH_PATH TO {SCHEMA_NAME};

-- Seconds a job spent actually working, accumulated across however many processes ran it. A
-- run that stops and continues later spans more wall-clock time than it works, and the gap is
-- unbounded once the stop is one somebody asked for, so the elapsed time between the run's
-- start and its end cannot answer how long it took. NULL on rows that predate this, and on any
-- run that never stopped -- both are read from their start and end instead.
ALTER TABLE job_executions
    ADD COLUMN IF NOT EXISTS active_seconds DOUBLE PRECISION;
