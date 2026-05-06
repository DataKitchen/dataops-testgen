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
    tt.impact_dimension = "Conformance"
    tt.dq_dimension = "Accuracy"
    tt.test_scope = "column"
    tt.except_message = "Alpha truncation detected"
    tt.usage_notes = "Best for VARCHAR columns"
    mock_tt_cls.select_where.return_value = [tt]

    from testgen.mcp.tools.reference import get_test_type

    result = get_test_type("Alpha Truncation")

    assert "Alpha Truncation" in result
    assert "Alpha_Trunc" not in result
    assert "Conformance" in result
    assert "Accuracy" in result
    assert "column" in result
    assert "truncated" in result.lower()


@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_not_found(mock_tt_cls, db_session_mock):
    mock_tt_cls.select_where.return_value = []

    from testgen.mcp.tools.reference import get_test_type

    result = get_test_type("Nonexistent Type")

    assert "not found" in result


@patch("testgen.mcp.tools.reference.TestType")
def test_test_types_resource(mock_tt_cls, db_session_mock):
    tt1 = MagicMock()
    tt1.test_type = "Alpha_Trunc"
    tt1.test_name_short = "Alpha Truncation"
    tt1.impact_dimension = "Conformance"
    tt1.dq_dimension = "Accuracy"
    tt1.test_scope = "column"
    tt1.test_description = "Checks truncation"
    tt2 = MagicMock()
    tt2.test_type = "Unique_Pct"
    tt2.test_name_short = "Unique Percent"
    tt2.impact_dimension = "Usability"
    tt2.dq_dimension = "Uniqueness"
    tt2.test_scope = "column"
    tt2.test_description = "Checks unique percentage"
    mock_tt_cls.select_where.return_value = [tt1, tt2]

    from testgen.mcp.tools.reference import test_types_resource

    result = test_types_resource()

    assert "Alpha Truncation" in result
    assert "Unique Percent" in result
    assert "Alpha_Trunc" not in result
    assert "Unique_Pct" not in result
    assert "Conformance" in result
    assert "Usability" in result
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
    assert "Quality Dimensions" in result
    assert "Test Scopes" in result
    assert "Disposition" in result
    assert "Monitor Types" not in result

    # Hygiene-issue additions (TG-1029):
    assert "Profiling Run" in result
    assert "Hygiene Issue" in result
    assert "## Hygiene Issue Likelihood" in result
    assert "Definite" in result
    assert "Likely" in result
    assert "Possible" in result
    assert "PII Risk" in result
    # All three disposition values defined under one section:
    assert "Confirmed" in result
    assert "Dismissed" in result
    assert "Muted" in result
    # Recency was added during the migration:
    assert "Recency" in result
    # Impact Dimensions section + all four values:
    assert "## Impact Dimensions" in result
    assert "Reliability" in result
    assert "Conformance" in result
    assert "Regularity" in result
    assert "Usability" in result


@patch("testgen.mcp.tools.reference.HygieneIssueType")
def test_hygiene_issue_types_resource_basic(mock_type_cls, db_session_mock):
    t1 = MagicMock()
    t1.name = "Personally Identifiable Information"
    t1.impact_dimension = "Conformance"
    t1.dq_dimension = "Validity"
    t1.likelihood = "Potential PII"
    t1.description = "PII description."
    t1.suggested_action = "Handle PII carefully."
    t2 = MagicMock()
    t2.name = "Non-Standard Blank Values"
    t2.impact_dimension = "Usability"
    t2.dq_dimension = "Completeness"
    t2.likelihood = "Definite"
    t2.description = "Blanks description."
    t2.suggested_action = "Cleanse blanks."
    mock_type_cls.select_where.return_value = [t1, t2]

    from testgen.mcp.tools.reference import hygiene_issue_types_resource

    result = hygiene_issue_types_resource()

    # Header order: Issue Type | Impact Dimension | Quality Dimension | Likelihood | Description | Suggested Action
    header_line = next(line for line in result.split("\n") if line.startswith("| Issue Type"))
    assert header_line == "| Issue Type | Impact Dimension | Quality Dimension | Likelihood | Description | Suggested Action |"
    # All values surface:
    assert "Personally Identifiable Information" in result
    assert "Non-Standard Blank Values" in result
    assert "Potential PII" in result
    assert "Definite" in result
    assert "Handle PII carefully." in result


@patch("testgen.mcp.tools.reference.HygieneIssueType")
def test_hygiene_issue_types_resource_orders_by_name(mock_type_cls, db_session_mock):
    from testgen.common.models.hygiene_issue import HygieneIssueType
    from testgen.mcp.tools.reference import hygiene_issue_types_resource

    mock_type_cls.select_where.return_value = []
    mock_type_cls.name = HygieneIssueType.name

    hygiene_issue_types_resource()

    # ``select_where`` was called with order_by tuple containing the name column.
    mock_type_cls.select_where.assert_called_once()
    kwargs = mock_type_cls.select_where.call_args.kwargs
    assert "order_by" in kwargs
    assert kwargs["order_by"][0] is HygieneIssueType.name


@patch("testgen.mcp.tools.reference.HygieneIssueType")
def test_hygiene_issue_types_resource_empty(mock_type_cls, db_session_mock):
    mock_type_cls.select_where.return_value = []

    from testgen.mcp.tools.reference import hygiene_issue_types_resource

    result = hygiene_issue_types_resource()
    assert "No hygiene issue types found" in result
