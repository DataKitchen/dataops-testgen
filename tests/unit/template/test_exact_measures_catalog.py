"""Test types and hygiene issues state the profile measures they need measured exactly."""

import re
from pathlib import Path

import pytest
from yaml import safe_load

import testgen
from testgen.common.models.profile_result import ProfileResult
from testgen.testing.exact_measures import undeclared_sampled_reads

pytestmark = pytest.mark.unit

TEMPLATE_DIR = Path(testgen.__file__).parent / "template"

# Test types that read a sampled measure without declaring it, and why that is safe.
UNDECLARED_SAMPLED_READS: dict[str, str] = {
    "Alpha_Trunc": "reads sampled measures only to decide whether to generate; its threshold is the exact max length",
    "Distinct_Value_Ct": "reads frequent values only to decide whether to generate; its threshold is the exact distinct count",
    "Email_Format": "reads the sampled pattern only to decide whether to generate; the test checks every value",
    "Street_Addr_Pattern": "reads sampled measures only to decide whether to generate; its threshold is fixed",
}


def _test_types() -> list[dict]:
    return [safe_load(path.read_text())["test_types"] for path in sorted((TEMPLATE_DIR / "dbsetup_test_types").glob("*.yaml"))]


def _hygiene_issue_types() -> list[dict]:
    return [
        safe_load(path.read_text())["profile_anomaly_types"]
        for path in sorted((TEMPLATE_DIR / "dbsetup_anomaly_types").glob("*.yaml"))
    ]


def _selection_types() -> list[dict]:
    return [tt for tt in _test_types() if tt.get("selection_criteria") not in (None, "TEMPLATE")]


def test_every_declared_measure_is_a_profiling_measure():
    for tt in _selection_types():
        ProfileResult.apply_exact_measures(tt["selection_criteria"], tt.get("exact_measures"))
    for issue in _hygiene_issue_types():
        ProfileResult.apply_exact_measures(issue["anomaly_criteria"], issue.get("exact_measures"))


def test_no_criteria_check_how_a_measure_was_acquired_by_hand():
    criteria = [(tt["test_type"], tt.get("selection_criteria") or "") for tt in _test_types()] + [
        (issue["anomaly_type"], issue["anomaly_criteria"]) for issue in _hygiene_issue_types()
    ]
    for name, text in criteria:
        assert not re.search(r"\b(sample_ratio|percentile_method)\b", text), (
            f"{name}: declare the measure in exact_measures or an {{EXACT:...}} token instead"
        )


def test_only_test_types_generated_from_selection_criteria_declare_exact_measures():
    for tt in _test_types():
        if tt.get("exact_measures"):
            assert tt.get("selection_criteria") not in (None, "TEMPLATE"), tt["test_type"]


def test_only_column_hygiene_issues_declare_exact_measures():
    for issue in _hygiene_issue_types():
        if issue.get("exact_measures"):
            assert issue["data_object"] == "Column", issue["anomaly_type"]


def test_every_sampled_measure_a_test_type_reads_is_declared_or_explained():
    for tt in _selection_types():
        undeclared = undeclared_sampled_reads(tt)
        if tt["test_type"] in UNDECLARED_SAMPLED_READS:
            assert undeclared, f"{tt['test_type']} no longer reads an undeclared sampled measure: remove its entry"
        else:
            assert not undeclared, (
                f"{tt['test_type']} reads {sorted(undeclared)}, which a sampled profile takes from the sample: "
                "declare them in exact_measures, or explain in UNDECLARED_SAMPLED_READS why sampling is safe"
            )


def test_every_undeclared_read_names_a_real_test_type():
    assert set(UNDECLARED_SAMPLED_READS) <= {tt["test_type"] for tt in _test_types()}
