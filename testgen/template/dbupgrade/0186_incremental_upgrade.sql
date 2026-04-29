SET SEARCH_PATH TO {SCHEMA_NAME};

-- DQ Score Weighting

ALTER TABLE projects
    ADD COLUMN use_dq_score_weights BOOLEAN DEFAULT FALSE;
-- New projects default ON; existing projects stay OFF for backward compatibility
ALTER TABLE projects
    ALTER COLUMN use_dq_score_weights SET DEFAULT TRUE;

ALTER TABLE data_table_chars
    ADD COLUMN dq_score_weight FLOAT DEFAULT 1.0;

ALTER TABLE data_column_chars
    ADD COLUMN dq_score_weight     FLOAT DEFAULT 1.0,
    ADD COLUMN dq_score_pii_weight FLOAT DEFAULT 1.0;

CREATE TABLE dq_score_weight_defaults (
    id             UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    weight_scope   VARCHAR(10)  NOT NULL,
    semantic_type  VARCHAR(50)  NOT NULL,
    default_weight FLOAT        NOT NULL DEFAULT 1.0,
    UNIQUE (weight_scope, semantic_type)
);

-- Table-level defaults (matched via ILIKE on functional_table_type suffix)
INSERT INTO dq_score_weight_defaults (weight_scope, semantic_type, default_weight) VALUES
    ('table', '%entity',      10.0),
    ('table', '%domain',       5.0),
    ('table', '%bridge',       5.0),
    ('table', '%summary',      1.5),
    ('table', '%transaction',  1.0);

-- Column-level defaults (exact match on functional_data_type)
INSERT INTO dq_score_weight_defaults (weight_scope, semantic_type, default_weight) VALUES
    ('column', 'ID',                     3.0),
    ('column', 'ID-SK',                  3.0),
    ('column', 'ID-Unique',              3.0),
    ('column', 'ID-Unique-SK',           3.0),
    ('column', 'ID-FK',                  2.5),
    ('column', 'ID-Secondary',           2.0),
    ('column', 'ID-Group',               1.5),
    ('column', 'Email',                  2.0),
    ('column', 'Phone',                  2.0),
    ('column', 'Person Full Name',       2.0),
    ('column', 'Person Given Name',      1.5),
    ('column', 'Person Last Name',       1.5),
    ('column', 'Entity Name',            2.0),
    ('column', 'Address',                1.5),
    ('column', 'City',                   1.5),
    ('column', 'State',                  1.5),
    ('column', 'Zip',                    1.5),
    ('column', 'Date Stamp',             1.5),
    ('column', 'DateTime Stamp',         1.5),
    ('column', 'Process Date Stamp',     1.0),
    ('column', 'Process DateTime Stamp', 1.0),
    ('column', 'Transactional Date',     1.5),
    ('column', 'Measurement',            1.5),
    ('column', 'Measurement Pct',        1.5),
    ('column', 'Code',                   1.5),
    ('column', 'Boolean',                1.0),
    ('column', 'Category',               1.0),
    ('column', 'Flag',                   0.75),
    ('column', 'Attribute',              0.75),
    ('column', 'Description',            0.5),
    ('column', 'Constant',               0.5),
    ('column', 'Sequence',               0.5);

-- PII-level defaults (matched on LEFT(pii_flag, 1))
-- A/B/C = auto-detected risk tiers; M = user-set 'MANUAL'
INSERT INTO dq_score_weight_defaults (weight_scope, semantic_type, default_weight) VALUES
    ('pii', 'A', 3.0),
    ('pii', 'B', 2.0),
    ('pii', 'C', 1.5),
    ('pii', 'M', 3.0);
