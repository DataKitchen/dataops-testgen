"""Match_* test types on DuckDB: a table profiled and then tested against an identical copy passes every test.

Baselines are taken from the DuckDB profile of the source table the way each type's ``default_parm_values``
reads ``profile_results``, then the type's DuckDB measure or template runs against a copy.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from yaml import safe_load

import testgen
from testgen.commands.queries.profiling_query import ProfilingSQL
from testgen.common import value_hash
from testgen.common.clean_sql import parse_value_list
from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.database_service import get_flavor_service, process_conditionals, replace_params
from testgen.common.profile_frequency import build_frequent_patterns, build_frequent_values
from testgen.common.read_file import read_template_sql_file, replace_templated_functions

pytestmark = pytest.mark.unit

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"
FLAVOR = "duckdb"
# DuckDB has no text hash probe, so a run profiling for table comparison hashes every hashable type.
HASHED_TYPES = frozenset({"A", "N", "D"})
RUN_DATE = "2024-06-01 12:00:00"

CODES = ["AB-1", "AB-2", "ab-3", "XY-10", "AB-1", "AB-2", "AB-1", " lead", "ZZ\u00a0Z", "", None, "QQ", "QQ", "Rr"]
# An apostrophe, a colon and a placeholder-shaped value exercise the quoting of the baseline literal
NOTES = ["alpha", "Beta", "GAMMA", "alpha", "beta", "Gamma", "delta", "ALPHA", "o'brien", "a :b", "{BASELINE_CT}", None]
COLUMNS = [  # name, general type, is_decimal, exact sum
    ("id", "N", False, True), ("amount", "N", True, True), ("price", "N", False, False), ("flag", "B", False, False),
    ("code", "A", False, False), ("note", "A", False, False), ("ts", "D", False, False), ("d", "D", False, False),
]
DB_TYPES = {
    "id": "INTEGER", "amount": "DECIMAL(18,4)", "price": "DOUBLE", "flag": "BOOLEAN",
    "code": "VARCHAR", "note": "VARCHAR", "ts": "TIMESTAMP", "d": "DATE",
}


def _chars(column: str, general_type: str, db_type: str | None = None) -> ColumnChars:
    db_type = db_type or DB_TYPES.get(column)
    return ColumnChars(
        "s", "src", column, general_type=general_type, column_type=(db_type or "").lower(), db_data_type=db_type
    )


COLUMN_CHARS = {column: _chars(column, general_type) for column, general_type, *_ in COLUMNS}
KEYED_TYPES = {"A": "Match_Keyed_Hash_Text", "N": "Match_Keyed_Hash_Num", "D": "Match_Keyed_Hash_Date"}


def _keyed_hashes(con, key: ColumnChars, columns: list[ColumnChars], max_query_chars: int | None = None) -> list:
    """The keyed hashes profiling records for ``columns``, by the queries it runs."""
    sql = ProfilingSQL.__new__(ProfilingSQL)
    sql.connection = SimpleNamespace(sql_flavor_code=FLAVOR, max_query_chars=max_query_chars)
    sql.flavor_service = get_flavor_service(FLAVOR)
    return [value for query, _ in sql.run_keyed_hash(key, columns) for value in con.execute(query).fetchone()]


def _canonical(frequent: dict | None) -> str | None:
    return ", ".join(f"{entry['value']} ({entry['ct']})" for entry in frequent["values"]) if frequent else None


def _sum_baseline(p: dict) -> dict:
    if p.get("sum_value") is None:
        return {"baseline_sum": repr(p["avg_value"] * p["value_ct"]), "upper_tolerance": "0.000000001"}
    # Trim trailing zeros from the stored NUMERIC(38,8), as Match_Sum's generation SQL does
    return {"baseline_sum": f"{p['sum_value']:.8f}".rstrip("0").rstrip("."), "upper_tolerance": "0"}


# Test type -> (default_parm_columns values read from the profile row)
BASELINES = {
    "Match_Null_Ct": lambda p: {"baseline_ct": p["null_value_ct"]},
    "Match_Distinct_Ct": lambda p: {"baseline_unique_ct": p["distinct_value_ct"]},
    "Match_Min_Val": lambda p: {"baseline_value": repr(float(p["min_value"]))},
    "Match_Max_Val": lambda p: {"baseline_value": repr(float(p["max_value"]))},
    "Match_Zero_Ct": lambda p: {"baseline_ct": p["zero_value_ct"]},
    "Match_Sum": _sum_baseline,
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
    "Match_Hash_Text": lambda p: {"baseline_value": p.get("multiset_hash")},
    "Match_Hash_Num": lambda p: {"baseline_value": p.get("multiset_hash")},
    "Match_Hash_Date": lambda p: {"baseline_value": p.get("multiset_hash")},
    "Match_Epoch_Sum": lambda p: {"baseline_sum": p.get("epoch_sum")},
}
SELECTED = {  # the general types each type's selection criteria admit
    "Match_Null_Ct": "NADB", "Match_Distinct_Ct": "NADB", "Match_Min_Val": "N", "Match_Max_Val": "N",
    "Match_Zero_Ct": "N", "Match_Sum": "N", "Match_Stdev": "N", "Match_Fractional_Sum": "N",
    "Match_Min_Date": "D", "Match_Max_Date": "D", "Match_Distinct_Date_Ct": "D", "Match_True_Ct": "B",
    "Match_Min_Length": "A", "Match_Max_Length": "A", "Match_Total_Length": "A", "Match_Lead_Space_Ct": "A", "Match_Zero_Length_Ct": "A",
    "Match_Upper_Case_Ct": "A", "Match_Non_Printing_Ct": "A", "Match_Distinct_Hash": "A",
    "Match_Frequent_Values": "A", "Match_Frequent_Patterns": "A",
    "Match_Hash_Text": "A", "Match_Hash_Num": "N", "Match_Hash_Date": "D", "Match_Epoch_Sum": "D",
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


def _profile(
    con, column: str, general_type: str, is_decimal: bool, exact_sum: bool = False, db_type: str | None = None
) -> dict:
    service = get_flavor_service(FLAVOR)
    chars = _chars(column, general_type, db_type)
    is_hashed = general_type in HASHED_TYPES
    flags = {
        "do_sample": False, "do_sample_bool": False, "is_type_A": general_type == "A", "is_type_N": general_type == "N",
        "is_type_D": general_type == "D", "is_type_B": general_type == "B", "is_type_ADN": general_type in "ADN",
        "is_type_DN": general_type in "DN", "is_type_X": False, "is_not_A": general_type != "A",
        "is_not_A_or_X": general_type != "A", "is_A_sampling": False, "is_A_no_sampling": general_type == "A",
        "is_N_decimal": general_type == "N" and is_decimal, "is_N_exact_sum": general_type == "N" and exact_sum,
        "is_N_approx_pctile": False,
        "is_N_exact_pctile": general_type == "N",
        "is_A_hashed": is_hashed and general_type == "A", "is_DN_hashed": is_hashed and general_type in "DN",
        "is_epoch_summed": is_hashed and general_type == "D",
    }
    params = {
        "CONNECTION_ID": 1, "PROJECT_CODE": "P", "TABLE_GROUPS_ID": "tg", "DATA_SCHEMA": "s", "RUN_DATE": RUN_DATE,
        "DATA_TABLE": "src", "COL_POS": 1, "COL_NAME": column, "COL_NUM": f'"{column}"', "COL_NAME_SANITIZED": column, "COL_TYPE": "",
        "DB_DATA_TYPE": "", "COL_GEN_TYPE": general_type, "PROFILE_RUN_ID": "pr", "MAX_PATTERN_LENGTH": 25,
        "PERCENTILE_METHOD": "exact", "TABLE_HINT": "",
        **(service.value_hash_params(chars) if is_hashed else {}),
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


def _passes(
    con,
    test_type: str,
    table: str,
    column: str | None,
    baseline: dict,
    column_chars: ColumnChars | None = None,
    key_chars: ColumnChars | None = None,
) -> bool:
    doc = _test_type(test_type)
    service = get_flavor_service(FLAVOR)
    key = baseline.get("groupby_names")
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
        "GROUPBY_NAMES": key,
        **service.value_hash_params(column_chars or COLUMN_CHARS.get(column), key_chars or COLUMN_CHARS.get(key)),
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
    service = get_flavor_service(FLAVOR)
    hashed = [chars for name, chars in COLUMN_CHARS.items() if name != "id" and chars.general_type in HASHED_TYPES]
    for chars, keyed_hash in zip(hashed, _keyed_hashes(con, COLUMN_CHARS["id"], hashed), strict=True):
        tests.append((KEYED_TYPES[chars.general_type], chars.column_name, {"groupby_names": "id", "baseline_value": str(keyed_hash)}))
    for column, general_type, is_decimal, exact_sum in COLUMNS:
        profile = _profile(con, column, general_type, is_decimal, exact_sum)
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
        ("Match_Hash_Text", "code"), ("Match_Hash_Date", "d"), ("Match_Epoch_Sum", "d"),
        ("Match_Keyed_Hash_Text", "code"), ("Match_Keyed_Hash_Date", "d"),
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


def test_an_exact_sum_catches_a_small_change_in_a_large_integer_total():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT 12000000000 + i AS v FROM range(0, 100) t(i)")
    con.execute("CREATE TABLE s.copy AS SELECT * FROM s.src")
    con.execute("CREATE TABLE s.changed AS SELECT CASE WHEN v = 12000000050 THEN v + 2 ELSE v END AS v FROM s.src")

    profile = _profile(con, "v", "N", False, exact_sum=True)
    baseline = _sum_baseline(profile)

    assert baseline == {"baseline_sum": "1200000004950", "upper_tolerance": "0"}
    assert _passes(con, "Match_Sum", "copy", "v", baseline)
    assert not _passes(con, "Match_Sum", "changed", "v", baseline)


def test_an_exact_sum_catches_a_change_of_one_past_double_precision():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT 900000000000000 + i AS v FROM range(0, 20) t(i)")
    con.execute("CREATE TABLE s.changed AS SELECT CASE WHEN v = 900000000000000 THEN v + 1 ELSE v END AS v FROM s.src")

    baseline = _sum_baseline(_profile(con, "v", "N", False, exact_sum=True))

    assert int(baseline["baseline_sum"]) > 2**53
    assert _passes(con, "Match_Sum", "src", "v", baseline)
    assert not _passes(con, "Match_Sum", "changed", "v", baseline)


def test_an_exact_decimal_sum_catches_one_cent_on_a_large_table():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT (i % 100000 + 0.25)::DECIMAL(18,2) AS v FROM range(0, 3000000) t(i)")
    con.execute("CREATE TABLE s.changed AS SELECT CASE WHEN rowid = 7 THEN v + 0.01 ELSE v END AS v FROM s.src")

    baseline = _sum_baseline(_profile(con, "v", "N", True, exact_sum=True))

    assert _passes(con, "Match_Sum", "src", "v", baseline)
    assert not _passes(con, "Match_Sum", "changed", "v", baseline)


def test_a_floating_point_column_profiles_no_exact_sum_and_keeps_the_tolerance(con):
    profile = _profile(con, "price", "N", False)

    assert "sum_value" not in profile
    assert _sum_baseline(profile)["upper_tolerance"] == "0.000000001"
    assert _passes(con, "Match_Sum", "copy", "price", _sum_baseline(profile))


def test_an_exact_sum_is_left_unset_past_the_values_it_can_hold():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT 1e25::HUGEINT + i AS v FROM range(0, 5) t(i)")

    assert _profile(con, "v", "N", False, exact_sum=True)["sum_value"] is None


def test_profiled_hashes_equal_the_reference_values(con):
    rows = con.execute("SELECT id, amount, price, code, ts, d FROM s.src").fetchall()
    columns = [("id", "N"), ("amount", "N"), ("price", "N"), ("code", "A"), ("ts", "D"), ("d", "D")]
    for index, (column, general_type) in enumerate(columns):
        profile = _profile(con, column, general_type, column == "amount")
        assert profile["multiset_hash"] == value_hash.multiset_hash(row[index] for row in rows), column
        if general_type == "D":
            assert profile["epoch_sum"] == value_hash.epoch_sum(row[index] for row in rows), column


def test_a_float_column_hashes_like_the_same_values_held_as_decimals():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src (n DECIMAL(18,8))")
    con.execute("INSERT INTO s.src VALUES (0.1234565), (-0.1234565), (0.12345649), (12345678.9999995), (2.675), "
                "(0.00000049), (3), (NULL)")
    con.execute("CREATE TABLE s.dest AS SELECT n::DOUBLE AS n FROM s.src")
    baseline = {"baseline_value": str(_profile(con, "n", "N", True, db_type="DECIMAL(18,8)")["multiset_hash"])}

    assert _passes(con, "Match_Hash_Num", "dest", "n", baseline, _chars("n", "N", "DOUBLE"))


def test_floats_out_of_decimal_range_are_left_out_of_the_hash():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT * FROM (VALUES (1.5::DOUBLE), (1e30), "
                "(-1e35), (1e20)) t(n)")
    values = [row[0] for row in con.execute("SELECT n FROM s.src").fetchall()]

    assert _profile(con, "n", "N", False, db_type="DOUBLE")["multiset_hash"] == value_hash.multiset_hash(values)
    assert value_hash.multiset_hash(values) == value_hash.multiset_hash([1.5, 1e20])


def test_the_reference_leaves_infinite_and_nan_floats_out_of_the_hash():
    assert value_hash.multiset_hash([1.5, float("nan"), float("inf"), float("-inf")]) == value_hash.multiset_hash([1.5])


def test_decimals_out_of_decimal_range_are_left_out_of_the_hash_and_the_profile_still_runs():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute(
        "CREATE TABLE s.src AS SELECT * FROM (VALUES (1.5::DECIMAL(38,0)), (1e33::DECIMAL(38,0)), "
        f"('{10**32 - 1}'::DECIMAL(38,0)), ('{10**32}'::DECIMAL(38,0))) t(n)"
    )
    values = [row[0] for row in con.execute("SELECT n FROM s.src").fetchall()]

    profile = _profile(con, "n", "N", True, db_type="DECIMAL(38,0)")

    assert profile["multiset_hash"] == value_hash.multiset_hash(values)
    assert value_hash.multiset_hash(values) == value_hash.multiset_hash([Decimal(2), Decimal(10**32 - 1)])


@pytest.mark.parametrize(
    ("db_type", "value"),
    [("SMALLINT", -(2**15)), ("INTEGER", -(2**31)), ("BIGINT", -(2**63))],
)
def test_an_integer_types_minimum_value_is_hashed(db_type, value):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute(f"CREATE TABLE s.src AS SELECT * FROM (VALUES ('{value}'::{db_type}), (1::{db_type})) t(n)")

    profile = _profile(con, "n", "N", False, db_type=db_type)

    assert profile["multiset_hash"] == value_hash.multiset_hash([value, 1])


@pytest.mark.parametrize(
    ("db_type", "values"),
    [
        ("DECIMAL(9,8)", ["9.99999999", "-9.99999995"]),
        ("DECIMAL(38,6)", [f"-{10**32 - 1}.5", f"{10**32 - 1}.5"]),
    ],
    ids=["rounding adds a whole digit", "a fraction just inside the bound"],
)
def test_decimals_at_the_edges_of_their_type_are_hashed(db_type, values):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    rows = ", ".join(f"('{value}'::{db_type})" for value in values)
    con.execute(f"CREATE TABLE s.src AS SELECT * FROM (VALUES {rows}) t(n)")

    profile = _profile(con, "n", "N", True, db_type=db_type)

    assert profile["multiset_hash"] == value_hash.multiset_hash(Decimal(value) for value in values)


def test_a_hugeint_past_the_wide_decimal_is_left_out_of_the_hash():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute(f"CREATE TABLE s.src AS SELECT * FROM (VALUES (2::HUGEINT), ({10**38}::HUGEINT)) t(n)")

    assert _profile(con, "n", "N", False, db_type="HUGEINT")["multiset_hash"] == value_hash.multiset_hash([2])


def test_infinite_dates_are_left_out_of_the_hash():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT * FROM (VALUES ('infinity'::DATE), ('2024-01-01'::DATE)) t(d)")

    profile = _profile(con, "d", "D", False, db_type="DATE")

    assert profile["multiset_hash"] == value_hash.multiset_hash([date(2024, 1, 1)])
    assert profile["epoch_sum"] == value_hash.epoch_sum([date(2024, 1, 1)])


def test_the_reference_leaves_out_a_decimal_that_rounds_up_to_the_bound():
    assert not value_hash.is_hashable(Decimal(f"-{10**32 - 1}.9999995"))
    assert value_hash.is_hashable(Decimal(f"-{10**32 - 1}.9999994"))


def test_the_reference_zero_pads_years_below_one_thousand():
    assert value_hash.canonical_text(date(1, 1, 1)) == "0001-01-01 00:00:00"


def test_a_single_precision_float_hashes_like_its_exact_double_value():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT * FROM (VALUES (123.456789::FLOAT), (0.1::FLOAT)) t(n)")
    doubles = [row[0] for row in con.execute("SELECT n::DOUBLE FROM s.src").fetchall()]

    assert _profile(con, "n", "N", False, db_type="FLOAT")["multiset_hash"] == value_hash.multiset_hash(doubles)


def test_a_key_value_out_of_decimal_range_leaves_its_row_out_of_the_keyed_hash():
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT * FROM (VALUES (1::DECIMAL(38,0), 'a'), (1e33::DECIMAL(38,0), 'b')) t(k, v)")
    rows = con.execute("SELECT k, v FROM s.src").fetchall()
    key, value = _chars("k", "N", "DECIMAL(38,0)"), _chars("v", "A", "VARCHAR")

    assert _keyed_hashes(con, key, [value]) == [value_hash.keyed_hash(rows)] == [value_hash.keyed_hash(rows[:1])]


@pytest.mark.parametrize(
    ("damage", "fails"),
    [
        ("UPDATE s.dest SET v = 'changed' WHERE k = 3", True),
        ("INSERT INTO s.dest SELECT * FROM s.dest WHERE k = 3", True),
        ("DELETE FROM s.dest WHERE k = 3", True),
        ("UPDATE s.dest SET v = CASE k WHEN 3 THEN 'v4' WHEN 4 THEN 'v3' ELSE v END", False),
    ],
    ids=["changed value", "duplicated row", "dropped row", "values swapped between rows"],
)
def test_the_text_hash_fails_on_any_change_to_the_values_but_not_on_their_order(damage, fails):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT i AS k, 'v' || i::VARCHAR AS v FROM range(0, 20) t(i)")
    con.execute("CREATE TABLE s.dest AS SELECT * FROM s.src")
    con.execute(damage)

    chars = _chars("v", "A", "VARCHAR")
    baseline = {"baseline_value": str(_profile(con, "v", "A", False, db_type="VARCHAR")["multiset_hash"])}

    assert _passes(con, "Match_Hash_Text", "dest", "v", baseline, chars) is not fails


def test_a_uniform_time_zone_shift_moves_the_epoch_sum_by_the_row_count_times_the_offset():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT TIMESTAMP '2024-03-01 10:00:00.5' + i * INTERVAL 1 DAY AS ts FROM range(0, 25) t(i)")
    con.execute("CREATE TABLE s.shifted AS SELECT ts + INTERVAL 1 HOUR AS ts FROM s.src")

    chars = _chars("ts", "D", "TIMESTAMP")
    source = _profile(con, "ts", "D", False, db_type="TIMESTAMP")["epoch_sum"]
    measure = con.execute(f"SELECT SUM({get_flavor_service(FLAVOR).epoch_sum_term('ts', chars)}) FROM s.shifted").fetchone()[0]

    assert measure - source == 25 * 3600
    assert not _passes(con, "Match_Epoch_Sum", "shifted", "ts", {"baseline_sum": str(source)}, chars)
    assert not _passes(con, "Match_Hash_Date", "shifted", "ts", {"baseline_value": str(_profile(con, "ts", "D", False, db_type="TIMESTAMP")["multiset_hash"])}, chars)


def test_the_same_values_hash_alike_whatever_the_declared_type():
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src (n BIGINT, ts TIMESTAMP)")
    con.execute("INSERT INTO s.src VALUES (5, '2024-01-02 03:04:05'), (-7, '2024-01-02 00:00:00'), (NULL, NULL)")
    con.execute("CREATE TABLE s.dest AS SELECT n::DECIMAL(12,3) AS n, ts::TIMESTAMPTZ AS ts FROM s.src")

    baselines = {
        "n": {"baseline_value": str(_profile(con, "n", "N", False, db_type="BIGINT")["multiset_hash"])},
        "ts": {"baseline_value": str(_profile(con, "ts", "D", False, db_type="TIMESTAMP")["multiset_hash"])},
    }

    assert _passes(con, "Match_Hash_Num", "dest", "n", baselines["n"], _chars("n", "N", "DECIMAL(12,3)"))
    assert _passes(con, "Match_Hash_Date", "dest", "ts", baselines["ts"], _chars("ts", "D", "TIMESTAMP WITH TIME ZONE"))


@pytest.mark.parametrize(
    ("damage", "plain_fails", "keyed_fails"),
    [
        ("UPDATE s.dest SET v = CASE k WHEN 3 THEN 'v4' WHEN 4 THEN 'v3' ELSE v END", False, True),
        ("UPDATE s.dest SET k = k + 1000", False, True),
        ("UPDATE s.dest SET v = 'changed' WHERE k = 3", True, True),
        ("UPDATE s.dest SET v = NULL WHERE k = 3", True, True),
    ],
    ids=["values swapped between rows", "key regenerated", "changed value", "value nulled"],
)
def test_the_keyed_hash_ties_each_value_to_its_row(damage, plain_fails, keyed_fails):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA s")
    con.execute("CREATE TABLE s.src AS SELECT i AS k, 'v' || i::VARCHAR AS v FROM range(0, 20) t(i)")
    con.execute("CREATE TABLE s.dest AS SELECT * FROM s.src")
    con.execute(damage)

    key, value = _chars("k", "N", "BIGINT"), _chars("v", "A", "VARCHAR")
    plain = {"baseline_value": str(_profile(con, "v", "A", False, db_type="VARCHAR")["multiset_hash"])}
    keyed = {"groupby_names": "k", "baseline_value": str(_keyed_hashes(con, key, [value])[0])}

    assert _passes(con, "Match_Hash_Text", "dest", "v", plain, value) is not plain_fails
    assert _passes(con, "Match_Keyed_Hash_Text", "dest", "v", keyed, value, key) is not keyed_fails


def test_keyed_hashes_equal_the_reference_values_however_the_queries_are_split(con):
    service = get_flavor_service(FLAVOR)
    hashed = [chars for name, chars in COLUMN_CHARS.items() if name != "id" and chars.general_type in HASHED_TYPES]
    rows = con.execute(f"SELECT id, {', '.join(chars.column_name for chars in hashed)} FROM s.src").fetchall()
    expected = [value_hash.keyed_hash((row[0], row[index + 1]) for row in rows) for index in range(len(hashed))]

    assert _keyed_hashes(con, COLUMN_CHARS["id"], hashed) == expected
    assert _keyed_hashes(con, COLUMN_CHARS["id"], hashed, max_query_chars=600) == expected
