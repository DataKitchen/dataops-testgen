SET SEARCH_PATH TO {SCHEMA_NAME};

CREATE INDEX IF NOT EXISTS ix_td_suite_contract_term
   ON test_definitions (test_suite_id, contract_term_id)
   WHERE contract_term_id IS NOT NULL;
