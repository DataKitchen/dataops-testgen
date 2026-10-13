import re

from yaml import safe_load

from testgen.common.read_file import get_template_files

EXPECTED_PAIRS = {("Standard", t) for t in [
    "Alpha_Trunc", "Avg_Shift", "Constant", "Daily_Record_Ct", "Dec_Trunc", "Distinct_Date_Ct",
    "Distinct_Value_Ct", "Dupe_Rows", "Email_Format", "Future_Date", "Future_Date_1Y",
    "Incr_Avg_Shift", "LOV_Match", "Min_Date", "Min_Val", "Missing_Pct", "Monthly_Rec_Ct",
    "Outlier_Pct_Above", "Outlier_Pct_Below", "Pattern_Match", "Recency", "Required", "Required_No_Placeholder",
    "Street_Addr_Pattern", "US_State", "Unique", "Unique_Pct", "Valid_Characters", "Valid_Month",
    "Valid_US_Zip", "Valid_US_Zip3", "Variability_Decrease", "Variability_Increase", "Weekly_Rec_Ct",
]} | {("Monitor", t) for t in ["Schema_Drift", "Freshness_Trend", "Volume_Trend"]} | {("Contract", "Required_No_Placeholder")} | {
    ("Table Comparison", t) for t in [
        "Match_Row_Ct", "Match_Column_Ct", "Match_Column_Type", "Match_Null_Ct", "Match_Distinct_Ct",
        "Match_Min_Val", "Match_Max_Val", "Match_Zero_Ct", "Match_Sum", "Match_Stdev", "Match_Fractional_Sum",
        "Match_Min_Date", "Match_Max_Date", "Match_Distinct_Date_Ct", "Match_True_Ct", "Match_Min_Length",
        "Match_Max_Length", "Match_Total_Length", "Match_Lead_Space_Ct", "Match_Zero_Length_Ct", "Match_Upper_Case_Ct",
        "Match_Non_Printing_Ct", "Match_Distinct_Hash", "Match_Frequent_Values", "Match_Frequent_Patterns",
        "Match_Hash_Text", "Match_Hash_Num", "Match_Hash_Date", "Match_Epoch_Sum",
        "Match_Keyed_Hash_Text", "Match_Keyed_Hash_Num", "Match_Keyed_Hash_Date",
    ]
}


def _load_all_core_test_types():
    from importlib.resources import as_file
    for yaml_file in get_template_files(mask="^.*ya?ml$", sub_directory="dbsetup_test_types"):
        with as_file(yaml_file) as f, f.open("r") as fh:
            yield safe_load(fh)["test_types"]


def test_core_yaml_generation_sets_match_frozen_pairs():
    pairs = set()
    for tt in _load_all_core_test_types():
        for gs in tt.get("generation_sets", []) or []:
            pairs.add((gs, tt["test_type"]))
    assert pairs == EXPECTED_PAIRS


def test_050_no_longer_hardcodes_generation_sets_insert():
    from testgen.common.read_file import read_template_sql_file
    sql = read_template_sql_file("050_populate_new_schema_metadata.sql", "dbsetup")
    # Still cleared: either a bare TRUNCATE or the narrowed DELETE that preserves
    # rows keyed on admin-uploaded test types.
    assert (
        "TRUNCATE TABLE generation_sets" in sql
        or re.search(r"DELETE\s+FROM\s+generation_sets", sql, re.IGNORECASE)
    )
    assert not re.search(r"INSERT\s+INTO\s+generation_sets", sql, re.IGNORECASE)
