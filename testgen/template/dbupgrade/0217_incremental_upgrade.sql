SET SEARCH_PATH TO {SCHEMA_NAME};

-- Backfill the worked time of every run that finished before it was being recorded, so the
-- column answers for those runs too and the displays can read it alone.
--
-- Measured from the claim where there is one, which is where the live accumulator measures
-- from: the claim happens in the scheduler and the start in the subprocess it spawns, so the
-- two differ by the spawn, and mixing them would leave backfilled rows meaning something
-- slightly different from live ones.
--
-- Requires a start, so a run that was claimed and never dispatched keeps its NULL. None of the
-- time between its claim and whatever settled it was work, and NULL is how this column says a
-- run never worked.
--
-- A run that stopped and continued gets only its last segment, because every claim restamps
-- the timestamp this measures from and the row keeps no history of the earlier ones. That
-- undercounts those runs. Recovering the rest would need per-segment records that rows written
-- before this column existed do not carry.
UPDATE job_executions
   SET active_seconds = EXTRACT(EPOCH FROM (completed_at - COALESCE(claimed_at, started_at)))
 WHERE active_seconds IS NULL
   AND started_at IS NOT NULL
   AND completed_at IS NOT NULL;
