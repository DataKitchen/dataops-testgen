import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen
from testgen.common.models.test_definition import StatisticalTechnique, TestAlgorithm

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

ALGORITHMS = {a.value for a in TestAlgorithm}
TECHNIQUES = {t.value for t in StatisticalTechnique}
HEALTH_DIMENSIONS = {"Schema Drift", "Data Drift", "Statistical Drift", "Volume", "Freshness"}


# Output columns every QUERY test template selects, in the order they are selected.
# Schema_Drift is the only METADATA type and selects the same list without these.
RESULT_COLUMNS = [
    "test_type", "test_definition_id", "test_suite_id", "test_run_id", "test_time",
    "schema_name", "table_name", "column_names", "threshold_value", "skip_errors",
    "input_parameters", "result_signal", "result_code", "result_message", "result_measure",
]
SCHEMA_DRIFT_OMITS = {"table_name", "column_names", "threshold_value", "skip_errors"}


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", sql, flags=re.S))


def _test_type_docs():
    for path in sorted([*YAML_DIR.glob("*.yaml"), *YAML_DIR.glob("*.yml")]):
        data = safe_load(path.read_text())["test_types"]
        yield path.name, data


@pytest.mark.unit
def test_every_test_type_declares_a_valid_algorithm():
    for filename, tt in _test_type_docs():
        algorithm = tt.get("algorithm")
        assert algorithm in ALGORITHMS, f"{filename}: invalid/missing algorithm {algorithm!r}"


@pytest.mark.unit
def test_statistical_technique_is_valid_when_present():
    for filename, tt in _test_type_docs():
        algorithm = tt.get("algorithm")
        technique = tt.get("statistical_technique")
        if technique is not None:
            assert technique in TECHNIQUES, f"{filename}: invalid statistical_technique {technique!r}"
        if algorithm == TestAlgorithm.STATISTICAL_DRIFT.value:
            assert technique in TECHNIQUES, f"{filename}: drift test needs a valid technique, got {technique!r}"


@pytest.mark.unit
def test_health_dimension_uses_freshness_not_recency():
    for filename, tt in _test_type_docs():
        health = tt.get("health_dimension")
        assert health != "Recency", f"{filename}: health_dimension must be 'Freshness', not 'Recency'"
        assert health is None or health in HEALTH_DIMENSIONS, f"{filename}: unexpected health_dimension {health!r}"


@pytest.mark.unit
def test_templates_sharing_a_result_header_agree_on_their_columns():
    """Results for a run_type are bulk-loaded under one header taken from whichever
    template's query finished last, and looked up on each row by name. So every
    template of a (run_type, flavor) must expose the same output columns, under the
    same names. A missing name aborts the write for the whole batch.

    Pins names, cardinality and order for the columns the load names; a template
    adding an output column beyond them is not detected.
    """
    expected = {
        "QUERY": RESULT_COLUMNS,
        "METADATA": [column for column in RESULT_COLUMNS if column not in SCHEMA_DRIFT_OMITS],
    }
    for filename, tt in _test_type_docs():
        columns = expected.get(tt.get("run_type"))
        if columns is None:
            continue
        for template in tt.get("test_templates") or []:
            aliases = [
                match.group(1).lower()
                for match in re.finditer(
                    r"\bAS\s+([a-z_]+)\b", _strip_sql_comments(template["template"]), re.I
                )
                if match.group(1).lower() in set(columns)
            ]
            assert aliases == columns, (
                f"{filename} [{template['sql_flavor']}]: output columns {aliases}, expected {columns}"
            )
