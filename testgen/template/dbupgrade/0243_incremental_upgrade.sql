SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE test_suites
   SET test_suite = regexp_replace(test_suite, '^\s+|\s+$', '', 'g')
 WHERE test_suite ~ '^\s|\s$';
