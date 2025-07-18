SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE auth_users
  ADD CONSTRAINT pk_au_id
  PRIMARY KEY (id);

ALTER TABLE projects
  DROP COLUMN effective_from_date,
  DROP COLUMN effective_thru_date;

ALTER TABLE table_groups
  ADD CONSTRAINT pk_tg_id
  PRIMARY KEY (id);

UPDATE connections
  SET sql_flavor_code = sql_flavor
  WHERE sql_flavor_code IS NULL;
