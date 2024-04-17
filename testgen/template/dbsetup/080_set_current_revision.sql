SET SEARCH_PATH TO {SCHEMA_NAME};

UPDATE tg_revision
   SET revision = {DB_REVISION}
 WHERE component = 'metadata_db';
