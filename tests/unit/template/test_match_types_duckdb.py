"""Match_* test types on DuckDB: a table profiled and then tested against an identical copy passes every test.

Baselines are taken from the DuckDB profile of the source table the way each type's ``default_parm_values``
reads ``profile_results``, then the type's DuckDB measure or template runs against a copy.
"""

from pathlib import Path

import duckdb
import pytest
from yaml import safe_load

import testgen
from testgen.common.clean_sql import parse_value_list
from testgen.common.database.database_service import get_flavor_service, process_conditionals, replace_params
from testgen.common.profile_frequency import build_frequent_patterns, build_frequent_values
from testgen.common.read_file import read_template_sql_file, replace_templated_functions

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"
FLAVOR = "duckdb"
RUN_DATE = "2024-06-01 12:00:00"

CODES = ["AB-1", "AB-2", "ab-3", "XY-10", "AB-1", "AB-2", "AB-1", " lead", "ZZ\u00a0Z", "", None, "QQ", "QQ", "Rr"]
# An apostrophe, a colon and a placeholder-shaped value exercise the quoting of the baseline literal
NOTES = ["alpha", "Beta", "GAMMA", "alpha", "beta", "Gamma", "delta", "ALPHA", "o'brien", "a :b", "{BASELINE_CT}", None]
COLUMNS = [  # name, general type, is_decimal
    ("id", "N", False), ("amount", "N", True), ("price", "N", False), ("flag", "B", False),
    ("code", "A", False), ("note", "A", False), ("ts", "D", False), ("d", "D", False),
]


def _canonical(frequent: dict | None) -> str | None:
    return ", ".join(f"{entry['value']} ({entry['ct']})" for entry in frequent["values"]) if frequent else None


# Test type -> (default_parm_columns values read from the profile row)
BASELINES = {
    "Match_Null_Ct": lambda p: {"baseline_ct": p["null_value_ct"]},
    "Match_Distinct_Ct": lambda p: {"baseline_unique_ct": p["distinct_value_ct"]},
    "Match_Min_Val": lambda p: {"baseline_value": repr(float(p["min_value"]))},
    "Match_Max_Val": lambda p: {"baseline_value": repr(float(p["max_value"]))},
    "Match_Zero_Ct": lambda p: {"baseline_ct": p["zero_value_ct"]},
    "Match_Sum": lambda p: {"baseline_sum": repr(p["avg_value"] * p["value_ct"]), "upper_tolerance": "0.000000001"},
    "Match_Stdev": lambda p: {"baseline_sd": repr(p["stdev_value"]), "upper_tolerance": "0.000000001"},
    "Match_Fractional_Sum": lambda p: {
        "baseline_sum": None if p.get("fractional_sum") is None else f"{p['fractional_sum']:.6f}",
    },
    "Match_Min_Date": lambda p: {"baseline_value": p["min_date"].strftime("%Y-%m-%d %H:%M:%S")},
    "Match_Max_Date": lambda p: {"baseline_value": p["max_date"].strftime("%Y-%m-%d %H:%M:%S")},
    "Match_Distinct_Date_Ct": lambda p: {"baseline_ct": p["date_days_present"]},
    "Match_True_Ct": lambda p: {"baseline_ct": p["boolean_true_ct"]},
    "Match_Min_Length": lambda p: {"baseline_value": p["min_length"]},
    "Match_Max_Length": lambda p: {"baseline_value": p["max_length"]},
    "Match_Total_Length": lambda p: {
        "baseline_sum": round((p["avg_length"] or 0) * (p["value_ct"] - (p["zero_length_ct"] or 0))),
    },
    "Match_Lead_Space_Ct": lambda p: {"baseline_ct": p["lead_space_ct"]},
    "Match_Zero_Length_Ct": lambda p: {"baseline_ct": p["zero_length_ct"]},
    "Match_Upper_Case_Ct": lambda p: {"baseline_ct": p["upper_case_ct"]},
    "Match_Non_Printing_Ct": lambda p: {"baseline_ct": p["non_printing_ct"]},
    "Match_Distinct_Hash": lambda p: {"baseline_value": p["distinct_value_hash"]},
    "Match_Frequent_Values": lambda p: {"baseline_value": _canonical(p["frequent_values"])},
    "Match_Frequent_Patterns": lambda p: {"baseline_value": _canonical(p["frequent_patterns"])},
}
SELECTED = {  # the general types each type's selection criteria admit
    "Match_Null_Ct": "NADB", "Match_Distinct_Ct": "NADB", "Match_Min_Val": "N", "Match_Max_Val": "N",
    "Match_Zero_Ct": "N", "Match_Sum": "N", "Match_Stdev": "N", "Match_Fractional_Sum": "N",
    "Match_Min_Date": "D", "Match_Max_Date": "D", "Match_Distinct_Date_Ct": "D", "Match_True_Ct": "B",
    "Match_Min_Length": "A", "Match_Max_Length": "A", "Match_Total_Length": "A", "Match_Lead_Space_Ct": "A", "Match_Zero_Length_Ct": "A",
    "Match_Upper_Case_Ct": "A", "Match_Non_Printing_Ct": "A", "Match_Distinct_Hash": "A",
    "Match_Frequent_Values": "A", "Match_Frequent_Patterns": "A",
}


@pytest.fixture(scope="module")
def con():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src (id INTEGER, amount DECIMAL(18,4), price DOUBLE, flag BOOLEAN, code VARCHAR, "
                "note VARCHAR, ts TIMESTAMP, d DATE)")
    con.executemany("INSERT INTO s.src VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
        (
            i,
            None if i % 9 == 0 else round(i * 1.125 - 7.3333, 4),
            float(i % 7) * 2.5,
            None if i % 11 == 0 else (i % 3 == 0),
            CODES[i % len(CODES)],
            NOTES[i % len(NOTES)],
            f"2024-0{1 + i % 5}-1{i % 10} 0{i % 10}:15:3{i % 10}.75",
            f"2023-1{i % 3}-0{1 + i % 9}",
        )
        for i in range(40)
    ])
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")
    con.execute("CREATE TABLE s.changed AS SELECT * FROM s.src")
    con.execute("UPDATE s.changed SET code = 'AB-9', d = d + 400 WHERE id = 5")
    return con


def _profile(con, column: str, general_type: str, is_decimal: bool) -> dict:
    flags = {
        "do_sample": False, "do_sample_bool": False, "is_type_A": general_type == "A", "is_type_N": general_type == "N",
        "is_type_D": general_type == "D", "is_type_B": general_type == "B", "is_type_ADN": general_type in "ADN",
        "is_type_DN": general_type in "DN", "is_type_X": False, "is_not_A": general_type != "A",
        "is_not_A_or_X": general_type != "A", "is_A_sampling": False, "is_A_no_sampling": general_type == "A",
        "is_N_decimal": general_type == "N" and is_decimal, "is_N_approx_pctile": False,
        "is_N_exact_pctile": general_type == "N",
    }
    params = {
        "CONNECTION_ID": 1, "PROJECT_CODE": "P", "TABLE_GROUPS_ID": "tg", "DATA_SCHEMA": "s", "RUN_DATE": RUN_DATE,
        "DATA_TABLE": "src", "COL_POS": 1, "COL_NAME": column, "COL_NAME_SANITIZED": column, "COL_TYPE": "",
        "DB_DATA_TYPE": "", "COL_GEN_TYPE": general_type, "PROFILE_RUN_ID": "pr", "MAX_PATTERN_LENGTH": 25,
        "PERCENTILE_METHOD": "exact", "TABLE_HINT": "",
    }

    def run(template: str) -> list[dict]:
        sql = read_template_sql_file(template, f"flavors/{FLAVOR}/profiling")
        sql = replace_templated_functions(replace_params(process_conditionals(sql, flags), params), FLAVOR)
        cursor = con.execute(sql)
        names = [description[0] for description in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]

    profile = run("project_profiling_query.sql")[0]
    profile["frequent_patterns"] = build_frequent_patterns(profile)
    if general_type == "A":
        frequency = run("project_secondary_profiling_query.sql")
        profile["frequent_values"] = build_frequent_values(frequency)
        profile["distinct_value_hash"] = frequency[0]["distinct_value_hash"]
    return profile


def _test_type(test_type: str) -> dict:
    return safe_load((YAML_DIR / f"test_types_{test_type}.yaml").read_text())["test_types"]


def _passes(con, test_type: str, table: str, column: str | None, baseline: dict) -> bool:
    doc = _test_type(test_type)
    service = get_flavor_service(FLAVOR)
    null_if_empty = lambda value: "NULL" if value in (None, "") else value
    params = {
        "TEST_TYPE": test_type, "TEST_DEFINITION_ID": "td", "TEST_SUITE_ID": "ts", "TEST_RUN_ID": "tr",
        "RUN_DATE": RUN_DATE, "SCHEMA_NAME": "s", "TABLE_NAME": table, "QUOTE": '"',
        "COLUMN_NAME": f'"{column or ""}"', "COLUMN_NAME_NO_QUOTES": column, "SKIP_ERRORS": 0, "INPUT_PARAMETERS": "",
        "BASELINE_CT": null_if_empty(baseline.get("baseline_ct")),
        "BASELINE_UNIQUE_CT": null_if_empty(baseline.get("baseline_unique_ct")),
        "BASELINE_VALUE": baseline.get("baseline_value"),
        "THRESHOLD_VALUE": baseline.get("threshold_value") or 0,
        "BASELINE_SUM": null_if_empty(baseline.get("baseline_sum")),
        "BASELINE_SD": null_if_empty(baseline.get("baseline_sd")),
        "UPPER_TOLERANCE": null_if_empty(baseline.get("upper_tolerance")),
        "BASELINE_VALUE_LIST": service.string_literal_list(parse_value_list(baseline.get("baseline_value"))),
        "BASELINE_VALUE_LITERAL": service.string_literal_or_null(baseline.get("baseline_value")),
    }
    if doc["run_type"] == "CAT":
        condition = next(c for c in doc["cat_test_conditions"] if c["sql_flavor"] == FLAVOR)
        measure = replace_templated_functions(replace_params(condition["measure"], params), FLAVOR)
        expected = replace_params(condition["test_condition"], params)
        space = " " if "BETWEEN" in condition["test_operator"] else ""
        failed = f"{measure}{space}{condition['test_operator']}{space}{expected}"
        return con.execute(f'SELECT CASE WHEN {failed} THEN 0 ELSE 1 END FROM "s"."{table}"').fetchone()[0] == 1
    template = next(t for t in doc["test_templates"] if t["sql_flavor"] == FLAVOR)["template"]
    cursor = con.execute(replace_params(template, params))
    row = dict(zip([description[0] for description in cursor.description], cursor.fetchone(), strict=True))
    return row["result_code"] == 1


@pytest.fixture(scope="module")
def generated(con) -> list[tuple[str, str | None, dict]]:
    tests = [("Match_Row_Ct", None, {"threshold_value": "40"})]
    for column, general_type, is_decimal in COLUMNS:
        profile = _profile(con, column, general_type, is_decimal)
        for test_type, read in BASELINES.items():
            if general_type in SELECTED[test_type]:
                baseline = read(profile)
                if all(value is not None for value in baseline.values()):
                    tests.append((test_type, column, {key: str(value) for key, value in baseline.items()}))
    return tests


def test_every_duckdb_measure_is_exercised(generated):
    exercised = {test_type for test_type, _, _ in generated}
    runnable = {path.stem.removeprefix("test_types_") for path in YAML_DIR.glob("test_types_Match_*.yaml")}
    assert runnable - exercised == {"Match_Column_Ct", "Match_Column_Type"}


def test_an_identical_copy_passes_every_test(con, generated):
    failures = [(t, c) for t, c, baseline in generated if not _passes(con, t, "copy", c, baseline)]
    assert failures == []


def test_a_changed_value_fails_the_tests_that_measure_it(con, generated):
    failures = {(t, c) for t, c, baseline in generated if not _passes(con, t, "changed", c, baseline)}
    assert failures == {
        ("Match_Distinct_Ct", "code"), ("Match_Distinct_Hash", "code"), ("Match_Frequent_Values", "code"),
        ("Match_Distinct_Ct", "d"), ("Match_Distinct_Date_Ct", "d"), ("Match_Max_Date", "d"),
    }


def test_leading_spaces_count_any_number_of_spaces_but_not_blank_values():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    values = [" one", "   three", "   ", "", "none", None]
    con.execute("CREATE TABLE s.src (v VARCHAR)")
    con.executemany("INSERT INTO s.src VALUES (?)", [(value,) for value in values])
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")
    con.execute("CREATE TABLE s.trimmed AS SELECT CASE WHEN v = '   three' THEN 'three' ELSE v END AS v FROM s.src")

    profile = _profile(con, "v", "A", False)
    baseline = {"baseline_ct": str(profile["lead_space_ct"])}

    assert profile["lead_space_ct"] == 2
    assert _passes(con, "Match_Lead_Space_Ct", "copy", "v", baseline)
    assert not _passes(con, "Match_Lead_Space_Ct", "trimmed", "v", baseline)


def test_fractional_sum_of_decimals_matches_the_same_values_stored_as_doubles():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    # Six-place decimals ending in 5 sit on a rounding tie at five places; a double holding one
    # can fall just below the tie.
    con.execute("CREATE TABLE s.src AS SELECT (i * 0.00001 + 0.000005)::DECIMAL(18,6) AS v FROM range(0, 2000) t(i)")
    con.execute("CREATE TABLE s.copy AS SELECT v::DOUBLE AS v FROM s.src")

    profile = _profile(con, "v", "N", True)

    assert _passes(con, "Match_Fractional_Sum", "copy", "v", {"baseline_sum": f"{profile['fractional_sum']:.6f}"})


def test_total_length_catches_a_value_rewritten_everywhere_it_occurs():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    # More distinct values than the hash and frequency measures cover; the damage lengthens values
    # that are neither the shortest nor the longest.
    con.execute("CREATE TABLE s.src AS SELECT 'name' || i::VARCHAR || 'é' AS v FROM range(0, 500) t(i) "
                "UNION ALL SELECT 'x' UNION ALL SELECT 'the longest value of all'")
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")
    con.execute("CREATE TABLE s.damaged AS SELECT REPLACE(v, 'é', 'Ã©') AS v FROM s.src")

    profile = _profile(con, "v", "A", False)
    baselines = {
        test_type: {key: str(value) for key, value in BASELINES[test_type](profile).items()}
        for test_type in ["Match_Total_Length", "Match_Distinct_Ct", "Match_Min_Length", "Match_Max_Length"]
    }

    assert _passes(con, "Match_Total_Length", "copy", "v", baselines["Match_Total_Length"])
    assert not _passes(con, "Match_Total_Length", "damaged", "v", baselines["Match_Total_Length"])
    for test_type in ["Match_Distinct_Ct", "Match_Min_Length", "Match_Max_Length"]:
        assert _passes(con, test_type, "damaged", "v", baselines[test_type])


def test_sum_of_values_past_eight_decimal_places_matches_an_identical_copy():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT 1.0 / (i + 2) AS v FROM range(0, 1000) t(i)")
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")

    profile = _profile(con, "v", "N", True)
    baseline = {key: str(value) for key, value in BASELINES["Match_Sum"](profile).items()}

    assert _passes(con, "Match_Sum", "copy", "v", baseline)


def test_profiling_records_no_hash_past_seventy_distinct_values():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT 'v' || i::VARCHAR AS v FROM range(0, 71) t(i)")

    assert _profile(con, "v", "A", False)["distinct_value_hash"] is None


def test_case_counts_compare_by_code_point_under_a_case_insensitive_collation():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src (v VARCHAR COLLATE NOCASE)")
    con.executemany("INSERT INTO s.src VALUES (?)", [(value,) for value in ["ABC", "DEF", "abc", "Abc", "123", None]])
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")
    con.execute("CREATE TABLE s.recased AS SELECT CASE WHEN v = 'DEF' THEN 'def' ELSE v END AS v FROM s.src")

    profile = _profile(con, "v", "A", False)
    baseline = {key: str(value) for key, value in BASELINES["Match_Upper_Case_Ct"](profile).items()}

    assert (profile["upper_case_ct"], profile["lower_case_ct"], profile["non_alpha_ct"]) == (2, 1, 1)
    assert _passes(con, "Match_Upper_Case_Ct", "copy", "v", baseline)
    assert not _passes(con, "Match_Upper_Case_Ct", "recased", "v", baseline)


def test_every_match_cat_type_fails_on_a_null_measure():
    cat_types = [
        doc for doc in (_test_type(path.stem.removeprefix("test_types_")) for path in YAML_DIR.glob("test_types_Match_*.yaml"))
        if doc["run_type"] == "CAT"
    ]
    assert cat_types
    assert [doc["test_type"] for doc in cat_types if doc.get("null_measure_fails") is not True] == []
