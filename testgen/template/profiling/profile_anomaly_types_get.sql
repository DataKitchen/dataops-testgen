SELECT id, anomaly_type, data_object, anomaly_criteria, detail_expression, dq_score_prevalence_formula, dq_score_risk_factor
  FROM profile_anomaly_types t
ORDER BY id;
