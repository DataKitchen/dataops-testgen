SET SEARCH_PATH TO {SCHEMA_NAME};

-- The Trino flavor is not offered: it is absent from both SQLFlavor and SQLFlavorCode, so no
-- connection can name it, and its profiling templates and flavor service no longer exist.
-- cat_test_conditions is the only table that ever carried Trino rows. The YAML metadata import
-- upserts without deleting, so those rows survive an upgrade unless removed here.
DELETE FROM cat_test_conditions WHERE sql_flavor = 'trino';
