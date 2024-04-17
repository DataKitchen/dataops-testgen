CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.datediff(difftype character varying, firstdate timestamp without time zone, seconddate timestamp without time zone) returns bigint
    language plpgsql
as
$$
   BEGIN
      RETURN
      CASE
        WHEN UPPER(difftype) IN ('DAY', 'DD')
              THEN DATE_PART('day', seconddate - firstdate)
        WHEN UPPER(difftype) IN ('WEEK','WK')
              THEN TRUNC(DATE_PART('day', seconddate - firstdate)/7)
        WHEN UPPER(difftype) IN ('MON', 'MM')
              THEN 12 * (DATE_PART('year', seconddate) - DATE_PART('year', firstdate))
                    + (DATE_PART('month', seconddate) - DATE_PART('month', firstdate))
        WHEN UPPER(difftype) IN ('QUARTER', 'QTR')
              THEN 4 * (DATE_PART('year', seconddate) - DATE_PART('year', firstdate))
                    + (DATE_PART('qtr', seconddate) - DATE_PART('month', firstdate))
        WHEN UPPER(difftype) IN ('YEAR', 'YY')
              THEN DATE_PART('year', seconddate) - DATE_PART('year', firstdate)
      END;
   END;
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_charcount(instring character varying, searchstring character varying) returns bigint
    language plpgsql
as
$$
   BEGIN
      RETURN (CHAR_LENGTH(instring) - CHAR_LENGTH(REPLACE(instring, searchstring, ''))) / CHAR_LENGTH(searchstring);
   END;
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_parsefreq(top_freq_values VARCHAR(1000), rowno INTEGER, colno INTEGER) returns VARCHAR(1000)
LANGUAGE SQL
STABLE
as
$$
    WITH first AS
    (
        SELECT SPLIT_PART(top_freq_values, CHR(10), rowno) AS first_row
    )
    SELECT
        CASE
            WHEN colno = 1 THEN CAST(TRIM(LEADING '|' FROM SUBSTRING(first_row, POSITION('|' IN first_row), LENGTH(first_row) - POSITION('|' IN REVERSE(first_row)))) AS VARCHAR)
            WHEN colno = 2 THEN CAST(TRIM(SUBSTRING(first_row, LENGTH(first_row) - POSITION('|' IN REVERSE(first_row)) + 2)) AS VARCHAR)
            ELSE NULL
            END
    FROM first
$$;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_PrepColumnName(value_to_check TEXT)
    RETURNS TEXT AS
$$
DECLARE
    keyword_arr TEXT[] := ARRAY ['ALL', 'ALTER', 'ANALYSE', 'ANALYZE', 'AND', 'ANY', 'ARRAY', 'AS', 'ASC', 'ASYMMETRIC',
                                 'AUTHORIZATION', 'BINARY', 'BOTH', 'CASE', 'CAST', 'CHECK', 'COLLATE', 'COLLATION',
                                 'COLUMN', 'CONCURRENTLY', 'CONSTRAINT', 'CREATE', 'CROSS', 'CURRENT_CATALOG',
                                 'CURRENT_DATE', 'CURRENT_ROLE', 'CURRENT_SCHEMA', 'CURRENT_TIME', 'CURRENT_TIMESTAMP',
                                 'CURRENT_USER', 'CREDENTIALS',
                                 'DEFAULT', 'DEFERRABLE', 'DESC', 'DISTINCT', 'DO', 'DROP',
                                 'ELSE', 'END', 'EXCEPT', 'FALSE', 'FETCH', 'FOR', 'FOREIGN', 'FREEZE', 'FROM', 'FULL',
                                 'GRANT', 'GROUP', 'HAVING', 'ILIKE', 'IN', 'INITIALLY', 'INNER', 'INTERSECT', 'INTO',
                                 'IS', 'ISNULL', 'JOIN', 'LATERAL', 'LEADING', 'LEFT', 'LIKE', 'LIMIT', 'LOCALTIME',
                                 'LOCALTIMESTAMP', 'NATURAL', 'NOT', 'NOTNULL', 'NULL', 'OFFSET', 'ON', 'ONLY', 'OR',
                                 'ORDER', 'OUTER', 'OVERLAPS', 'PLACING', 'PRIMARY', 'REFERENCES', 'RETURNING', 'RIGHT',
                                 'SELECT', 'SESSION_USER', 'SIMILAR', 'SOME', 'SYMMETRIC', 'TABLE', 'TABLESAMPLE',
                                 'THEN', 'TIMESTAMP', 'TIMEZONE', 'TO', 'TRAILING', 'TRUE', 'UNION', 'UNIQUE', 'USER', 'USING',
                                 'VARIADIC', 'VERBOSE', 'WHEN', 'WHERE', 'WINDOW', 'WITH']; -- Add more keywords here
BEGIN
    -- Check if the value matches any of the keywords (case-insensitive)
    IF value_to_check ILIKE ANY (keyword_arr) THEN
        RETURN '"' || value_to_check || '"';
    -- Check if the value contains a space or a comma or it starts with a number
    ELSIF value_to_check !~ '^[a-zA-Z_][a-zA-Z0-9_]*$' THEN
        RETURN '"' || value_to_check || '"';
    ELSE
        RETURN value_to_check;
    END IF;
END;
$$ LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_pct(numerator NUMERIC, denominator NUMERIC, decs INTEGER DEFAULT 0) returns NUMERIC
    language plpgsql
as
$$
   BEGIN
      RETURN ROUND((100.0 * numerator/denominator), decs);
   END;
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_quote_literal_escape(var_value varchar, sql_flavor varchar) RETURNS varchar
    LANGUAGE plpgsql
AS
$$
DECLARE
    escaped_value         varchar;
    lower_case_sql_flavor varchar;
BEGIN
    lower_case_sql_flavor := LOWER(sql_flavor);

    IF lower_case_sql_flavor = 'postgres'  OR lower_case_sql_flavor = 'postgresql' THEN
        escaped_value := QUOTE_LITERAL(var_value);
    ELSIF lower_case_sql_flavor = 'redshift' OR lower_case_sql_flavor = 'snowflake' THEN
        escaped_value := TRIM(LEADING 'E' FROM QUOTE_LITERAL(var_value));
    ELSIF lower_case_sql_flavor = 'mssql' THEN
        escaped_value := '''' || REPLACE(var_value, '''', '''''') || '''';
    ELSE
        RAISE EXCEPTION 'Invalid sql_flavor name: %', sql_flavor;
    END IF;

    RETURN escaped_value;
END;
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_format_csv_no_quotes(str_csv TEXT) returns TEXT
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT
        REGEXP_REPLACE(
                       REGEXP_REPLACE(str_csv::VARCHAR, '''', '', 'g'),  -- Remove single quotes
                       '\s*,\s*',  -- Match comma, with or without surrounding spaces
                       ', ',       -- Replace with comma followed by a space
                       'g'         -- Global replace
                      ) AS formatted_value
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_format_csv_quotes(str_csv TEXT) returns TEXT
LANGUAGE SQL
IMMUTABLE
as
$$
    SELECT
       '''' || REGEXP_REPLACE(str_csv::VARCHAR, '\s*,\s*', ''', ''', 'g') || ''''
   AS formatted_value
$$;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_count_intersecting_items(list1 VARCHAR, list2 VARCHAR, separator VARCHAR)
RETURNS BIGINT AS $$
SELECT COUNT(*)
FROM (
    SELECT unnest(string_to_array(list1, separator)) AS element
    INTERSECT
    SELECT unnest(string_to_array(list2, separator))
) AS intersection
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_extract_intersecting_items(list1 VARCHAR, list2 VARCHAR, separator VARCHAR)
RETURNS VARCHAR AS $$
SELECT STRING_AGG(DISTINCT element, separator) as shared_vals
FROM (
    SELECT unnest(string_to_array(list1, separator)) AS element
    INTERSECT
    SELECT unnest(string_to_array(list2, separator))
) AS intersection
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_extract_distinct_items(list VARCHAR, separator VARCHAR)
RETURNS VARCHAR AS $$
SELECT STRING_AGG(DISTINCT element, separator) as distinct_items
FROM (
    SELECT unnest(string_to_array(list, separator)) AS element
) AS all_items
$$ LANGUAGE sql;


CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_extract_top_values(input_string TEXT)
RETURNS TEXT AS $$
SELECT string_agg(trim(split_part(value, '|', 2)), '|') AS values_only
FROM (
  SELECT unnest(regexp_split_to_array(input_string, E'\n')) AS value
) AS t
WHERE trim(value) <> ''
$$ LANGUAGE sql;
