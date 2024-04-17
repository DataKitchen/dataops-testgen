-- Step 3: Create isdate function

CREATE FUNCTION {DATA_QC_SCHEMA}.fndk_isdate(@strparm VARCHAR(500))
    RETURNS INT
AS
BEGIN
    DECLARE @ret INT

    SET @ret =

   CASE WHEN TRY_CAST(NULLIF(@strparm, '') AS float) IS NOT NULL
                    AND LEFT(NULLIF(@strparm, ''),4) BETWEEN 1800 AND 2200 THEN
                 CASE
                        WHEN LEN((NULLIF(@strparm, ''))) > 11 THEN 0
                        -- YYYYMMDD
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 112) IS NOT NULL THEN 1

                        -- YYYY-MM-DD
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 23) IS NOT NULL THEN 1

                        -- MM/DD/YYYY
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 101) IS NOT NULL THEN 1

                        -- MM/DD/YY
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 1) IS NOT NULL THEN 1

                        --MM-DD-YYYY
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 110) IS NOT NULL THEN 1

                        --MM-DD-YY
                        WHEN TRY_CONVERT(DATE, NULLIF(@strparm, ''), 10) IS NOT NULL THEN 1


                   ELSE 0 END
              --DD MMM YYYY
               WHEN (TRY_CONVERT(DATE, NULLIF(@strparm, ''), 106) IS NOT NULL
                   AND LEFT(NULLIF(@strparm, ''), 4)  BETWEEN 1800 AND 2200)
                   THEN 1

              -- YYYY-MM-DD HH:MM:SS SSSSSS
               WHEN (TRY_CONVERT(DATETIME2, NULLIF(@strparm, ''), 121) IS NOT NULL
                   AND LEFT(NULLIF(@strparm, ''), 4)  BETWEEN 1800 AND 2200)
                   THEN 1

              -- YYYY-MM-DD HH:MM:SS
               WHEN (TRY_CONVERT(DATETIME2, NULLIF(@strparm, ''), 120) IS NOT NULL
                   AND LEFT(NULLIF(@strparm, ''), 4)  BETWEEN 1800 AND 2200)
                   THEN 1
              ELSE 0
              END
	RETURN @ret

END
;
