SET SEARCH_PATH TO {SCHEMA_NAME};

-- Add impact_dimension as second classification axis for DQ scoring

ALTER TABLE test_types
    ADD COLUMN IF NOT EXISTS impact_dimension VARCHAR(20);

ALTER TABLE profile_anomaly_types
    ADD COLUMN IF NOT EXISTS impact_dimension VARCHAR(20);

ALTER TABLE test_definitions
    ADD COLUMN IF NOT EXISTS impact_dimension VARCHAR(20);

ALTER TABLE test_results
    ADD COLUMN IF NOT EXISTS impact_dimension VARCHAR(20);

ALTER TABLE profile_anomaly_results
    ADD COLUMN IF NOT EXISTS impact_dimension VARCHAR(20);

ALTER TABLE score_definition_results_breakdown
    ADD COLUMN IF NOT EXISTS impact_dimension TEXT DEFAULT NULL;

-- Populate impact_dimension on test_types from default assignments
UPDATE test_types SET impact_dimension = 'Reliability' WHERE test_type IN (
    'Daily_Record_Ct', 'Distinct_Date_Ct', 'Monthly_Rec_Ct', 'Recency', 'Row_Ct',
    'Row_Ct_Pct', 'Weekly_Rec_Ct', 'Aggregate_Balance', 'Aggregate_Balance_Percent',
    'Aggregate_Balance_Range', 'Timeframe_Combo_Gain', 'Timeframe_Combo_Match',
    'Table_Freshness', 'Schema_Drift', 'Volume_Trend', 'Freshness_Trend'
);
UPDATE test_types SET impact_dimension = 'Conformance' WHERE test_type IN (
    'Alpha_Trunc', 'Condition_Flag', 'Constant', 'CUSTOM', 'Dec_Trunc', 'Email_Format',
    'Future_Date', 'Future_Date_1Y', 'LOV_All', 'LOV_Match', 'Min_Date', 'Min_Val',
    'Pattern_Match', 'Required', 'Street_Addr_Pattern', 'Unique', 'Unique_Pct',
    'US_State', 'Valid_Month', 'Valid_US_Zip', 'Valid_US_Zip3', 'Aggregate_Minimum',
    'Combo_Match', 'Dupe_Rows'
);
UPDATE test_types SET impact_dimension = 'Regularity' WHERE test_type IN (
    'Avg_Shift', 'Distinct_Value_Ct', 'Incr_Avg_Shift', 'Missing_Pct',
    'Outlier_Pct_Above', 'Outlier_Pct_Below', 'Variability_Increase',
    'Variability_Decrease', 'Distribution_Shift', 'Metric_Trend'
);
UPDATE test_types SET impact_dimension = 'Usability' WHERE test_type IN (
    'Valid_Characters'
);

-- Populate impact_dimension on profile_anomaly_types from default assignments
UPDATE profile_anomaly_types SET impact_dimension = 'Conformance' WHERE anomaly_type IN (
    'No_Values', 'Invalid_Zip_USA', 'Unexpected_US_States', 'Unexpected_Emails',
    'Invalid_Zip3_USA', 'Non_Alpha_Name_Address', 'Non_Alpha_Prefixed_Name', 'Potential_PII'
);
UPDATE profile_anomaly_types SET impact_dimension = 'Regularity' WHERE anomaly_type IN (
    'Small_Missing_Value_Ct', 'Small_Divergent_Value_Ct', 'Potential_Duplicates',
    'Unlikely_Date_Values', 'Recency_One_Year', 'Recency_Six_Months', 'Small_Numeric_Value_Ct'
);
UPDATE profile_anomaly_types SET impact_dimension = 'Usability' WHERE anomaly_type IN (
    'Suggested_Type', 'Non_Standard_Blanks', 'Multiple_Types_Minor', 'Multiple_Types_Major',
    'Column_Pattern_Mismatch', 'Table_Pattern_Mismatch', 'Leading_Spaces', 'Quoted_Values',
    'Char_Column_Number_Values', 'Char_Column_Date_Values', 'Boolean_Value_Mismatch',
    'Standardized_Value_Matches', 'Delimited_Data_Embedded', 'Char_Column_Number_Units',
    'Variant_Coded_Values', 'Inconsistent_Casing', 'Non_Printing_Chars'
);

-- Backfill test_results from test_types (no definition override on historical data)
UPDATE test_results tr
SET impact_dimension = tt.impact_dimension
FROM test_types tt
WHERE tr.test_type = tt.test_type;

-- Backfill profile_anomaly_results from profile_anomaly_types
UPDATE profile_anomaly_results ar
SET impact_dimension = at.impact_dimension
FROM profile_anomaly_types at
WHERE ar.anomaly_id = at.id;
