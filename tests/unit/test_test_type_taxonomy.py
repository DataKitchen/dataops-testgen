import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen
from testgen.commands.queries.execute_tests_query import TestExecutionSQL
from testgen.common.models.test_definition import StatisticalTechnique, TestAlgorithm

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

ALGORITHMS = {a.value for a in TestAlgorithm}
TECHNIQUES = {t.value for t in StatisticalTechnique}
HEALTH_DIMENSIONS = {"Schema Drift", "Data Drift", "Statistical Drift", "Volume", "Freshness"}


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
    """Results for a run type are bulk-loaded under the header the loader declares, and
    looked up on each row by name, so every template of that run type must select
    exactly those columns. A name the loader asks for and a template omits aborts the
    write for the whole batch.

    Pins names, cardinality and order; a template adding a column beyond the declared
    header is written without it rather than detected here.
    """
    for filename, tt in _test_type_docs():
        expected = TestExecutionSQL.template_result_columns.get(tt.get("run_type"))
        if expected is None:
            continue
        columns = list(expected)
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
