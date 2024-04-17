SELECT t.test_type, t.test_description, dq_dimension
  FROM test_types t
 WHERE test_description > ''
ORDER BY test_type;