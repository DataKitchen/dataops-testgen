from unittest.mock import MagicMock, patch

import pytest
import yaml

from testgen.common.models.scores import (
    SCORE_CARD_NULL_DRILLDOWN,
    SCORE_CATEGORIES,
    ScoreCategory,
    ScoreDefinition,
    ScoreDefinitionCriteria,
)
from testgen.common.models.test_definition import TestDefinition, TestDefinitionSummary, TestType, TestTypeSummary
from testgen.common.read_file import get_template_files
from testgen.utils import format_score_card, format_score_card_breakdown, format_score_card_issues

pytestmark = pytest.mark.unit

VALID_IMPACT_DIMENSIONS = {"Reliability", "Conformance", "Regularity", "Usability"}


# --- YAML completeness ---

def _load_yaml_files(subfolder: str, mask: str) -> list[tuple[str, dict]]:
    results = []
    for entry in get_template_files(mask, sub_directory=subfolder):
        with entry.open("r") as f:
            data = yaml.safe_load(f)
        results.append((entry.name, data))
    return results


@pytest.fixture(scope="module")
def test_type_yamls():
    return _load_yaml_files("dbsetup_test_types", r"test_types_.*\.yaml")


@pytest.fixture(scope="module")
def anomaly_type_yamls():
    return _load_yaml_files("dbsetup_anomaly_types", r"profile_anomaly_types_.*\.yaml")


def test_all_test_type_yamls_have_impact_dimension(test_type_yamls):
    missing = [name for name, data in test_type_yamls if "impact_dimension" not in data.get("test_types", {})]
    assert not missing, f"Missing impact_dimension in test type YAMLs: {missing}"


def test_all_test_type_yaml_impact_dimensions_are_valid(test_type_yamls):
    invalid = [
        (name, data["test_types"]["impact_dimension"])
        for name, data in test_type_yamls
        if data.get("test_types", {}).get("impact_dimension") not in VALID_IMPACT_DIMENSIONS
    ]
    assert not invalid, f"Invalid impact_dimension values: {invalid}"


def test_all_anomaly_type_yamls_have_impact_dimension(anomaly_type_yamls):
    missing = [
        name for name, data in anomaly_type_yamls
        if "impact_dimension" not in data.get("profile_anomaly_types", {})
    ]
    assert not missing, f"Missing impact_dimension in anomaly type YAMLs: {missing}"


def test_all_anomaly_type_yaml_impact_dimensions_are_valid(anomaly_type_yamls):
    invalid = [
        (name, data["profile_anomaly_types"]["impact_dimension"])
        for name, data in anomaly_type_yamls
        if data.get("profile_anomaly_types", {}).get("impact_dimension") not in VALID_IMPACT_DIMENSIONS
    ]
    assert not invalid, f"Invalid impact_dimension values: {invalid}"


# --- ScoreCategory ---

def test_impact_dimension_in_score_category_enum():
    assert ScoreCategory.impact_dimension.value == "impact_dimension"


def test_impact_dimension_in_score_categories_list():
    assert "impact_dimension" in SCORE_CATEGORIES


# --- ORM annotations ---

def test_test_type_orm_has_impact_dimension_column():
    assert hasattr(TestType, "impact_dimension")


def test_test_definition_orm_has_impact_dimension_column():
    assert hasattr(TestDefinition, "impact_dimension")


def test_test_definition_summary_has_impact_dimension_annotation():
    assert "impact_dimension" in TestDefinitionSummary.__annotations__


def test_test_type_summary_has_default_impact_dimension_annotation():
    assert "default_impact_dimension" in TestTypeSummary.__annotations__


def test_summary_columns_include_default_impact_dimension_label():
    from testgen.common.models.test_definition import TestDefinition as TD
    labels = {
        col.key if hasattr(col, "key") else getattr(col, "name", None)
        for col in TD._summary_columns
        if hasattr(col, "key") or hasattr(col, "name")
    }
    assert "default_impact_dimension" in labels


# --- format_score_card categories_label ---

def _make_definition(category: ScoreCategory | None = None) -> MagicMock:
    defn = MagicMock()
    defn.total_score = True
    defn.cde_score = True
    defn.category = category
    return defn


def test_format_score_card_impact_dimension_label():
    defn = _make_definition(ScoreCategory.impact_dimension)
    card = {
        "id": None, "project_code": "p", "name": "n",
        "score": None, "cde_score": None, "profiling_score": None, "testing_score": None,
        "categories": [], "history": [], "definition": defn,
    }
    result = format_score_card(card)
    assert result["categories_label"] == "Impact Dimension"


def test_format_score_card_dq_dimension_label_unchanged():
    defn = _make_definition(ScoreCategory.dq_dimension)
    card = {
        "id": None, "project_code": "p", "name": "n",
        "score": None, "cde_score": None, "profiling_score": None, "testing_score": None,
        "categories": [], "history": [], "definition": defn,
    }
    result = format_score_card(card)
    assert result["categories_label"] == "Quality Dimension"


def test_format_score_card_no_category_gives_none_label():
    defn = _make_definition(None)
    card = {
        "id": None, "project_code": "p", "name": "n",
        "score": None, "cde_score": None, "profiling_score": None, "testing_score": None,
        "categories": [], "history": [], "definition": defn,
    }
    result = format_score_card(card)
    assert result["categories_label"] is None


# --- format_score_card_breakdown / format_score_card_issues ---

def test_format_score_card_breakdown_impact_dimension_column():
    row = {"impact_dimension": "Reliability", "impact": 0.5, "score": 0.9, "issue_ct": 3, "table_groups_id": None}
    result = format_score_card_breakdown([row], "impact_dimension")
    assert result["columns"] == ["impact_dimension", "impact", "score", "issue_ct"]
    assert result["items"][0]["impact_dimension"] == "Reliability"


def test_format_score_card_issues_impact_dimension_includes_column():
    row = {"type": "Null Values", "status": "Definite", "detail": "x", "time": 1000, "column": "col_a", "id": "1", "table_group_id": "tg", "table": "t", "name": "", "run_id": "r", "issue_type": "hygiene"}
    result = format_score_card_issues([row], "impact_dimension")
    # impact_dimension is not column_name, so "column" should be in columns
    assert "column" in result["columns"]


# --- get_score_card_issues: template routing and filter generation ---

def _make_score_definition(group_by_field: bool = True) -> ScoreDefinition:
    defn = ScoreDefinition()
    defn.project_code = "proj"
    defn.criteria = ScoreDefinitionCriteria.from_filters(
        [{"field": "table_groups_name", "value": "tg1", "others": []}],
        group_by_field=group_by_field,
    )
    return defn



def test_get_score_card_issues_uses_impact_dimension_template():
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_session_fn.return_value.execute.return_value = mock_result
        with patch("testgen.common.models.scores.read_template_sql_file", return_value="SELECT 1") as mock_read:
            defn.get_score_card_issues("score", "impact_dimension", "Reliability")
            mock_read.assert_called_once_with(
                "get_score_card_issues_by_impact_dimension.sql", sub_directory="score_cards"
            )


def test_get_score_card_issues_uses_dq_dimension_template():
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_session_fn.return_value.execute.return_value = mock_result
        with patch("testgen.common.models.scores.read_template_sql_file", return_value="SELECT 1") as mock_read:
            defn.get_score_card_issues("score", "dq_dimension", "Accuracy")
            mock_read.assert_called_once_with(
                "get_score_card_issues_by_dimension.sql", sub_directory="score_cards"
            )


def test_get_score_card_issues_impact_dimension_filter_normal_value():
    defn = _make_score_definition()
    # Use a real template so we can inspect placeholder replacement
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        captured_query = {}
        def capture(q, params=None):
            captured_query["sql"] = str(q)
            return mock_result
        mock_session_fn.return_value.execute.side_effect = capture

        template = (
            "WHERE {filters} AND {value_filter}"
            "{profiling_impact_dimension_filter}"
            "{test_impact_dimension_filter}"
        )
        with patch("testgen.common.models.scores.read_template_sql_file", return_value=template):
            defn.get_score_card_issues("score", "impact_dimension", "Reliability")

    sql = captured_query["sql"]
    assert "types.impact_dimension = :value" in sql
    assert "test_results.impact_dimension = :value" in sql


def test_get_score_card_issues_impact_dimension_filter_null_drilldown():
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        captured_query = {}
        def capture(q, params=None):
            captured_query["sql"] = str(q)
            return mock_result
        mock_session_fn.return_value.execute.side_effect = capture

        template = (
            "WHERE {filters} AND {value_filter}"
            "{profiling_impact_dimension_filter}"
            "{test_impact_dimension_filter}"
        )
        with patch("testgen.common.models.scores.read_template_sql_file", return_value=template):
            defn.get_score_card_issues("score", "impact_dimension", SCORE_CARD_NULL_DRILLDOWN)

    sql = captured_query["sql"]
    assert "types.impact_dimension IS NULL" in sql
    assert "test_results.impact_dimension IS NULL" in sql


def test_get_score_card_issues_dq_dimension_filter_does_not_leak_impact_placeholders():
    """dq_dimension path must leave impact_dimension placeholders empty."""
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        captured_query = {}
        def capture(q, params=None):
            captured_query["sql"] = str(q)
            return mock_result
        mock_session_fn.return_value.execute.side_effect = capture

        template = (
            "WHERE {filters} AND {value_filter}"
            "{dq_dimension_filter}"
            "{profiling_impact_dimension_filter}"
            "{test_impact_dimension_filter}"
        )
        with patch("testgen.common.models.scores.read_template_sql_file", return_value=template):
            defn.get_score_card_issues("score", "dq_dimension", "Accuracy")

    sql = captured_query["sql"]
    assert "impact_dimension" not in sql


# --- get_score_card_breakdown: join condition for impact_dimension ---

def test_get_score_card_breakdown_impact_dimension_uses_null_safe_join():
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        captured_query = {}
        def capture(q):
            captured_query["sql"] = str(q)
            return mock_result
        mock_session_fn.return_value.execute.side_effect = capture

        template = "{join_condition}"
        with patch("testgen.common.models.scores.read_template_sql_file", return_value=template):
            defn.get_score_card_breakdown("score", "impact_dimension")

    sql = captured_query["sql"]
    # impact_dimension uses the OR IS NULL pattern, not a simple equality join
    assert "IS NULL" in sql
    assert "impact_dimension" in sql


def test_get_score_card_breakdown_uses_impact_dimension_template():
    defn = _make_score_definition()
    with patch("testgen.common.models.scores.get_current_session") as mock_session_fn:
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = []
        mock_session_fn.return_value.execute.return_value = mock_result
        with patch("testgen.common.models.scores.read_template_sql_file", return_value="{join_condition}{columns}{group_by}{filters}{records_count_filters}{non_null_columns}") as mock_read:
            defn.get_score_card_breakdown("score", "impact_dimension")
            mock_read.assert_called_once_with(
                "get_score_card_breakdown_by_impact_dimension.sql", sub_directory="score_cards"
            )
