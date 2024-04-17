-- Step 1: Drop both functions if they exist
BEGIN
    IF OBJECT_ID('{DATA_QC_SCHEMA}.fndk_isnum', 'FN') IS NOT NULL
        DROP FUNCTION {DATA_QC_SCHEMA}.fndk_isnum;

    IF OBJECT_ID('{DATA_QC_SCHEMA}.fndk_isdate', 'FN') IS NOT NULL
        DROP FUNCTION {DATA_QC_SCHEMA}.fndk_isdate;
END
