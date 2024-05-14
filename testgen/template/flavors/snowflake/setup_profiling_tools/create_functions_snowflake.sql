CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isnum(strparm VARCHAR)
RETURNS INTEGER
LANGUAGE SQL
IMMUTABLE
AS
$$
SELECT CASE
            WHEN REGEXP_LIKE(strparm::VARCHAR, '^\\s*[+-]?\\$?\\s*[0-9]+(,[0-9]{3})*(\\.[0-9]*)?[\\%]?\\s*$') THEN 1
            ELSE 0
        END
$$;


CREATE OR REPLACE FUNCTION {DATA_QC_SCHEMA}.fndk_isdate(strparm VARCHAR)
RETURNS INTEGER
LANGUAGE SQL
IMMUTABLE
AS
$$
SELECT CASE
             -- YYYY-MM-DD HH:MM:SS SSSSSS
             WHEN TRY_TO_DATE(strparm, 'YYYY-MM-DD HH:MI:SS SSSSSS') IS NOT NULL THEN 1

             -- YYYY-MM-DD HH:MM:SS
             WHEN TRY_TO_DATE(strparm, 'YYYY-MM-DD HH:MI:SS') IS NOT NULL THEN 1

             -- YYYYMMDDHHMMSSSSSS
             WHEN TRY_TO_DATE(strparm, 'YYYYMMDDHHMISSSSSS') IS NOT NULL THEN 1

             -- YYYYMMDDHHMMSS
             WHEN TRY_TO_DATE(strparm, 'YYYYMMDDHHMISS') IS NOT NULL THEN 1

             -- YYYYMMDD
             WHEN LENGTH(strparm) = 8 AND TRY_TO_DATE(strparm, 'YYYYMMDD') IS NOT NULL THEN 1

             -- YYYY-MON-DD HH:MM:SS SSSSSS
             --WHEN TRY_TO_DATE(strparm, 'YYYY-MON-DD HH:MI:SS SSSSSS') IS NOT NULL THEN 1

              -- YYYY-MON-DD HH:MM:SS
             --WHEN TRY_TO_DATE(strparm, 'YYYY-MON-DD HH:MI:SS') IS NOT NULL THEN 1

              -- Exclude anything else long
              WHEN LENGTH(strparm) > 11 THEN 0

             -- YYYY-MON-DD
             WHEN TRY_TO_DATE(strparm, 'YYYY-MON-DD') IS NOT NULL THEN 1

             -- YYYY-MM-DD
             WHEN TRY_TO_DATE(strparm, 'YYYY-MM-DD') IS NOT NULL THEN 1

             -- MM/DD/YYYY
             WHEN TRY_TO_DATE(strparm, 'MM/DD/YYYY') IS NOT NULL THEN 1

             -- MM/DD/YY
             WHEN TRY_TO_DATE(strparm, 'MM/DD/YY') IS NOT NULL THEN 1

            --MM-DD-YYYY
            WHEN TRY_TO_DATE(strparm, 'MM-DD-YYYY') IS NOT NULL THEN 1

             --MM-DD-YY
             WHEN TRY_TO_DATE(strparm, 'MM-DD-YY') IS NOT NULL THEN 1

             --DD-MMM-YYYY
             WHEN TRY_TO_DATE(strparm, 'DD-MON-YYYY') IS NOT NULL THEN 1


              ELSE 0
              END
$$;
