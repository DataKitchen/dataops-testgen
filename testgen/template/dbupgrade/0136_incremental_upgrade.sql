SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE score_definition_results_breakdown
    ADD COLUMN table_groups_name TEXT DEFAULT NULL,
    ADD COLUMN data_location TEXT DEFAULT NULL,
    ADD COLUMN data_source TEXT DEFAULT NULL,
    ADD COLUMN source_system TEXT DEFAULT NULL,
    ADD COLUMN source_process TEXT DEFAULT NULL,
    ADD COLUMN business_domain TEXT DEFAULT NULL,
    ADD COLUMN stakeholder_group TEXT DEFAULT NULL,
    ADD COLUMN transform_level TEXT DEFAULT NULL,
    ADD COLUMN data_product TEXT DEFAULT NULL;
