-- Step 2: Create isnum function
CREATE FUNCTION {DATA_QC_SCHEMA}.fndk_isnum (@strparm VARCHAR(500))
RETURNS INT
AS
BEGIN
	IF TRY_CAST(NULLIF(@strparm, '') AS float) IS NOT NULL
	BEGIN
	    RETURN(1)
	END

	RETURN(0)
END;
