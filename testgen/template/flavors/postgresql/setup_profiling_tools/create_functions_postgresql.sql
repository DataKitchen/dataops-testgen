CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.DATEDIFF(difftype character varying, firstdate timestamp without time zone, seconddate timestamp without time zone)
RETURNS BIGINT AS $$
    SELECT
       CASE
        WHEN UPPER(difftype) IN ('DAY', 'DD', 'D') THEN
            DATE(seconddate) - DATE(firstdate)
        WHEN UPPER(difftype) IN ('WEEK','WK', 'W') THEN
            (DATE(seconddate) - DATE(firstdate)) / 7
        WHEN UPPER(difftype) IN ('MON', 'MONTH', 'MM') THEN
            (DATE_PART('year', seconddate) - DATE_PART('year', firstdate)) * 12 + (DATE_PART('month', seconddate) - DATE_PART('month', firstdate))
        WHEN UPPER(difftype) IN ('QUARTER', 'QTR', 'Q') THEN
            ((DATE_PART('year', seconddate) - DATE_PART('year', firstdate)) * 4) + (DATE_PART('quarter', seconddate) - DATE_PART('quarter', firstdate))
        WHEN UPPER(difftype) IN ('YEAR', 'YY', 'Y') THEN
            DATE_PART('year', seconddate) - DATE_PART('year', firstdate)
        ELSE
            NULL::BIGINT
    END;
$$ LANGUAGE sql IMMUTABLE STRICT;

CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fn_charcount(instring character varying, searchstring character varying) returns bigint
    language plpgsql
as
$$
   BEGIN
      RETURN (CHAR_LENGTH(instring) - CHAR_LENGTH(REPLACE(instring, searchstring, ''))) / CHAR_LENGTH(searchstring);
   END;
$$;


CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fn_parsefreq(top_freq_values VARCHAR(1000), rowno INTEGER, colno INTEGER) returns VARCHAR(1000)
    language plpgsql
as
$$
   BEGIN
      RETURN SPLIT_PART(SPLIT_PART(top_freq_values, CHR(10), rowno), '|', colno+1);
   END;
$$;


CREATE
OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isnum(VARCHAR)
          RETURNS INTEGER
          IMMUTABLE
        AS
        $$
SELECT CASE
            WHEN $1 ~ E'^\\s*[+-]?\\$?\\s*[0-9]+(,[0-9]{3})*(\\.[0-9]*)?[\\%]?\\s*$' THEN 1
            ELSE 0
        END;
$$
LANGUAGE sql;





CREATE
OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isdate(VARCHAR)
          RETURNS INTEGER
          IMMUTABLE
        AS $$
SELECT CASE
           -- YYYY-MM-DD HH:MM:SS SSSSSS or YYYY-MM-DD HH:MM:SS
           WHEN $1 ~ '^(\\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])\\s(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\\s[0-9]{6})?$'
                             THEN CASE
                                                         WHEN LEFT($1, 4):: INT BETWEEN 1800 AND 2200
    AND (
    ( SUBSTRING ($1, 6, 2) IN ('01', '03', '05', '07', '08',
    '10', '12')
    AND SUBSTRING ($1, 9, 2):: INT BETWEEN 1 AND 31 )
    OR ( SUBSTRING ($1, 6, 2) IN ('04', '06', '09')
    AND SUBSTRING ($1, 9, 2):: INT BETWEEN 1 AND 30 )
    OR ( SUBSTRING ($1, 6, 2) = '02'
    AND SUBSTRING ($1, 9, 2):: INT :: INT BETWEEN 1 AND 29)
    )
    THEN 1
    ELSE 0
END
                        -- YYYYMMDDHHMMSSSSSS or YYYYMMDD
WHEN $1 ~ '^(\\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(2[0-3]|[01][0-9])([0-5][0-9])([0-5][0-9])([0-9]{6})$'
  OR $1 ~ '^(\\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(2[0-3]|[01][0-9])$'
                             THEN CASE
                                   WHEN LEFT($1, 4)::INT BETWEEN 1800 AND 2200
                                       AND (
                                            ( SUBSTRING($1, 5, 2) IN ('01', '03', '05', '07', '08',
                                                                                '10', '12')
                                               AND SUBSTRING($1, 7, 2)::INT BETWEEN 1 AND 31 )
                                           OR  ( SUBSTRING($1, 5, 2) IN ('04', '06', '09')
                                                  AND SUBSTRING($1, 7, 2)::INT BETWEEN 1 AND 30 )
                                           OR  ( SUBSTRING($1, 5, 2)  = '02'
                                                  AND SUBSTRING($1, 7, 2)::INT::INT BETWEEN 1 AND 29)
                                           )
                                      THEN 1
                                     ELSE 0
END
                        -- Exclude anything else long
WHEN LENGTH($1) > 11 THEN 0
                        -- YYYY-MMM/MM-DD
                        WHEN REGEXP_REPLACE(UPPER($1), '(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', '12', 'g')
                               ~ '[12][09][0-9][0-9]-[0-1]?[0-9]-[0-3]?[0-9]'
                            THEN CASE
                                   WHEN SPLIT_PART($1, '-', 1)::INT BETWEEN 1800 AND 2200
                                       AND (
                                            ( UPPER(SPLIT_PART($1, '-', 2)) IN ('01', '03', '05', '07', '08',
                                                                                '1', '3', '5', '7', '8', '10', '12',
                                                                                'JAN', 'MAR', 'MAY', 'JUL', 'AUG',
                                                                                'OCT', 'DEC')
                                               AND SPLIT_PART($1, '-', 3)::INT BETWEEN 1 AND 31 )
                                        OR  ( UPPER(SPLIT_PART($1, '-', 2)) IN ('04', '06', '09', '4', '6', '9', '11',
                                                                                'APR', 'JUN', 'SEP', 'NOV')
                                               AND SPLIT_PART($1, '-', 3)::INT BETWEEN 1 AND 30 )
                                        OR  ( UPPER(SPLIT_PART($1, '-', 2)) IN ('02', '2', 'FEB')
                                               AND SPLIT_PART($1, '-', 3)::INT BETWEEN 1 AND 29)
                                           )
                                      THEN 1
                                     ELSE 0
END
                        -- MM/-DD/-YY/YYYY
WHEN REPLACE($1, '-', '/') ~ '^[0-1]?[0-9]/[0-3]?[0-9]/[12][09][0-9][0-9]$'
                          OR REPLACE($1, '-', '/') ~ '^[0-1]?[0-9]/[0-3]?[0-9]/[0-9][0-9]$'
                             THEN
                                  CASE
                                    WHEN SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT BETWEEN 1 AND 12
                                     AND (
                                          ( SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT IN (1, 3, 5, 7, 8, 10, 12)
                                             AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 31 )
                                      OR  ( SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT IN (4, 6, 9, 11)
                                             AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 30 )
                                      OR  ( SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT = 2
                                             AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 29)
                                         )
                                     AND
                                         ('20' || RIGHT(SPLIT_PART(REPLACE($1, '-', '/'), '/', 3), 2))::INT BETWEEN 1800 AND 2200
                                    THEN 1
                                    ELSE 0
END
                        -- DD-MMM-YYYY
WHEN UPPER($1) ~ '[0-3]?[0-9]-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-[12][09][0-9][0-9]'
                          THEN
                               CASE
                                 WHEN SPLIT_PART($1, '-', 3)::INT BETWEEN 1800 AND 2200
                                     AND (
                                          ( UPPER(SPLIT_PART($1, '-', 2)) IN ('JAN', 'MAR', 'MAY', 'JUL', 'AUG', 'OCT', 'DEC')
                                             AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 31 )
                                      OR  ( UPPER(SPLIT_PART($1, '-', 2)) IN ('APR', 'JUN', 'SEP', 'NOV')
                                             AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 30 )
                                      OR  ( UPPER(SPLIT_PART($1, '-', 2)) = 'FEB'
                                             AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 29)
                                         )
                                   THEN 1
                                   ELSE 0
END
ELSE 0
END
as isdate
        $$
          LANGUAGE sql;
