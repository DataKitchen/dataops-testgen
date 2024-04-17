
-- The following functions are inline functions
-- INLINE FUNCTION TO CHECK FOR A NUMBER

WITH FUNCTION num_check(a varchar)
    RETURNS integer
    RETURN
    CASE WHEN regexp_like(a, '^[0-9]+(\.[0-9]+)?$')  = TRUE THEN 1
    WHEN regexp_like(a, '\$[0-9]+(\.[0-9]+)?$') = TRUE THEN 1
    WHEN regexp_like(a, '^[0-9]+(\.[0-9]+)?\$') = TRUE THEN 1
    ELSE 0
END
SELECT num_check('1234567'), num_check('$45.945843'), num_check('0.123$');


-- INLINE FUNCTION TO CHECK FOR A DATE

WITH FUNCTION date_check(a varchar)
    RETURNS integer
    RETURN
    CASE WHEN REGEXP_LIKE(a, '^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])\s(2[0-3]|[01][0-9]):([0-5][0-9]):([0-5][0-9])(\s[0-9]{6})?$')
    THEN CASE WHEN CAST(SUBSTRING(a, 1, 4) AS INT) BETWEEN 1800 AND 2200
    AND( ( SUBSTRING(a, 6, 2) IN ('01', '03', '05', '07', '08', '10', '12')
    AND CAST(SUBSTRING(a, 9, 2) AS INT) BETWEEN 1 AND 31)
    OR (SUBSTRING(a, 6, 2) IN ('04', '06', '09') AND CAST(SUBSTRING(a, 9, 2) AS INT) BETWEEN 1 AND 30)
    OR (SUBSTRING(a, 6, 2) = '02' AND CAST(SUBSTRING(a, 9, 2) AS INT)  BETWEEN 1 AND 29)
    )
    THEN 1
    ELSE 0
END
WHEN REGEXP_LIKE(a, '^(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(2[0-3]|[01][0-9])([0-5][0-9])([0-5][0-9])([0-9]{6})$')
             OR REGEXP_LIKE(a, '^(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])$')
         THEN CASE WHEN CAST(SUBSTRING(a, 1, 4) AS INT) BETWEEN 1800 AND 2200
                        AND ( (SUBSTRING(a, 5, 2) IN ('01', '03', '05', '07', '08', '10', '12')
                                    AND CAST(SUBSTRING(a, 7, 2) AS INT) BETWEEN 1 AND 31)
                               OR (SUBSTRING(a, 5, 2) IN ('04', '06', '09') AND CAST(SUBSTRING(a, 7, 2) AS INT) BETWEEN 1 AND 30)
                               OR (SUBSTRING(a, 5, 2) = '02' AND CAST(SUBSTRING(a, 7, 2) AS INT) BETWEEN 1 AND 29)
                            )
                    THEN 1
                    ELSE 0
END
WHEN LENGTH(a) > 11 THEN 0
        WHEN REGEXP_LIKE(REGEXP_REPLACE(UPPER(a), '(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)', '12'), '[12][09][0-9][0-9]-[0-1]?[0-9]-[0-3]?[0-9]')
        THEN CASE WHEN CAST(SPLIT_PART(a, '-', 1) AS INT) BETWEEN 1800 AND 2200
                        AND ( (UPPER(SPLIT_PART(a, '-', 2)) IN ('01', '03', '05', '07', '08',
                                                           '1', '3', '5', '7', '8', '10', '12',
                                                           'JAN', 'MAR', 'MAY', 'JUL', 'AUG',
                                                           'OCT', 'DEC')
                                AND CAST(SPLIT_PART(a, '-', 3) AS INT) BETWEEN 1 AND 31)
                            OR (UPPER(SPLIT_PART(a, '-', 2)) IN ('04', '06', '09', '4', '6', '9', '11', 'APR', 'JUN', 'SEP', 'NOV')
                                AND CAST(SPLIT_PART(a, '-', 3) AS INT) BETWEEN 1 AND 30)
                            OR (UPPER(SPLIT_PART(a, '-', 2)) IN ('02', '2', 'FEB') AND CAST(SPLIT_PART(a, '-', 3) AS INT) BETWEEN 1 AND 29)
                        )
                    THEN 1
                    ELSE 0
END
WHEN REGEXP_LIKE(REPLACE(a, '-', '/') , '^[0-1]?[0-9]/[0-3]?[0-9]/[12][09][0-9][0-9]$')
             OR REGEXP_LIKE(REPLACE(a, '-', '/') , '^[0-1]?[0-9]/[0-3]?[0-9]/[0-9][0-9]$')
        THEN CASE WHEN CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 1) AS INT) BETWEEN 1 AND 12
                        AND ( (CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 1) AS INT) IN (1, 3, 5, 7, 8, 10, 12)
                                    AND CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 2) AS INT)  BETWEEN 1 AND 31)
                              OR (CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 1) AS INT) IN (4, 6, 9, 11)
                                    AND CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 2) AS INT)  BETWEEN 1 AND 30)
                              OR (CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 1) AS INT) = 2
                                    AND CAST(SPLIT_PART(REPLACE(a, '-', '/'), '/', 2) AS INT)  BETWEEN 1 AND 29)
                        )
                        AND CAST(('20' || SUBSTRING(SPLIT_PART(REPLACE(a, '-', '/'), '/', 3), -2 )) AS INT) BETWEEN 1800 AND 2200
                   THEN 1
                   ELSE 0
END
WHEN REGEXP_LIKE(UPPER(a) , '[0-3]?[0-9]-(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)-[12][09][0-9][0-9]')
        THEN CASE WHEN CAST(SPLIT_PART(a, '-', 3) AS INT) BETWEEN 1800 AND 2200
                        AND ( (UPPER(SPLIT_PART(a, '-', 2)) IN ('JAN', 'MAR', 'MAY', 'JUL', 'AUG', 'OCT', 'DEC')
                                    AND CAST(SPLIT_PART(a, '-', 1) AS INT) BETWEEN 1 AND 31)
                              OR (UPPER(SPLIT_PART(a, '-', 2)) IN ('APR', 'JUN', 'SEP', 'NOV')
                                    AND CAST(SPLIT_PART(a, '-', 1) AS INT) BETWEEN 1 AND 30)
                              OR (UPPER(SPLIT_PART(a, '-', 2)) = 'FEB'
                                    AND CAST(SPLIT_PART(a, '-', 1) AS INT) BETWEEN 1 AND 29)
                        )
                   THEN 1
                   ELSE 0
END
ELSE 0
END
SELECT date_check('2002-02-30 12:01:35'),
       date_check('2002-02-21 12:01:35 121324'),
       date_check('20100314224518304596'),
       date_check('20100230'),
       date_check('201002301234'),
       date_check('2010-03-30'), date_check('2010-MAR-30'),
       date_check('05-21-22'), date_check('10/23/2023'),
       date_check('10-SEP-2024');