/*
Clean the test definition status before it's set with missing tables / columns information
*/
UPDATE test_definitions
SET test_definition_status = NULL
WHERE cat_test_id IN ({CAT_TEST_IDS});
