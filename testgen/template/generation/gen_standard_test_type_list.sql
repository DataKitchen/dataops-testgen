SELECT t.test_type,
       t.selection_criteria,
       t.default_parm_columns,
       t.default_parm_values
FROM test_types t
LEFT JOIN generation_sets s
  ON (t.test_type = s.test_type
 AND  '{GENERATION_SET}' = s.generation_set)
WHERE t.active = 'Y'
  AND t.selection_criteria <> 'TEMPLATE' -- Also excludes NULL
  AND (s.generation_set IS NOT NULL
   OR  '{GENERATION_SET}' = '')
ORDER BY test_type;
