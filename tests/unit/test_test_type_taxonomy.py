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
def test_query_templates_agree_on_result_column_order():
    """QUERY results are bulk-loaded positionally under one header taken from a single
    template, so every QUERY template of a flavor must order its output columns alike.
    Covers the four result_* columns, the only ones that can appear solely as top-level
    aliases."""
    canonical = ["result_signal", "result_code", "result_message", "result_measure"]
    for filename, tt in _test_type_docs():
        if tt.get("run_type") != "QUERY":
            continue
        for template in tt.get("test_templates") or []:
            order = [
                match.group(1).lower()
                for match in re.finditer(r"\bAS\s+(result_(?:signal|code|message|measure))\b", template["template"], re.I)
            ]
            assert order == canonical, (
                f"{filename} [{template['sql_flavor']}]: result columns ordered {order}, expected {canonical}"
            )
