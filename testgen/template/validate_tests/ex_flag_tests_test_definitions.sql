/*
Mark Test inactive for Missing columns/tables with update status
*/
UPDATE test_definitions
SET test_active            = '{FLAG}',
    test_definition_status = LEFT('Inactivated {RUN_DATE}: ' || CONCAT_WS('; ', substring(test_definition_status from 34), '{MESSAGE}'), 200)
WHERE cat_test_id IN ({CAT_TEST_IDS});
