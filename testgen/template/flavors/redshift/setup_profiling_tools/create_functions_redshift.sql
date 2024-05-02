CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isnum(VARCHAR)
          RETURNS INTEGER
          IMMUTABLE
        AS
        $$
SELECT CASE
            WHEN $1 ~ '^\\s*[+-]?\\$?\\s*[0-9]+(,[0-9]{3})*(\\.[0-9]*)?[\\%]?\\s*$'   THEN 1
            ELSE 0
        END;
$$
LANGUAGE sql;


CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isdate(VARCHAR)
          RETURNS INTEGER
          IMMUTABLE
        AS $$
SELECT CASE
          -- YYYY-MM-DD HH:MM:SS SSSSSS or YYYY-MM-DD HH:MM:SS
          WHEN $1 ~
               '^(\\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])\\s(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\\s[0-9]{6})?$'
                               THEN CASE
                                        WHEN LEFT($1, 4):: INT BETWEEN 1800 AND 2200
                                           AND (
                                                   (SUBSTRING($1, 6, 2) IN ('01', '03', '05', '07', '08',
                                                                            '10', '12')
                                                      AND SUBSTRING($1, 9, 2):: INT BETWEEN 1 AND 31)
                                                   OR (SUBSTRING($1, 6, 2) IN ('04', '06', '09')
                                                   AND SUBSTRING($1, 9, 2):: INT BETWEEN 1 AND 30)
                                                   OR (SUBSTRING($1, 6, 2) = '02'
                                                   AND SUBSTRING($1, 9, 2):: INT :: INT BETWEEN 1 AND 29)
                                                )
                                           THEN 1
                                           ELSE 0
                                    END
          -- YYYYMMDDHHMMSSSSSS or YYYYMMDD
          WHEN $1 ~
               '^(\\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(2[0-3]|[01][0-9])([0-5][0-9])([0-5][0-9])([0-9]{6})$'
            OR $1 ~ '^(\\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(2[0-3]|[01][0-9])$'
                               THEN CASE
                                      WHEN LEFT($1, 4)::INT BETWEEN 1800 AND 2200
                                       AND (
                                             (SUBSTRING($1, 5, 2) IN ('01', '03', '05', '07', '08',
                                                                      '10', '12')
                                                AND SUBSTRING($1, 7, 2)::INT BETWEEN 1 AND 31)
                                             OR (SUBSTRING($1, 5, 2) IN ('04', '06', '09')
                                             AND SUBSTRING($1, 7, 2)::INT BETWEEN 1 AND 30)
                                             OR (SUBSTRING($1, 5, 2) = '02'
                                             AND SUBSTRING($1, 7, 2)::INT::INT BETWEEN 1 AND 29)
                                            )
                                         THEN 1
                                         ELSE 0
                                    END
          -- Exclude anything else long
          WHEN LENGTH($1) > 11 THEN 0
          -- YYYY-MMM/MM-DD
          WHEN REGEXP_REPLACE(UPPER($1), '(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', '12')
             ~ '[12][09][0-9][0-9]-[0-1]?[0-9]-[0-3]?[0-9]'
                               THEN CASE
             WHEN SPLIT_PART($1, '-', 1)::INT BETWEEN 1800 AND 2200
                AND (
                        (UPPER(SPLIT_PART($1, '-', 2)) IN ('01', '03', '05', '07', '08',
                                                           '1', '3', '5', '7', '8', '10', '12',
                                                           'JAN', 'MAR', 'MAY', 'JUL', 'AUG',
                                                           'OCT', 'DEC')
                           AND SPLIT_PART($1, '-', 3)::INT BETWEEN 1 AND 31)
                        OR (UPPER(SPLIT_PART($1, '-', 2)) IN ('04', '06', '09', '4', '6', '9', '11',
                                                              'APR', 'JUN', 'SEP', 'NOV')
                        AND SPLIT_PART($1, '-', 3)::INT BETWEEN 1 AND 30)
                        OR (UPPER(SPLIT_PART($1, '-', 2)) IN ('02', '2', 'FEB')
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
                           (SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT IN (1, 3, 5, 7, 8, 10, 12)
                              AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 31)
                           OR (SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT IN (4, 6, 9, 11)
                           AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 30)
                           OR (SPLIT_PART(REPLACE($1, '-', '/'), '/', 1)::INT = 2
                           AND SPLIT_PART(REPLACE($1, '-', '/'), '/', 2)::INT BETWEEN 1 AND 29)
                        )
                   AND
                     ('20' + RIGHT(SPLIT_PART(REPLACE($1, '-', '/'), '/', 3), 2))::INT BETWEEN 1800 AND 2200
                   THEN 1
                   ELSE 0
             END
          -- DD-MMM-YYYY
          WHEN UPPER($1) ~ '[0-3]?[0-9]-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-[12][09][0-9][0-9]'
                               THEN
             CASE
                WHEN SPLIT_PART($1, '-', 3)::INT BETWEEN 1800 AND 2200
                   AND (
                           (UPPER(SPLIT_PART($1, '-', 2)) IN ('JAN', 'MAR', 'MAY', 'JUL', 'AUG', 'OCT', 'DEC')
                              AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 31)
                           OR (UPPER(SPLIT_PART($1, '-', 2)) IN ('APR', 'JUN', 'SEP', 'NOV')
                           AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 30)
                           OR (UPPER(SPLIT_PART($1, '-', 2)) = 'FEB'
                           AND SPLIT_PART($1, '-', 1)::INT BETWEEN 1 AND 29)
                        )
                   THEN 1
                   ELSE 0
             END
                               ELSE 0
       END
          AS isdate;
        $$
          LANGUAGE sql;
