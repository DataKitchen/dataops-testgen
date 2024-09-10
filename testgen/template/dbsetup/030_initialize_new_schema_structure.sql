
SET SEARCH_PATH TO {SCHEMA_NAME};

-- ==============================================================================
-- |   Create DB Objects
-- |      This script should only be run for new schema -- no drops
-- ==============================================================================

CREATE SEQUENCE test_definitions_cat_test_id_seq;

CREATE SEQUENCE profile_results_dk_id_seq;

CREATE TABLE stg_secondary_profile_updates (
   project_code    VARCHAR(30),
   schema_name     VARCHAR(50),
   run_date        TIMESTAMP,
   table_name      VARCHAR(120),
   column_name     VARCHAR(120),
   top_freq_values VARCHAR(1500),
   distinct_value_hash VARCHAR(40)
);

CREATE TABLE stg_functional_table_updates (
   project_code  VARCHAR(30),
   schema_name   VARCHAR(50),
   run_date      TIMESTAMP,
   table_name    VARCHAR(120),
   table_period  VARCHAR(10),
   table_type    VARCHAR(11)
);

CREATE TABLE projects (
   id                  UUID DEFAULT gen_random_uuid(),
   project_code        VARCHAR(30) NOT NULL
      CONSTRAINT projects_project_code_pk
         PRIMARY KEY,
   project_name        VARCHAR(50),
   effective_from_date DATE,
   effective_thru_date DATE,
   observability_api_key TEXT,
   observability_api_url TEXT DEFAULT ''
);

CREATE TABLE connections (
   id                     UUID DEFAULT gen_random_uuid(),
   project_code           VARCHAR(30)
      CONSTRAINT connections_projects_project_code_fk
         REFERENCES projects,
   connection_id          BIGINT GENERATED ALWAYS AS IDENTITY
      CONSTRAINT connections_connection_id_pk
         PRIMARY KEY,
   sql_flavor             VARCHAR(30),
   project_host           VARCHAR(250),
   project_port           VARCHAR(5),
   project_user           VARCHAR(50),
   project_db             VARCHAR(100),
   connection_name        VARCHAR(40),
   project_qc_schema      VARCHAR(200),
   project_pw_encrypted   BYTEA,
   max_threads            INTEGER DEFAULT 4,
   max_query_chars        INTEGER,
   url VARCHAR(200) default '',
   connect_by_url BOOLEAN default FALSE,
   connect_by_key BOOLEAN DEFAULT FALSE,
   private_key BYTEA,
   private_key_passphrase BYTEA
);

CREATE TABLE table_groups
(
    id                       UUID DEFAULT gen_random_uuid(),
    project_code             VARCHAR(30)
      CONSTRAINT table_groups_projects_project_code_fk
           REFERENCES projects,
    connection_id            BIGINT
          CONSTRAINT table_groups_connections_connection_id_fk
           REFERENCES connections,
    table_groups_name        VARCHAR(100),
    table_group_schema       VARCHAR(100),
    profiling_table_set      VARCHAR(2000),
    profiling_include_mask   VARCHAR(2000),
    profiling_exclude_mask   VARCHAR(2000),
    profile_id_column_mask   VARCHAR(2000) DEFAULT '%id' :: VARCHAR(2000),
    profile_sk_column_mask   VARCHAR(150) DEFAULT '%_sk',
    profile_use_sampling     VARCHAR(3) DEFAULT 'N',
    profile_sample_percent   VARCHAR(3) DEFAULT '30',
    profile_sample_min_count BIGINT DEFAULT 100000,
    profiling_delay_days     VARCHAR(3) DEFAULT '0' ,
    profile_do_pair_rules    VARCHAR(3) DEFAULT 'N',
    profile_pair_rule_pct    INTEGER DEFAULT 95,
    data_source              VARCHAR(40),
    source_system            VARCHAR(40),
    data_location            VARCHAR(40),
    source_process           VARCHAR(40),
    business_domain          VARCHAR(40),
    stakeholder_group        VARCHAR(40),
    transform_level          VARCHAR(40)
);

CREATE TABLE profiling_runs (
   id                  UUID
      CONSTRAINT pk_prun_id
         PRIMARY KEY,
   project_code        VARCHAR(30) NOT NULL,
   connection_id       BIGINT      NOT NULL,
   table_groups_id     UUID        NOT NULL,
   profiling_starttime TIMESTAMP,
   profiling_endtime   TIMESTAMP,
   status              VARCHAR(100) DEFAULT 'Running',
   log_message         VARCHAR,
   table_ct            BIGINT,
   column_ct           BIGINT,
   anomaly_ct          BIGINT,
   anomaly_table_ct    BIGINT,
   anomaly_column_ct   BIGINT,
   process_id          INTEGER
);

CREATE TABLE test_suites (
   id                      UUID        DEFAULT gen_random_uuid(),
   project_code            VARCHAR(30)  NOT NULL,
   test_suite              VARCHAR(200) NOT NULL,
   connection_id           BIGINT
      CONSTRAINT test_suites_connections_connection_id_fk
         REFERENCES connections,
   table_groups_id         UUID,
   test_suite_description  VARCHAR(1000),
   test_action             VARCHAR(100),
   severity                VARCHAR(10),
   export_to_observability VARCHAR(5)  DEFAULT 'Y',
--    email_list             VARCHAR(200),
--    email_slack            VARCHAR(100),
--    wiki_link              VARCHAR(200),
--    variation_link         VARCHAR(200),
--    wiki_page_id           BIGINT,
--    confluence_space       VARCHAR(10),
   test_suite_schema       VARCHAR(100),
   component_key           VARCHAR(100),
   component_type          VARCHAR(100),
   component_name          VARCHAR(100),
   CONSTRAINT test_suites_id_pk
      PRIMARY KEY (id)
);

CREATE TABLE test_definitions (
   id                     UUID DEFAULT gen_random_uuid(),
   cat_test_id            BIGINT GENERATED BY DEFAULT AS IDENTITY
      CONSTRAINT test_definitions_cat_test_id_pk
         PRIMARY KEY,
   table_groups_id        UUID,
   profile_run_id         UUID,
   test_type              VARCHAR(200),
   test_suite_id          UUID NOT NULL,
   test_description       VARCHAR(1000),
   test_action            VARCHAR(100),
   schema_name            VARCHAR(100),
   table_name             VARCHAR(100),
   column_name            VARCHAR(500),
   skip_errors            INTEGER,
   baseline_ct            VARCHAR(1000),
   baseline_unique_ct     VARCHAR(1000),
   baseline_value         VARCHAR(1000),
   baseline_value_ct      VARCHAR(1000),
   threshold_value        VARCHAR(1000),
   baseline_sum           VARCHAR(1000),
   baseline_avg           VARCHAR(1000),
   baseline_sd            VARCHAR(1000),
   subset_condition       VARCHAR(500),
   groupby_names          VARCHAR(200),
   having_condition       VARCHAR(500),
   window_date_column     VARCHAR(100),
   window_days            INTEGER,
   match_schema_name      VARCHAR(100),
   match_table_name       VARCHAR(100),
   match_column_names     VARCHAR(200),
   match_subset_condition VARCHAR(500),
   match_groupby_names    VARCHAR(200),
   match_having_condition VARCHAR(500),
   test_mode              VARCHAR(20),
   custom_query           VARCHAR,
   test_active            VARCHAR(10) DEFAULT 'Y':: CHARACTER VARYING,
   test_definition_status VARCHAR(200),
   severity               VARCHAR(10),
   watch_level            VARCHAR(10) DEFAULT 'WARN'::CHARACTER VARYING,
   check_result           VARCHAR(500),
   lock_refresh           VARCHAR(10) DEFAULT 'N' NOT NULL,
   last_auto_gen_date     TIMESTAMP,
   profiling_as_of_date   TIMESTAMP,
   last_manual_update     TIMESTAMP DEFAULT NULL,
   export_to_observability VARCHAR(5),
   CONSTRAINT test_definitions_test_suites_test_suite_id_fk
      FOREIGN KEY (test_suite_id) REFERENCES test_suites
);

ALTER SEQUENCE test_definitions_cat_test_id_seq OWNED BY test_definitions.cat_test_id;

CREATE TABLE profile_results (
   id                    UUID DEFAULT gen_random_uuid()
      CONSTRAINT profile_results_id_pk
         PRIMARY KEY,
   dk_id                 BIGINT GENERATED ALWAYS AS IDENTITY,
--       CONSTRAINT profile_results_dk_id_pk
--          PRIMARY KEY,
   project_code          VARCHAR(30),
   connection_id         BIGINT
      CONSTRAINT profile_results_connections_connection_id_fk
         REFERENCES connections,
   table_groups_id       UUID,
   profile_run_id        UUID,
   schema_name           VARCHAR(50),
   run_date              TIMESTAMP,
   table_name            VARCHAR(120),
   position              INTEGER,
   column_name           VARCHAR(120),
   column_type           VARCHAR(50),
   general_type          VARCHAR(1),
   record_ct             BIGINT,
   value_ct              BIGINT,
   distinct_value_ct     BIGINT,
   distinct_std_value_ct BIGINT,
   null_value_ct         BIGINT,
   min_length            INTEGER,
   max_length            INTEGER,
   avg_length            DOUBLE PRECISION,
   zero_value_ct         BIGINT,
   zero_length_ct        BIGINT,
   lead_space_ct         BIGINT,
   quoted_value_ct       BIGINT,
   includes_digit_ct     BIGINT,
   filled_value_ct       BIGINT,
   min_text              VARCHAR(1000),
   max_text              VARCHAR(1000),
   numeric_ct            BIGINT,
   date_ct               BIGINT,
   top_patterns          VARCHAR(1000),
   top_freq_values       VARCHAR(1500),
   distinct_value_hash   VARCHAR(40),
   min_value             DOUBLE PRECISION,
   min_value_over_0         DOUBLE PRECISION,
   max_value             DOUBLE PRECISION,
   avg_value             DOUBLE PRECISION,
   stdev_value           DOUBLE PRECISION,
   percentile_25         DOUBLE PRECISION,
   percentile_50         DOUBLE PRECISION,
   percentile_75         DOUBLE PRECISION,
   fractional_sum        NUMERIC(38, 6),
   min_date              TIMESTAMP,
   max_date              TIMESTAMP,
   before_1yr_date_ct    BIGINT,
   before_5yr_date_ct    BIGINT,
   before_20yr_date_ct   BIGINT,
   within_1yr_date_ct    BIGINT,
   within_1mo_date_ct    BIGINT,
   future_date_ct        BIGINT,
   date_days_present     BIGINT,
   date_weeks_present    BIGINT,
   date_months_present   BIGINT,
   boolean_true_ct       BIGINT,
   datatype_suggestion   VARCHAR(50),
   distinct_pattern_ct   BIGINT,
   embedded_space_ct     BIGINT,
   avg_embedded_spaces   DOUBLE PRECISION,
   std_pattern_match     VARCHAR(30),
   pii_flag              VARCHAR(50),
   functional_data_type  VARCHAR(50),
   functional_table_type VARCHAR(50),
   sample_ratio          FLOAT
);

ALTER SEQUENCE profile_results_dk_id_seq OWNED BY profile_results.dk_id;


CREATE TABLE profile_anomaly_types (
   id                  VARCHAR(10)  NOT NULL
        CONSTRAINT pk_anomaly_types_id
            PRIMARY KEY,
   anomaly_type        VARCHAR(200) NOT NULL,
   data_object         VARCHAR(10),  -- Table, Dates, Column
   anomaly_name        VARCHAR(100),
   anomaly_description VARCHAR(500),
   anomaly_criteria    VARCHAR(2000),
   detail_expression   VARCHAR(2000),
   issue_likelihood    VARCHAR(50),  -- Potential, Likely, Certain
   suggested_action    VARCHAR(1000) -- Consider, Investigate, Correct
);

CREATE TABLE profile_anomaly_results (
    id             UUID DEFAULT gen_random_uuid() NOT NULL
        CONSTRAINT pk_anomaly_results_id
            PRIMARY KEY,
   project_code    VARCHAR(30),
   table_groups_id UUID,
   profile_run_id  UUID,
   column_id       UUID,
   schema_name     VARCHAR(50),
   table_name      VARCHAR(120),
   column_name     VARCHAR(500),
   column_type     VARCHAR(50),
   anomaly_id      VARCHAR(10),
   detail          VARCHAR,
   disposition     VARCHAR(20) -- Confirmed, Dismissed, Inactive
);


CREATE TABLE profile_pair_rules (
   id                  UUID DEFAULT gen_random_uuid() NOT NULL
      CONSTRAINT pk_profile_pair_rules_id
         PRIMARY KEY,
   profile_run_id      UUID,
   schema_name         VARCHAR(50),
   table_name          VARCHAR(120),
   cause_column_name   VARCHAR(500),
   cause_column_value  VARCHAR,
   effect_column_name  VARCHAR(500),
   effect_column_value VARCHAR,
   pair_count          BIGINT,
   cause_column_total  BIGINT,
   effect_column_total BIGINT,
   rule_ratio          DECIMAL(6, 4)
);


CREATE TABLE data_structure_log (
   project_code     VARCHAR(30),
   connection_id    BIGINT,
   change_date      TIMESTAMP,
   schema_name      VARCHAR(50),
   table_name       VARCHAR(100),
   ordinal_position INTEGER,
   column_name      VARCHAR(100),
   data_type         VARCHAR(50),
   status           VARCHAR(10)
);

CREATE TABLE data_table_chars (
   table_id              UUID DEFAULT gen_random_uuid(),
   table_groups_id       UUID,
   schema_name           VARCHAR(50),
   table_name            VARCHAR(120),
   functional_table_type VARCHAR(50),
   critical_data_element BOOLEAN,
   data_source           VARCHAR(40),
   source_system         VARCHAR(40),
   source_process        VARCHAR(40),
   business_domain       VARCHAR(40),
   stakeholder_group     VARCHAR(40),
   transform_level       VARCHAR(40),
   aggregation_level     VARCHAR(40),
   add_date              TIMESTAMP,
   drop_date             TIMESTAMP,
   record_ct             BIGINT,
   column_ct             BIGINT,
   data_point_ct         BIGINT
);

CREATE TABLE data_column_chars (
   column_id              UUID DEFAULT gen_random_uuid(),
   table_id               UUID,
   table_groups_id        UUID,
   schema_name            VARCHAR(50),
   table_name             VARCHAR(120),
   column_name            VARCHAR(120),
   general_type           VARCHAR(1),
   column_type            VARCHAR(50),
   functional_data_type   VARCHAR(50),
   critical_data_element  BOOLEAN,
   data_source            VARCHAR(40),
   source_system          VARCHAR(40),
   source_process         VARCHAR(40),
   business_domain        VARCHAR(40),
   stakeholder_group      VARCHAR(40),
   transform_level        VARCHAR(40),
   aggregation_level      VARCHAR(40),
   add_date               TIMESTAMP,
   last_mod_date          TIMESTAMP,
   drop_date              TIMESTAMP,
   test_ct                INTEGER,
   last_test_date         TIMESTAMP,
   tests_last_run         INTEGER,
   tests_7_days_prior     INTEGER,
   tests_30_days_prior    INTEGER,
   fails_last_run         INTEGER,
   fails_7_days_prior     INTEGER,
   fails_30_days_prior    INTEGER,
   warnings_last_run      INTEGER,
   warnings_7_days_prior  INTEGER,
   warnings_30_days_prior INTEGER
);

CREATE TABLE test_types (
   id                      VARCHAR,
   test_type               VARCHAR(200) NOT NULL
      CONSTRAINT cat_tests_test_type_pk
         PRIMARY KEY,
   test_name_short         VARCHAR(30),
   test_name_long          VARCHAR(100),
   test_description        VARCHAR(1000),
   except_message          VARCHAR(1000),
   measure_uom             VARCHAR(100),
   measure_uom_description VARCHAR(200),
   selection_criteria      TEXT,
   column_name_prompt      TEXT,
   column_name_help        TEXT,
   default_parm_columns    TEXT,
   default_parm_values     TEXT,
   default_parm_prompts    TEXT,
   default_parm_help       TEXT,
   default_severity        VARCHAR(10),
   run_type                VARCHAR(10),
   test_scope              VARCHAR,
   dq_dimension            VARCHAR(50),
   health_dimension        VARCHAR(50),
   threshold_description   VARCHAR(200),
   usage_notes             VARCHAR,
   active                  VARCHAR
);

CREATE TABLE test_templates (
   id            VARCHAR,
   test_type     VARCHAR(200) NOT NULL
      CONSTRAINT test_templates_test_types_test_type_fk
         REFERENCES test_types,
   sql_flavor    VARCHAR(20)  NOT NULL,
   template_name VARCHAR(400),
   CONSTRAINT test_templates_test_type_sql_flavor_pk
      PRIMARY KEY (test_type, sql_flavor)
);

CREATE TABLE generation_sets (
   generation_set VARCHAR,
   test_type      VARCHAR,
   CONSTRAINT generation_sets_gen_set_test_type_pk
      PRIMARY KEY (generation_set, test_type)
);

CREATE TABLE test_runs (
   id                UUID NOT NULL
      CONSTRAINT test_runs_id_pk
         PRIMARY KEY,
   test_suite_id     UUID NOT NULL,
   test_starttime    TIMESTAMP,
   test_endtime      TIMESTAMP,
   status            VARCHAR(100) DEFAULT 'Running',
   log_message       TEXT,
   duration          VARCHAR(50),
   test_ct           INTEGER,
   passed_ct         INTEGER,
   failed_ct         INTEGER,
   warning_ct        INTEGER,
   error_ct          INTEGER,
   table_ct          INTEGER,
   column_ct         INTEGER,
   column_failed_ct  INTEGER,
   column_warning_ct INTEGER,
   process_id        INTEGER,
   CONSTRAINT test_runs_test_suites_fk
      FOREIGN KEY (test_suite_id) REFERENCES test_suites
);

CREATE TABLE test_results (
   id                     UUID DEFAULT gen_random_uuid(),
   result_id              BIGINT GENERATED ALWAYS AS IDENTITY,
   test_type              VARCHAR(50)
      CONSTRAINT test_results_test_types_test_type_fk
         REFERENCES test_types,
   test_suite_id          UUID NOT NULL,
   test_definition_id     UUID,
   auto_gen               BOOLEAN,
   test_time              TIMESTAMP,
   starttime              TIMESTAMP,
   endtime                TIMESTAMP,
   schema_name            VARCHAR(100),
   table_name             VARCHAR(100),
   column_names           VARCHAR(500),
   skip_errors            INTEGER,
   input_parameters       VARCHAR(1000),
   result_code            INTEGER,
   severity               VARCHAR(10),
   result_status          VARCHAR(10),
   result_message         VARCHAR(1000),
   result_measure         VARCHAR(1000),
   threshold_value        VARCHAR(1000),
   result_error_data      VARCHAR(4000),
   test_action            VARCHAR(100),
   disposition            VARCHAR(20),
   subset_condition       VARCHAR(500),
   result_query           VARCHAR(4000),
   test_description       VARCHAR(1000),
   test_run_id            UUID NOT NULL,
   table_groups_id        UUID,
   observability_status   VARCHAR(10),
   CONSTRAINT test_results_test_suites_project_code_test_suite_fk
      FOREIGN KEY (test_suite_id) REFERENCES test_suites
);

CREATE TABLE working_agg_cat_tests (
   test_run_id       UUID NOT NULL,
   schema_name       VARCHAR(200) NOT NULL,
   table_name        VARCHAR(200) NOT NULL,
   cat_sequence      INTEGER      NOT NULL,
   test_count        INTEGER,
   test_time         TIMESTAMP,
   start_time        TIMESTAMP,
   end_time          TIMESTAMP,
   column_names      TEXT,
   test_types        TEXT,
   test_definition_ids TEXT,
   test_actions      TEXT,
   test_descriptions TEXT,
   test_parms        TEXT,
   test_measures     TEXT,
   test_conditions   TEXT,
   CONSTRAINT working_agg_cat_tests_trid_sn_tn_cs
      PRIMARY KEY (test_run_id, schema_name, table_name, cat_sequence)
);

CREATE TABLE working_agg_cat_results (
   test_run_id     UUID NOT NULL,
   schema_name     VARCHAR(200) NOT NULL,
   table_name      VARCHAR(200) NOT NULL,
   cat_sequence    INTEGER      NOT NULL,
   measure_results TEXT,
   test_results    TEXT,
   CONSTRAINT working_agg_cat_results_tri_sn_tn_cs
      PRIMARY KEY (test_run_id, schema_name, table_name, cat_sequence)
);

CREATE TABLE cat_test_conditions (
   id             VARCHAR,
   test_type      VARCHAR(200) NOT NULL
      CONSTRAINT cat_test_conditions_cat_tests_test_type_fk
         REFERENCES test_types,
   sql_flavor     VARCHAR(20)  NOT NULL,
   measure        VARCHAR(2000),
   test_operator  VARCHAR(20),
   test_condition VARCHAR(2000),
   CONSTRAINT cat_test_conditions_test_type_sql_flavor_pk
      PRIMARY KEY (test_type, sql_flavor)
);

CREATE TABLE target_data_lookups (
   id           VARCHAR,
   test_id      VARCHAR,
   test_type    VARCHAR(200) NOT NULL,
   sql_flavor   VARCHAR(20)  NOT NULL,
   lookup_type  VARCHAR(10),
   lookup_query VARCHAR,
   error_type   VARCHAR(30)  NOT NULL
);

CREATE TABLE variant_codings (
   value_type   VARCHAR,
   check_values VARCHAR
);

CREATE TABLE functional_test_results
(
   test_name VARCHAR(50),
   error_ct  BIGINT
);

CREATE TABLE auth_users (
	id UUID 		DEFAULT gen_random_uuid(),
	username 		VARCHAR(20),
	email 			VARCHAR(120),
	name 			VARCHAR(120),
	password 		VARCHAR(120),
	preauthorized 	BOOLEAN default false,
	role      VARCHAR(20)
);

ALTER TABLE auth_users
ADD CONSTRAINT username_check
CHECK (
    LENGTH(username) >= 4 AND       -- Minimum length of 4 characters
    LENGTH(username) <= 20 AND      -- Maximum length of 20 characters
    username ~ '^[a-zA-Z0-9_]+$'   -- Only alphanumeric characters and underscores allowed
);

ALTER TABLE auth_users
ADD CONSTRAINT unique_username
UNIQUE (username);

CREATE TABLE tg_revision (
   component     VARCHAR(50) NOT NULL
      CONSTRAINT tg_revision_component_pk
         PRIMARY KEY,
   revision INTEGER
);


CREATE UNIQUE INDEX table_groups_name_unique ON table_groups(project_code, table_groups_name);

-- Index working table - ORIGINAL
CREATE INDEX working_agg_cat_tests_test_run_id_index
   ON working_agg_cat_tests(test_run_id);

-- Index Connections
CREATE UNIQUE INDEX uix_con_id
   ON connections(id);

-- Index Table_Groups
CREATE UNIQUE INDEX uix_tg_id
   ON table_groups(id);

CREATE INDEX ix_tg_cid
   ON table_groups(connection_id);


-- Index Profile Results - ORIGINAL -- still relevant?
CREATE INDEX profile_results_tgid_sn_tn_cn
    ON profile_results (table_groups_id, schema_name, table_name, column_name);


-- Index test_suites
CREATE UNIQUE INDEX uix_ts_id
   ON test_suites(id);

CREATE INDEX ix_ts_con
   ON test_suites(connection_id);

-- Index test_definitions
CREATE INDEX ix_td_ts_fk
   ON test_definitions(test_suite_id);

CREATE INDEX ix_td_pc_stc_tst
   ON test_definitions(test_suite_id, schema_name, table_name, column_name, test_type);

CREATE UNIQUE INDEX uix_td_id
   ON test_definitions(id);

CREATE INDEX ix_td_tg
   ON test_definitions(table_groups_id);

CREATE INDEX ix_td_ts_tc
   ON test_definitions(test_suite_id, table_name, column_name, test_type);

-- Index test_runs
CREATE INDEX ix_trun_ts_fk
   ON test_runs(test_suite_id);

CREATE INDEX ix_trun_pc_ts_time
   ON test_runs(test_suite_id, test_starttime);

CREATE INDEX ix_trun_time
   ON test_runs USING BRIN (test_starttime);

-- Index test_results
CREATE UNIQUE INDEX uix_tr_id
   ON test_results(id);

CREATE INDEX ix_tr_pc_ts
   ON test_results(test_suite_id);

CREATE INDEX ix_tr_trun
   ON test_results(test_run_id);

CREATE INDEX ix_tr_tt
   ON test_results(test_type);

CREATE INDEX ix_tr_pc_sctc_tt
   ON test_results(test_suite_id, schema_name, table_name, column_names, test_type);

CREATE INDEX ix_tr_ts_tctt
   ON test_results(test_suite_id, table_name, column_names, test_type);

-- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
-- PROFILING OPTIMIZATION
-- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

-- Index profiling_runs
CREATE INDEX ix_prun_pc_con
   ON profiling_runs(project_code, connection_id);

CREATE INDEX ix_prun_tg
   ON profiling_runs(table_groups_id);


-- Index profile_anomaly_types
CREATE UNIQUE INDEX uix_pat_at
   ON profile_anomaly_types(anomaly_type);


-- Index profile_results
CREATE INDEX ix_pr_prun
   ON profile_results(profile_run_id);

CREATE INDEX ix_pr_pc_con
   ON profile_results(project_code, connection_id);

CREATE UNIQUE INDEX uix_pr_tg_t_c_prun
   ON profile_results(table_groups_id, table_name, column_name, profile_run_id);


-- Index profile_pair_rules
CREATE INDEX ix_pro_pair_prun
   ON profile_pair_rules(profile_run_id);


-- Index profile_anomaly_results
CREATE INDEX ix_ares_prun
   ON profile_anomaly_results(profile_run_id);

CREATE INDEX ix_ares_anid
   ON profile_anomaly_results(anomaly_id);


-- Conditional index for Observability Export - ORIGINAL
CREATE INDEX cix_tr_pc_ts
   ON test_results(test_suite_id) WHERE observability_status = 'Queued';


INSERT INTO tg_revision (component, revision)
VALUES  ('metadata_db', 0);
