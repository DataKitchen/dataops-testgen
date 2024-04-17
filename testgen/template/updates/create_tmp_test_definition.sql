DROP TABLE IF EXISTS tmp_test_definition CASCADE;

CREATE TEMPORARY TABLE  tmp_test_definition
(
    project_code           varchar(30),
    test_suite             varchar(200),
    schema_name            varchar(100),
    table_name             varchar(100),
    column_name            varchar(500),
    id                     uuid,
    test_type              varchar(200),
    test_description       varchar(1000),
    test_action            varchar(100),
    test_active            varchar(10),
    lock_refresh           varchar(10),
    severity               varchar(10),
    test_parameter         varchar(100),
    test_parameter_value   varchar(1000)
);
