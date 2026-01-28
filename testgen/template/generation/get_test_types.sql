SELECT t.test_type,
  t.selection_criteria,
  t.generation_template,
  t.default_parm_columns,
  t.default_parm_values
FROM test_types t
  INNER JOIN generation_sets s ON (t.test_type = s.test_type)
  -- Only active test types
WHERE t.active = 'Y'
  -- Only test types included in generation set
  AND s.generation_set = :GENERATION_SET
ORDER BY test_type;
