SET SEARCH_PATH TO {SCHEMA_NAME};

-- ==============================================================================
-- Layer 2 value-compliance anomaly types
-- These detect cases where column values violate the declared storage contract:
--   1032  Exceeds_Declared_Length    – varchar(n) column where max observed
--                                      length equals the declared limit,
--                                      indicating likely truncation at load time
--   1033  Numeric_Precision_Overflow – numeric(p,s) column where the observed
--                                      maximum value reaches 10^(p-s), leaving
--                                      no room for additional digits
--   1034  Decimal_In_Integer_Column  – integer-family column whose profiling
--                                      suggests the values actually require a
--                                      decimal type (datatype_suggestion is
--                                      numeric/decimal)
-- ==============================================================================

INSERT INTO profile_anomaly_types (
    id,
    anomaly_type,
    data_object,
    anomaly_name,
    anomaly_description,
    anomaly_criteria,
    detail_expression,
    detail_redactable,
    issue_likelihood,
    suggested_action,
    dq_dimension
)
VALUES
(
    '1032',
    'Exceeds_Declared_Length',
    'column',
    'Values at Declared Column Length Limit',
    'A character column''s maximum observed value length equals the column''s declared length, indicating values may have been silently truncated at load time or that the column is too narrow for the data it holds.',
    $crit$p.general_type = 'A'
   AND p.column_type ~ '\([0-9]+\)$'
   AND p.value_ct > 0
   AND p.max_length >= REGEXP_REPLACE(p.column_type, '^.*\(([0-9]+)\)$', '\1')::INTEGER$crit$,
    $det$'Declared Max Length: ' || REGEXP_REPLACE(p.column_type, '^.*\(([0-9]+)\)$', '\1')
    || ', Max Observed Length: ' || p.max_length::VARCHAR$det$,
    FALSE,
    'Likely',
    'Review source data lengths and compare with the declared column size. If values are being truncated, increase the column length or add a pre-load validation step.',
    'Validity'
),
(
    '1033',
    'Numeric_Precision_Overflow',
    'column',
    'Numeric Values Approach Declared Precision Limit',
    'A numeric(p,s) column has an observed maximum value that reaches or exceeds the maximum storable value given its declared precision and scale (10^(p-s)), risking arithmetic overflow or silent rounding on future inserts.',
    $crit$p.general_type = 'N'
   AND p.column_type ~ '^numeric\([0-9]+,[0-9]+\)$'
   AND p.max_value IS NOT NULL
   AND p.max_value >= POW(
           10,
           SPLIT_PART(REGEXP_REPLACE(p.column_type, '^numeric\(([0-9]+),([0-9]+)\)$', '\1,\2'), ',', 1)::INT
           - SPLIT_PART(REGEXP_REPLACE(p.column_type, '^numeric\(([0-9]+),([0-9]+)\)$', '\1,\2'), ',', 2)::INT
       )$crit$,
    $det$'Declared Type: ' || p.column_type
    || ', Max Storable Integer Part: ' || (
        POW(10, SPLIT_PART(REGEXP_REPLACE(p.column_type, '^numeric\(([0-9]+),([0-9]+)\)$', '\1,\2'), ',', 1)::INT
                - SPLIT_PART(REGEXP_REPLACE(p.column_type, '^numeric\(([0-9]+),([0-9]+)\)$', '\1,\2'), ',', 2)::INT) - 1
    )::BIGINT::VARCHAR
    || ', Max Observed Value: ' || p.max_value::VARCHAR$det$,
    FALSE,
    'Likely',
    'Increase the declared precision of the column (e.g. numeric(14,2) instead of numeric(10,2)) to accommodate the observed data range, or investigate whether the large values are data quality errors.',
    'Accuracy'
),
(
    '1034',
    'Decimal_In_Integer_Column',
    'column',
    'Integer Column Contains Decimal Values',
    'A column declared as an integer type (or numeric with scale 0) has profiling results that suggest its values actually require decimal storage. This indicates the column type does not match the data it holds.',
    $crit$p.general_type = 'N'
   AND (
         p.column_type IN ('integer','int','int4','int8','bigint','smallint','int2','tinyint')
      OR p.column_type ~ '^numeric\([0-9]+,\s*0\)$'
   )
   AND p.datatype_suggestion IS NOT NULL
   AND p.datatype_suggestion ILIKE 'numeric%'$crit$,
    $det$'Declared Type: ' || p.column_type
    || ', Suggested Type: ' || p.datatype_suggestion
    || ', Max Value: ' || p.max_value::VARCHAR$det$,
    FALSE,
    'Definite',
    'Change the column type to NUMERIC or DECIMAL with an appropriate scale, or investigate whether the source system is sending fractional values that should be rounded before loading.',
    'Validity'
)
ON CONFLICT (id) DO NOTHING;
