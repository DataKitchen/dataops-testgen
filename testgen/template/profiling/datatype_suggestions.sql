UPDATE profile_results pr
SET datatype_suggestion =
  CASE
    WHEN pr.record_ct > 500
         AND pr.column_name NOT ILIKE '%id'
    THEN
      CASE base.general_type
        WHEN 'A' THEN
          CASE
            -- ZIP codes
            WHEN pr.column_name ILIKE '%zip%'
                 AND pr.max_length <= 10
            THEN 'VARCHAR('
                 || COALESCE(LEAST(10, base.current_size), 10)::text
                 || ')'

            -- Small and Predictable
            WHEN pr.functional_data_type IN ('State', 'Boolean')
            THEN 'VARCHAR(' || max_length::VARCHAR || ')'

            WHEN pr.functional_data_type = 'Measurement Pct'
            THEN 'VARCHAR('
                 || COALESCE(GREATEST(6, max_length), 6)::text
                 || ')'

            -- DECIMALs
            WHEN pr.numeric_ct > 0
                 AND pr.value_ct = pr.numeric_ct + pr.zero_length_ct
                 AND POSITION('.' IN pr.top_freq_values) > 0
            THEN 'DECIMAL(18,4)'

            -- small/big integers
            WHEN pr.numeric_ct > 0
                 AND pr.value_ct = pr.numeric_ct + pr.zero_length_ct
                 AND pr.max_length <= 6
                 AND POSITION('.' IN pr.top_freq_values) = 0
            THEN 'INTEGER'
            WHEN pr.numeric_ct > 0
                 AND pr.value_ct = pr.numeric_ct + pr.zero_length_ct
                 AND pr.max_length  > 6
                 AND POSITION('.' IN pr.top_freq_values) = 0
            THEN 'BIGINT'

            -- timestamps with zone
            WHEN pr.date_ct > 0
                 AND pr.value_ct = pr.date_ct + pr.zero_length_ct
                 AND POSITION('+' IN pr.top_freq_values) > 0
            THEN CASE
                   WHEN '{SQL_FLAVOR}' = 'redshift' THEN 'TIMESTAMPZ'
                   WHEN '{SQL_FLAVOR}' = 'postgresql' THEN 'TIMESTAMPZ'
                   WHEN '{SQL_FLAVOR}' = 'snowflake' THEN 'TIMESTAMP_TZ'
                   WHEN '{SQL_FLAVOR}' LIKE 'mssql%' THEN 'DATETIMEOFFSET'
                   WHEN '{SQL_FLAVOR}' = 'databricks' THEN 'TIMESTAMP'
                   WHEN '{SQL_FLAVOR}' = 'bigquery' THEN 'TIMESTAMP'
                   ELSE 'TIMESTAMPZ'
                 END

            -- timestamps without zone
            WHEN pr.date_ct > 0
                 AND pr.value_ct = pr.date_ct + pr.zero_length_ct
                 AND POSITION(':' IN pr.top_freq_values) > 0
            THEN CASE
                   WHEN '{SQL_FLAVOR}' = 'redshift' THEN 'TIMESTAMP'
                   WHEN '{SQL_FLAVOR}' = 'postgresql' THEN 'TIMESTAMP'
                   WHEN '{SQL_FLAVOR}' = 'snowflake' THEN 'TIMESTAMP_NTZ'
                   WHEN '{SQL_FLAVOR}' LIKE 'mssql%' THEN 'DATETIME2'
                   WHEN '{SQL_FLAVOR}' = 'databricks' THEN 'TIMESTAMP_NTZ'
                   WHEN '{SQL_FLAVOR}' = 'bigquery' THEN 'DATETIME'
                   ELSE 'TIMESTAMP_NTZ'
                 END

            -- pure dates
            WHEN pr.date_ct > 0
                 AND pr.value_ct = pr.date_ct + pr.zero_length_ct
            THEN 'DATE'

            -- very short text → suggest VARCHAR(10)
            WHEN pr.max_length <= 5
            THEN 'VARCHAR('
                 || COALESCE(LEAST(10, base.current_size), 10)::text
                 || ')'

            -- fallback text → adaptive bucket
            WHEN pr.max_length IS NOT NULL
            THEN
              'VARCHAR('
              || COALESCE(
                   LEAST(
                     -- computed_bucket:
                     (CASE
                        WHEN pr.max_length <= 50
                        THEN CEIL((pr.max_length + 5)/10.0) * 10
                        ELSE ((1 + TRUNC((pr.max_length + 10)/20.0, 0)) * 20)
                      END)::int,
                     base.current_size
                   ),
                   -- fallback if current_size IS NULL
                   (CASE
                      WHEN pr.max_length <= 50
                      THEN CEIL(pr.max_length/10.0) * 10
                      ELSE ((1 + TRUNC((pr.max_length + 10)/20.0, 0)) * 20)
                    END)::int
                 )::text
              || ')'

            ELSE
              lower(pr.column_type)
          END

        WHEN 'N' THEN
          CASE
            WHEN RTRIM(SPLIT_PART(pr.column_type, ',', 2),')') > '0'
                 AND pr.fractional_sum = 0
                 AND pr.min_value >= -100
                 AND pr.max_value <=  100
            THEN 'SMALLINT'

            WHEN RTRIM(SPLIT_PART(pr.column_type, ',', 2),')') > '0'
                 AND pr.fractional_sum = 0
                 AND pr.min_value >= -100000000
                 AND pr.max_value <= 100000000
            THEN 'INTEGER'

            WHEN RTRIM(SPLIT_PART(pr.column_type, ',', 2),')') > '0'
                 AND pr.fractional_sum = 0
                 AND (pr.min_value < -100000000
                      OR pr.max_value > 100000000)
            THEN 'BIGINT'

            ELSE
              lower(pr.column_type)
          END

        ELSE
          lower(pr.column_type)
      END
    ELSE
      lower(pr.column_type)
  END
FROM (
  SELECT
    id,
    general_type,
    -- pull out declared size if present, else NULL
    CAST(substring(column_type FROM '\((\d+)\)') AS int) AS current_size
  FROM profile_results
  WHERE project_code = :PROJECT_CODE
    AND schema_name   = :DATA_SCHEMA
    AND run_date      = :RUN_DATE
) AS base
WHERE pr.id = base.id;
