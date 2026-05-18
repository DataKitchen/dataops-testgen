SET SEARCH_PATH TO {SCHEMA_NAME};

-- Loosen fn_eval's numeric token pattern to accept leading-dot decimals
-- (e.g. ".733"). Oracle's NUMBER -> VARCHAR2 conversion drops the leading
-- zero for |x| < 1, and the value flows verbatim into test_results.result_measure
-- (VARCHAR), so the DQ scoring prevalence formula like
--   2.0 * (1.0 - fn_normal_cdf(ABS({RESULT_MEASURE}::FLOAT) / 2.0))
-- fed ".733..." to fn_eval, which rejected it as "invalid token \".\"".

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_eval(expression TEXT) RETURNS FLOAT
AS
$$
DECLARE
   result FLOAT;
   invalid_parts TEXT;
BEGIN
   -- Check the modified expression for invalid characters, allowing colons
   IF expression ~* E'[^0-9+\\-*/(),.\\sA-Z_:e\\\'"]' THEN
      RAISE EXCEPTION 'Invalid characters detected in expression: %', expression;
   END IF;

   -- Check for dangerous PostgreSQL-specific keywords
   IF expression ~* E'\b(DROP|ALTER|INSERT|UPDATE|DELETE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE|CREATE|COMMENT|SECURITY|WITH|SET ROLE|SET SESSION|DO|CALL|--|/\\*|;|pg_read_file|pg_write_file|pg_terminate_backend)\b' THEN
      RAISE EXCEPTION 'Invalid expression: dangerous statement detected';
   END IF;

   -- Remove all allowed tokens from the validation expression, treating 'FLOAT' as a keyword.
   -- Numeric pattern accepts leading-dot decimals (e.g. ".733") that Oracle emits
   -- when converting NUMBER values with |x| < 1 to VARCHAR2.
   invalid_parts := regexp_replace(
      expression,
      E'(\\mGREATEST|LEAST|ABS|FN_NORMAL_CDF|DATEDIFF|DAY|FLOAT|NULLIF)\\M|([0-9]+\\.?[0-9]*|\\.[0-9]+)([eE][+-]?[0-9]+)?|[+\\-*/(),\\\'":]+|\\s+',
      '',
      'gi'
   );

   -- If anything is left in the validation expression, it's invalid
   IF invalid_parts <> '' THEN
      RAISE EXCEPTION 'Invalid expression contains invalid tokens "%" in expression: %', invalid_parts, expression;
   END IF;

   -- Use the original expression (with ::FLOAT) for execution
   EXECUTE format('SELECT (%s)::FLOAT', expression) INTO result;

   RETURN result;
END;
$$
LANGUAGE plpgsql;
