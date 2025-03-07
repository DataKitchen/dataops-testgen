SET SEARCH_PATH TO {SCHEMA_NAME};

ALTER TABLE connections ADD COLUMN http_path VARCHAR(200);

DROP FUNCTION IF EXISTS fn_PrepColumnName;

CREATE OR REPLACE FUNCTION {SCHEMA_NAME}.fn_quote_literal_escape(var_value varchar, sql_flavor varchar) RETURNS varchar
    LANGUAGE plpgsql
AS
$$
DECLARE
    escaped_value         varchar;
    lower_case_sql_flavor varchar;
BEGIN
    lower_case_sql_flavor := LOWER(sql_flavor);

    IF lower_case_sql_flavor IN ('postgres', 'postgresql') THEN
        escaped_value := QUOTE_LITERAL(var_value);
    ELSIF lower_case_sql_flavor IN ('redshift', 'snowflake') THEN
        escaped_value := TRIM(LEADING 'E' FROM QUOTE_LITERAL(var_value));
    ELSIF lower_case_sql_flavor = 'mssql' THEN
        escaped_value := '''' || REPLACE(var_value, '''', '''''') || '''';
    ELSIF lower_case_sql_flavor = 'databricks' THEN
        escaped_value := '''' || REPLACE(REPLACE(var_value, '\', '\\'), '''', '\''') || '''';
    ELSE
        RAISE EXCEPTION 'Invalid sql_flavor name: %', sql_flavor;
    END IF;

    RETURN escaped_value;
END;
$$;
