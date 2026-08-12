SELECT t.test_type,
  t.selection_criteria,
  t.generation_template,
  t.default_parm_columns,
  t.default_parm_values
FROM test_types t
  -- Only active test types
WHERE t.active = 'Y'
  -- Only test types included in one of the selected generation sets
  AND t.test_type IN (
    SELECT s.test_type FROM generation_sets s WHERE s.generation_set = ANY(:GENERATION_SETS)
  )
ORDER BY test_type;
