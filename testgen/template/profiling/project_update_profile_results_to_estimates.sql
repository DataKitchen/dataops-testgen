
-- Update sampled profile results for given profile_run to estimated values
-- We don't update distinct counts, because these should already be representative
-- in a random sample.

update profile_results
set sample_ratio = {PROFILE_SAMPLE_RATIO},
    record_ct = ROUND(record_ct * {PROFILE_SAMPLE_RATIO}, 0),
    value_ct = ROUND(value_ct * {PROFILE_SAMPLE_RATIO}, 0),
    -- distinct_value_ct = ROUND(record_ct * {PROFILE_SAMPLE_RATIO} *(distinct_value_ct::numeric/record_ct::numeric), 0),
    null_value_ct = ROUND(null_value_ct * {PROFILE_SAMPLE_RATIO}, 0),
    zero_value_ct = ROUND(zero_value_ct * {PROFILE_SAMPLE_RATIO}, 0),
    lead_space_ct = ROUND(lead_space_ct * {PROFILE_SAMPLE_RATIO}, 0),
    embedded_space_ct = ROUND(embedded_space_ct * {PROFILE_SAMPLE_RATIO}, 0),
    includes_digit_ct = ROUND(includes_digit_ct * {PROFILE_SAMPLE_RATIO}, 0),
    filled_value_ct = ROUND(filled_value_ct * {PROFILE_SAMPLE_RATIO}, 0),
    numeric_ct = ROUND(numeric_ct * {PROFILE_SAMPLE_RATIO}, 0),
    date_ct = ROUND(date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    before_1yr_date_ct = ROUND(before_1yr_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    before_5yr_date_ct = ROUND(before_5yr_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    before_20yr_date_ct = ROUND(before_20yr_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    within_1yr_date_ct = ROUND(within_1yr_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    within_1mo_date_ct = ROUND(within_1mo_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    future_date_ct = ROUND(future_date_ct * {PROFILE_SAMPLE_RATIO}, 0),
    boolean_true_ct = ROUND(boolean_true_ct * {PROFILE_SAMPLE_RATIO}, 0),
    date_days_present = ROUND(date_days_present * {PROFILE_SAMPLE_RATIO}, 0)
where profile_run_id = '{PROFILE_RUN_ID}'
and schema_name = split_part('{SAMPLING_TABLE}', '.', 1)
and table_name = split_part('{SAMPLING_TABLE}', '.', 2)
and sample_ratio IS NULL;


