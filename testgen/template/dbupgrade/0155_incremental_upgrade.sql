SET SEARCH_PATH TO {SCHEMA_NAME};

DROP TABLE data_structure_log;

CREATE TABLE data_structure_log (
   log_id UUID DEFAULT gen_random_uuid()
      CONSTRAINT pk_dsl_id
         PRIMARY KEY,
   element_id UUID,
   change_date TIMESTAMP,
   change VARCHAR(10),
   old_column_type VARCHAR(50),
   new_column_type VARCHAR(50)
);
