SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE test_definitions
   SET id = gen_random_uuid()
   WHERE id IS NULL;
