"""Guards on the generation templates as a whole, not on any single test type."""

import re
from pathlib import Path

import yaml

import testgen

TEMPLATE_ROOT = Path(testgen.__file__).parent / "template"

# Directories holding the per-test-type generation templates plus the shared
# selection template. get_test_types.sql is the one intentional exception: it is
# where the generation-set filter belongs.
GENERATION_DIRS = ("generation", "gen_query_tests", "gen_funny_cat_tests")


def _generation_templates() -> list[Path]:
    paths = []
    for sql_path in TEMPLATE_ROOT.rglob("*.sql"):
        parts = sql_path.relative_to(TEMPLATE_ROOT).parts
        if any(part in GENERATION_DIRS for part in parts):
            paths.append(sql_path)
    return paths


def test_generation_templates_exist():
    # Guards the glob itself: an empty list would make the next test vacuously pass.
    assert len(_generation_templates()) > 20


def test_only_get_test_types_filters_by_generation_set():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _generation_templates()
        if path.name != "get_test_types.sql" and "generation_sets" in path.read_text()
    )

    assert offenders == [], (
        "get_test_types.sql already filters by generation set; a per-template guard is "
        "redundant and drifts. Offenders: " + ", ".join(offenders)
    )


def _upserting_templates() -> list[Path]:
    return [
        path
        for path in TEMPLATE_ROOT.rglob("*.sql")
        if "ON CONFLICT (test_suite_id," in path.read_text()
    ]


def _inserted_columns(body: str) -> str:
    start = body.index("INSERT INTO test_definitions (")
    return body[start:body.index(")", start)]


def test_every_upsert_names_the_version_in_its_conflict_list():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _upserting_templates()
        if "ON CONFLICT (test_suite_id, version_id," not in path.read_text()
    )

    assert offenders == [], (
        "an upsert whose conflict list omits the version cannot infer its arbiter index and "
        "fails outright. Offenders: " + ", ".join(offenders)
    )


def test_every_table_scoped_upsert_honours_the_table_filter():
    """A contract covers the tables its document names, which may be a subset of the table group.

    Schema_Drift is the one exception: it writes no table_name, so there is nothing to filter by.
    """
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _upserting_templates()
        if "table_name" in _inserted_columns(path.read_text())
        and "{TABLE_FILTER}" not in path.read_text()
    )

    assert offenders == [], "table-scoped upserts ignoring the table filter: " + ", ".join(offenders)


def test_the_schema_scoped_upsert_takes_no_table_filter():
    schema_drift = TEMPLATE_ROOT / "gen_query_tests" / "gen_Schema_Drift.sql"

    assert "{TABLE_FILTER}" not in schema_drift.read_text()


def test_every_upsert_writes_the_version_it_conflicts_on():
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _upserting_templates()
        if "version_id" not in _inserted_columns(path.read_text())
        or ":VERSION_ID" not in path.read_text()
    )

    assert offenders == [], (
        "an upsert that conflicts on the version but never writes it lands every row on the "
        "placeholder version, where neither the deletes nor the reads of the same generation "
        "run can see it. Offenders: " + ", ".join(offenders)
    )


def test_generic_freshness_fingerprints_cast_before_defaulting_nulls():
    """PostgreSQL money cannot take an integer default, so a numeric column is cast before COALESCE."""
    templates = [
        TEMPLATE_ROOT / "gen_query_tests" / "gen_Freshness_Trend.sql",
        TEMPLATE_ROOT / "gen_query_tests" / "gen_Table_Freshness.sql",
    ]

    assert [path.name for path in templates if "COALESCE(@@@," in path.read_text()] == []


def test_every_read_of_profiling_results_leaves_out_dropped_columns():
    reads = re.compile(r"\b(?:FROM|JOIN)\s+profile_results\b", re.IGNORECASE)
    offenders = sorted(
        str(path.relative_to(TEMPLATE_ROOT))
        for path in _generation_templates()
        if len(reads.findall(text := path.read_text())) > text.count("drop_date")
    )

    assert offenders == [], (
        "a generation template reads profile_results without leaving out the columns the data catalog marks "
        "dropped, so it generates tests that error on every run. Offenders: " + ", ".join(offenders)
    )


def test_every_regenerated_aggregate_test_drops_its_record_subset():
    subset_types = set()
    for yaml_path in (TEMPLATE_ROOT / "dbsetup_test_types").glob("*.yaml"):
        test_type = yaml.safe_load(yaml_path.read_text())["test_types"]
        if test_type["run_type"] == "CAT" and "subset_condition" in (test_type["default_parm_columns"] or ""):
            subset_types.add(test_type["test_type"])
    subset_types.discard("Volume_Trend")  # Its generator writes the subset into its own query

    checked, offenders = set(), []
    for path in _generation_templates():
        text = path.read_text()
        for test_type in set(re.findall(r"'(\w+)'\s+AS test_type", text)) & subset_types:
            checked.add(test_type)
            if not re.search(r"\bsubset_condition\s*=\s*NULL\b", text):
                offenders.append(str(path.relative_to(TEMPLATE_ROOT)))

    assert checked == {"Constant", "Distinct_Value_Ct", "Row_Ct"}
    assert offenders == []
