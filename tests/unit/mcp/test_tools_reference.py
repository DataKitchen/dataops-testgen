from unittest.mock import MagicMock, patch


@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_found(mock_tt_cls, db_session_mock):
    tt = MagicMock()
    tt.test_type = "Alpha_Trunc"
    tt.test_name_short = "Alpha Truncation"
    tt.test_name_long = "Alphabetic Truncation Test"
    tt.test_description = "Checks for truncated alphabetic values"
    tt.measure_uom = "Pct"
    tt.measure_uom_description = "Percentage of truncated values"
    tt.threshold_description = "Maximum allowed truncation rate"
    tt.dq_dimension = "Accuracy"
    tt.test_scope = "column"
    tt.except_message = "Alpha truncation detected"
    tt.usage_notes = "Best for VARCHAR columns"
    mock_tt_cls.get.return_value = tt

    from testgen.mcp.tools.reference import get_test_type

    result = get_test_type("Alpha_Trunc")

    assert "Alpha Truncation" in result
    assert "Accuracy" in result
    assert "column" in result
    assert "truncated" in result.lower()


@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_not_found(mock_tt_cls, db_session_mock):
    mock_tt_cls.get.return_value = None

    from testgen.mcp.tools.reference import get_test_type

    result = get_test_type("Nonexistent_Type")

    assert "not found" in result


@patch("testgen.mcp.tools.reference.TestType")
def test_test_types_resource(mock_tt_cls, db_session_mock):
    tt1 = MagicMock()
    tt1.test_type = "Alpha_Trunc"
    tt1.test_name_short = "Alpha Truncation"
    tt1.dq_dimension = "Accuracy"
    tt1.test_scope = "column"
    tt1.test_description = "Checks truncation"
    tt2 = MagicMock()
    tt2.test_type = "Unique_Pct"
    tt2.test_name_short = "Unique Percent"
    tt2.dq_dimension = "Uniqueness"
    tt2.test_scope = "column"
    tt2.test_description = "Checks unique percentage"
    mock_tt_cls.select_where.return_value = [tt1, tt2]

    from testgen.mcp.tools.reference import test_types_resource

    result = test_types_resource()

    assert "Alpha_Trunc" in result
    assert "Unique_Pct" in result
    assert "Accuracy" in result
    assert "Uniqueness" in result


@patch("testgen.mcp.tools.reference.TestType")
def test_test_types_resource_empty(mock_tt_cls, db_session_mock):
    mock_tt_cls.select_where.return_value = []

    from testgen.mcp.tools.reference import test_types_resource

    result = test_types_resource()

    assert "No test types found" in result


def test_glossary_resource():
    from testgen.mcp.tools.reference import glossary_resource

    result = glossary_resource()

    assert "Entity Hierarchy" in result
    assert "Result Statuses" in result
    assert "Data Quality Dimensions" in result
    assert "Test Scopes" in result
    assert "Disposition" in result
    assert "Monitor Types" not in result
