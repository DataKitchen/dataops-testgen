SELECT t.test_type,
  t.selection_criteria,
  t.default_parm_columns,
  t.default_parm_values
FROM test_types t
  LEFT JOIN generation_sets s ON (t.test_type = s.test_type)
  -- Only active test types
WHERE t.active = 'Y'
  -- Only test types with non-null and non-template selection
  AND t.selection_criteria <> 'TEMPLATE'
  -- Only test types included in generation set
  AND s.generation_set = :GENERATION_SET
ORDER BY test_type;
