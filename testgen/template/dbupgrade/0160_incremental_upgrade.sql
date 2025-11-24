SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE connections
    SET max_query_chars = 20000
    WHERE max_query_chars = 9000;
