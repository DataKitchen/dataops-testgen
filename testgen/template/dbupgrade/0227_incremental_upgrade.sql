SET SEARCH_PATH TO {SCHEMA_NAME};

-- The Test Suites dialog stored its "Failed" option as 'Failed' and its "Inherit" option as
-- 'Inherit'. Test execution recognizes neither and records such a suite's failures as warnings.
-- 'Fail' is the value execution reads as failed; NULL leaves each test to its test type's severity.
UPDATE test_suites
   SET severity = CASE severity WHEN 'Failed' THEN 'Fail' END
 WHERE severity IN ('Failed', 'Inherit');
