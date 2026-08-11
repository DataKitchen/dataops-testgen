from unittest.mock import MagicMock, patch

import pytest


@patch("testgen.mcp.tools.reference.resolve_test_type", return_value="Alpha_Trunc")
@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_found(mock_tt_cls, _mock_resolve, db_session_mock):
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
    mock_tt_cls.get.return_value = tt

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
    """An unresolvable name returns the not-found string rather than raising —
    ``resolve_test_type`` raises, and ``get_test_type`` absorbs it."""
    from testgen.mcp.exceptions import MCPUserError
    from testgen.mcp.tools.reference import get_test_type

    with patch(
        "testgen.mcp.tools.reference.resolve_test_type",
        side_effect=MCPUserError("Unknown test type: `Nonexistent Type`."),
    ):
        result = get_test_type("Nonexistent Type")

    assert "not found" in result
    mock_tt_cls.get.assert_not_called()


@patch("testgen.mcp.tools.reference.resolve_test_type", return_value="Alpha_Trunc")
@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_resolved_but_row_missing(mock_tt_cls, _mock_resolve, db_session_mock):
    """Defensive branch: the name resolved but the row is gone."""
    mock_tt_cls.get.return_value = None

    from testgen.mcp.tools.reference import get_test_type

    assert "not found" in get_test_type("Alpha Truncation")


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


# --- column_profile_fields_resource ---


def test_column_profile_fields_resource_has_five_sections():
    from testgen.mcp.tools.reference import column_profile_fields_resource

    result = column_profile_fields_resource()

    assert "TestGen Column Profile Fields Reference" in result
    assert "## All Column Types" in result
    assert "## Alpha" in result
    assert "## Numeric" in result
    assert "## Datetime" in result
    assert "## Boolean" in result


def test_general_type_prose_lists_match_the_enum():
    """The server instructions and the resource intro both enumerate general types in prose.

    A stale list advertises a value ``parse_general_type`` rejects, which is the exact
    dead end the vocabulary is meant to prevent. Order follows the enum declaration.
    """
    from testgen.common.models.data_column import GeneralType
    from testgen.mcp.server import SERVER_INSTRUCTIONS
    from testgen.mcp.tools.reference import column_profile_fields_resource

    expected = " / ".join(general_type.value for general_type in GeneralType)

    assert expected in SERVER_INSTRUCTIONS
    assert expected in column_profile_fields_resource()


def test_column_profile_fields_resource_lists_all_pii_redacted_fields():
    """The footer must name every redactable field so the LLM can interpret `[PII Redacted]` markers."""
    from testgen.mcp.tools.reference import column_profile_fields_resource

    result = column_profile_fields_resource()

    # Friendly labels mirroring PROFILING_PII_FIELDS from testgen.common.pii_masking.
    expected_labels = (
        "Frequent Values",
        "Minimum Text",
        "Maximum Text",
        "Minimum Value",
        "Minimum Value > 0",
        "Maximum Value",
        "Minimum Date",
        "Maximum Date",
    )
    for label in expected_labels:
        assert label in result, f"Expected `{label}` to be named in the redaction note"


def test_column_profile_fields_resource_describes_redaction_trigger():
    from testgen.mcp.tools.reference import column_profile_fields_resource

    result = column_profile_fields_resource()

    # The redaction trigger: column is PII-flagged AND caller lacks permission to view PII.
    assert "PII" in result
    assert "permission to view PII" in result


def test_column_profile_fields_resource_describes_per_type_fields():
    """Each section should at least mention the most distinctive field for that type."""
    from testgen.mcp.tools.reference import column_profile_fields_resource

    result = column_profile_fields_resource()

    # All-types section
    assert "Row Count" in result
    assert "Hygiene Issues" in result
    # Alpha
    assert "Minimum Length" in result
    assert "Frequent Values" in result
    assert "Standard Pattern Match" in result
    # Numeric
    assert "Minimum Value" in result
    assert "Median Value" in result
    # Datetime
    assert "Minimum Date" in result
    assert "Before 1 Year" in result
    # Boolean
    assert "## Boolean Columns" in result


# --- server instructions reference the new resource ---


def test_server_instructions_reference_column_profile_fields_resource():
    """The LLM relies on SERVER_INSTRUCTIONS to learn which resources to consult.

    The new resource must be named alongside test-types and hygiene-issue-types so
    the LLM knows when to look up column-profile field semantics.
    """
    from testgen.mcp.server import SERVER_INSTRUCTIONS

    assert "testgen://column-profile-fields" in SERVER_INSTRUCTIONS
    # Sanity check the existing references are still present.
    assert "testgen://test-types" in SERVER_INSTRUCTIONS
    assert "testgen://hygiene-issue-types" in SERVER_INSTRUCTIONS


# ---------------------------------------------------------------------------
# connection_parameters_resource
# ---------------------------------------------------------------------------


def test_connection_parameters_index_lists_flavors():
    from testgen.mcp.tools.reference import connection_parameters_index_resource

    out = connection_parameters_index_resource()
    # Accepted sql_flavor labels.
    assert "PostgreSQL" in out and "Azure SQL Database" in out and "Salesforce Data 360" in out
    # Each links to its per-flavor resource (keyed by code).
    assert "testgen://connection-parameters/postgresql" in out
    assert "testgen://connection-parameters/salesforce_data360" in out


def test_connection_parameters_resource_unknown_flavor():
    from testgen.mcp.exceptions import MCPUserError
    from testgen.mcp.tools.reference import connection_parameters_resource

    with pytest.raises(MCPUserError) as exc:
        connection_parameters_resource("not_a_flavor")
    msg = str(exc.value)
    assert "snowflake" in msg and "salesforce_data360" in msg


def test_connection_parameters_resource_postgresql_single_mode():
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("postgresql")
    assert "PostgreSQL Connection Parameters" in out
    assert "Host" in out and "Username" in out
    assert "Required (host mode)" in out  # Host/Port/Database
    # URL alternative is advertised.
    assert "connect by URL" in out
    # Single-mode flavor: no connection_mode instruction.
    assert "Set `connection_mode`" not in out


def test_connection_parameters_resource_snowflake_both_modes():
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("snowflake")
    assert "Mode: Key-Pair" in out
    assert "Mode: Password" in out
    assert "Private Key" in out
    assert "Warehouse" in out
    assert "Set `connection_mode`" in out
    assert 'connection_mode="Key-Pair"' in out


def test_connection_parameters_resource_databricks_pat_fields():
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("databricks")
    assert "Mode: Access Token" in out
    assert "Mode: Service Principal (OAuth)" in out
    assert "Catalog" in out
    assert "HTTP Path" in out
    assert "Client ID" in out


def test_connection_parameters_resource_port_default_note():
    """The Port row documents the flavor's conventional default port (doc-only —
    the field stays required; the LLM supplies the default when the user doesn't)."""
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("postgresql")
    assert "Default for PostgreSQL is 5432" in out
    assert "Required (host mode)" in out  # Port requirement unchanged


def test_connection_parameters_resource_port_default_per_flavor():
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("sap_hana")
    assert "Default for SAP HANA is 39015" in out


def test_connection_parameters_resource_marks_secrets():
    from testgen.mcp.tools.reference import connection_parameters_resource

    out = connection_parameters_resource("bigquery")
    assert "Service Account Key" in out
    assert "Secret" in out
    # No URL alternative for BigQuery.
    assert "connect by URL" not in out


# --- Schema exclusion from the test-type catalog ---


@patch("testgen.mcp.tools.reference.TestType")
def test_test_types_resource_applies_public_filter(mock_tt_cls, db_session_mock):
    """The catalog is filtered to the publicly-offered types, not just the active ones."""
    mock_tt_cls.select_where.return_value = []

    from testgen.mcp.tools.reference import test_types_resource

    test_types_resource()

    mock_tt_cls.is_public.assert_called_once()
    assert mock_tt_cls.is_public.return_value in mock_tt_cls.select_where.call_args.args


@patch("testgen.mcp.tools.reference.TestType")
def test_get_test_type_rejects_non_public_type(mock_tt_cls, db_session_mock):
    """Non-public types are absent from every test-type surface, single-item lookup included."""
    from testgen.common.enums import MonitorType
    from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES

    schema_type = MagicMock()
    schema_type.test_type = MonitorType.SCHEMA.value
    schema_type.test_name_short = "Schema"
    mock_tt_cls.get.return_value = schema_type
    assert MonitorType.SCHEMA.value in NON_PUBLIC_TEST_TYPES

    from testgen.mcp.tools.reference import get_test_type

    with patch("testgen.mcp.tools.reference.resolve_test_type", return_value=MonitorType.SCHEMA.value):
        result = get_test_type("Schema")

    assert "not found" in result
    assert MonitorType.SCHEMA.value not in result
