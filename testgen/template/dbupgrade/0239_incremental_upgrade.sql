SET SEARCH_PATH TO {SCHEMA_NAME};

-- Zip3 and Zip US/CA columns weigh the same as Zip columns.
INSERT INTO dq_score_weight_defaults (weight_scope, semantic_type, default_weight) VALUES
    ('column', 'Zip3',      1.5),
    ('column', 'Zip US/CA', 1.5)
ON CONFLICT (weight_scope, semantic_type) DO NOTHING;
