SELECT '{SAMPLING_TABLE}' as schema_table,
       CASE
         WHEN count(*) <= {PROFILE_SAMPLE_MIN_COUNT}
           THEN -1
           ELSE
                CASE
                  WHEN ROUND(CAST({PROFILE_SAMPLE_PERCENT} as FLOAT) * CAST(COUNT(*) as FLOAT) / 100.0, 0) > {PROFILE_SAMPLE_MIN_COUNT}
                    THEN LEAST(999000, ROUND(CAST({PROFILE_SAMPLE_PERCENT} as FLOAT) * CAST(COUNT(*) as FLOAT) / 100.0, 0))
                    ELSE {PROFILE_SAMPLE_MIN_COUNT}
                END
       END as sample_count,
       CASE
         WHEN count(*) <= {PROFILE_SAMPLE_MIN_COUNT}
           THEN 1
           ELSE (CAST(COUNT(*) as FLOAT)
                  / CASE
                      WHEN ROUND(CAST({PROFILE_SAMPLE_PERCENT} as FLOAT) * CAST(COUNT(*) as FLOAT) / 100.0, 0) > {PROFILE_SAMPLE_MIN_COUNT}
                        THEN LEAST(999000, ROUND(CAST({PROFILE_SAMPLE_PERCENT} as FLOAT) * CAST(COUNT(*) as FLOAT) / 100.0, 0))
                        ELSE {PROFILE_SAMPLE_MIN_COUNT}
                    END )
       END as sample_ratio
from {SAMPLING_TABLE};
