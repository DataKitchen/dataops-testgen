import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen
from testgen.commands.queries.execute_tests_query import TestExecutionSQL
from testgen.common.models.profile_result import MeasureAcquisition, ProfileResult
from testgen.common.models.test_definition import StatisticalTechnique, TestAlgorithm

YAML_DIR = Path(testgen.__file__).parent / "template" / "dbsetup_test_types"

ALGORITHMS = {a.value for a in TestAlgorithm}
TECHNIQUES = {t.value for t in StatisticalTechnique}
HEALTH_DIMENSIONS = {"Schema Drift", "Data Drift", "Statistical Drift", "Volume", "Freshness"}


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", re.sub(r"/\*.*?\*/", "", sql, flags=re.S))


def _selected_result_columns(sql: str) -> list[str]:
    """Result-column names a template's SELECT list produces, in selection order.

    Covers both forms the templates use: ``expr AS alias`` and a bare column reference
    selected on its own line. Names are matched against the columns the loader knows
    about, so keywords and intermediate expressions fall away.
    """
    known = set(TestExecutionSQL.result_columns).union(*TestExecutionSQL.template_result_columns.values())
    return [
        name
        for match in re.finditer(
            r"\bAS\s+([a-z_][a-z0-9_]*)\b|^[ \t]*([a-z_][a-z0-9_]*)[ \t]*,[ \t]*$",
            _strip_sql_comments(sql),
            re.I | re.M,
        )
        if (name := (match.group(1) or match.group(2)).lower()) in known
    ]


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
    exactly those columns, in that order.

    The match is exact in both directions. A name the loader asks for and a template
    omits aborts the write for the whole batch; a column a template selects and the
    header omits is dropped on write, landing NULL with no error at all.
    """
    for filename, tt in _test_type_docs():
        expected = TestExecutionSQL.template_result_columns.get(tt.get("run_type"))
        if expected is None:
            continue
        columns = list(expected)
        for template in tt.get("test_templates") or []:
            selected = _selected_result_columns(template["template"])
            assert selected == columns, (
                f"{filename} [{template['sql_flavor']}]: output columns {selected}, expected {columns}"
            )


@pytest.mark.unit
def test_test_types_comparing_to_skip_errors_declare_it_as_a_parameter():
    """The form offers Threshold Error Count only through default_parm_columns, so a test type
    whose templates compare a result to {SKIP_ERRORS} must declare it, and one that never does
    must not offer it."""
    for filename, tt in _test_type_docs():
        templates = [template["template"] for template in tt.get("test_templates") or []]
        compares = any(re.search(r"[<>]=?\s*\{SKIP_ERRORS\}", template) for template in templates)
        declared = "skip_errors" in (tt.get("default_parm_columns") or "").split(",")
        assert compares == declared, (
            f"{filename}: templates {'compare' if compares else 'never compare'} a result to {{SKIP_ERRORS}}, "
            f"but skip_errors is {'not ' if not declared else ''}in default_parm_columns"
        )


@pytest.mark.unit
def test_table_comparison_baselines_from_sampled_measures_skip_sampled_profiles():
    """A Table Comparison test compares exactly, so a baseline read from a measure that a sampled
    profile takes from the sample would fail on the whole table."""
    sampled = {
        column for column, acquisition in ProfileResult.measure_acquisition.items()
        if acquisition in (MeasureAcquisition.SAMPLEABLE, MeasureAcquisition.SAMPLEABLE_COUNT)
    }
    for filename, tt in _test_type_docs():
        if "Table Comparison" not in (tt.get("generation_sets") or []) or tt.get("selection_criteria") in (None, "TEMPLATE"):
            continue
        reads = set(re.findall(r"[a-z_]+", tt.get("default_parm_values") or "")) & sampled
        if reads:
            assert "sample_ratio IS NULL" in tt["selection_criteria"], (
                f"{filename}: baseline reads {sorted(reads)}, which a sampled profile measures on the sample"
            )


DECLARABLE_GENERAL_TYPES = {"A", "N", "D", "B", "T"}


@pytest.mark.unit
def test_column_general_types_are_valid_codes():
    # X is a catch-all whose columns validation never checks, so declaring it would mean nothing.
    for filename, tt in _test_type_docs():
        codes = tt.get("column_general_types")
        if codes is None:
            continue
        assert isinstance(codes, list) and codes, f"{filename}: column_general_types must be a non-empty list"
        assert set(codes) <= DECLARABLE_GENERAL_TYPES, f"{filename}: {codes}"
        assert len(codes) == len(set(codes)), f"{filename}: duplicate codes in {codes}"


@pytest.mark.unit
def test_only_column_scope_types_declare_column_general_types():
    for filename, tt in _test_type_docs():
        if tt.get("column_general_types") is not None:
            assert tt["test_scope"] == "column", filename


@pytest.mark.unit
def test_column_general_types_include_every_general_type_generation_selects():
    # A generated test must never fail its own type check.
    for filename, tt in _test_type_docs():
        codes = tt.get("column_general_types")
        if codes is None or not tt.get("selection_criteria"):
            continue
        for selected in re.findall(r"general_type\s*=\s*'([A-Z])'", tt["selection_criteria"]):
            assert selected in codes, f"{filename}: selects general_type {selected} but declares {codes}"
