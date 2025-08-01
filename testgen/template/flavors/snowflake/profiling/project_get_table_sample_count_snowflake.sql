WITH stats
   AS (SELECT COUNT(*)::FLOAT as record_ct,
              ROUND(CAST({PROFILE_SAMPLE_PERCENT} as FLOAT) * CAST(COUNT(*) as FLOAT) / 100.0) as calc_sample_ct,
              CAST({PROFILE_SAMPLE_MIN_COUNT} as FLOAT) as min_sample_ct,
              CAST(999000 as FLOAT) as max_sample_ct
         FROM {SAMPLING_TABLE} )
SELECT '{SAMPLING_TABLE}' as schema_table,
       CASE WHEN record_ct <= min_sample_ct     THEN -1
            WHEN calc_sample_ct > max_sample_ct THEN max_sample_ct
            WHEN calc_sample_ct > min_sample_ct THEN calc_sample_ct
                                                ELSE {PROFILE_SAMPLE_MIN_COUNT}
       END as sample_count,
       CASE  WHEN record_ct <= min_sample_ct     THEN 1
             WHEN calc_sample_ct > max_sample_ct THEN record_ct / max_sample_ct
             WHEN calc_sample_ct > min_sample_ct THEN record_ct / calc_sample_ct
                                                 ELSE record_ct / min_sample_ct
       END as sample_ratio,
       ROUND(CASE  WHEN record_ct <= min_sample_ct     THEN 100
                   WHEN calc_sample_ct > max_sample_ct THEN 100.0 * max_sample_ct / record_ct
                   WHEN calc_sample_ct > min_sample_ct THEN 100.0 * calc_sample_ct / record_ct
                                                       ELSE 100.0 * min_sample_ct / record_ct
             END, 4) as sample_percent_calc
  FROM stats;
