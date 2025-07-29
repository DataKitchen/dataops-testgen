UPDATE profile_anomaly_results r
   SET dq_prevalence = ({PREV_FORMULA}) * :RISK
  FROM profile_anomaly_results r2
INNER JOIN profile_results p
   ON (r2.profile_run_id = p.profile_run_id
  AND  r2.table_name = p.table_name
  AND  r2.column_name = p.column_name)
 WHERE r.profile_run_id = :PROFILE_RUN_ID
   AND r2.anomaly_id = :ANOMALY_ID
   AND r.id = r2.id;