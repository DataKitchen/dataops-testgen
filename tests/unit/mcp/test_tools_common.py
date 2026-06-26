from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from testgen.common.enums import Disposition, ImpactDimension, IssueLikelihood, PiiRisk, QualityDimension
from testgen.common.models.scores import ScoreCategory
from testgen.common.models.test_definition import Severity
from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.tools.common import (
    SCORE_CATEGORY_ARG_TO_COLUMN,
    SCORE_CHAIN_LEAF_TO_COLUMN,
    SCORE_FILTER_FIELD_TO_COLUMN,
    SCORE_GROUP_BY_TO_COLUMN,
    ScoreCategoryArg,
    ScoreChainLeafField,
    ScoreFilterField,
    ScoreGroupBy,
    ScoreType,
    format_disposition,
    parse_category,
    parse_disposition,
    parse_impact_dimension,
    parse_issue_likelihood_list,
    parse_pii_risk_list,
    parse_quality_dimension,
    parse_result_status,
    parse_score_filter_field,
    parse_score_group_by,
    parse_score_type,
    parse_severity,
    parse_uuid,
    resolve_hygiene_issue,
    resolve_issue_type,
    resolve_profiling_run,
    resolve_test_note,
    validate_limit,
    validate_page,
)

# --- parse_uuid ---


def test_parse_uuid_valid():
    raw = "12345678-1234-5678-1234-567812345678"
    result = parse_uuid(raw)
    assert result == UUID(raw)


def test_parse_uuid_valid_no_dashes():
    raw = "12345678123456781234567812345678"
    result = parse_uuid(raw)
    assert isinstance(result, UUID)


def test_parse_uuid_invalid():
    with pytest.raises(MCPUserError, match="not a valid UUID"):
        parse_uuid("not-a-uuid")


def test_parse_uuid_empty():
    with pytest.raises(MCPUserError, match="not a valid UUID"):
        parse_uuid("")


def test_parse_uuid_custom_label():
    with pytest.raises(MCPUserError, match="Invalid test_run_id"):
        parse_uuid("bad", label="test_run_id")


# --- parse_result_status ---


def test_parse_result_status_valid():
    assert parse_result_status("Failed") == TestResultStatus.Failed
    assert parse_result_status("Passed") == TestResultStatus.Passed
    assert parse_result_status("Warning") == TestResultStatus.Warning


def test_parse_result_status_invalid():
    with pytest.raises(MCPUserError, match="Invalid status `BadStatus`"):
        parse_result_status("BadStatus")


def test_parse_result_status_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_result_status("nope")
    for status in TestResultStatus:
        assert status.value in str(exc_info.value)


# --- parse_severity ---


def test_parse_severity_valid():
    assert parse_severity("Fail") == Severity.FAIL
    assert parse_severity("Warning") == Severity.WARNING


def test_parse_severity_invalid_names_value():
    with pytest.raises(MCPUserError, match="Invalid severity `Critical`"):
        parse_severity("Critical")


def test_parse_severity_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_severity("nope")
    for severity in Severity:
        assert severity.value in str(exc_info.value)


def test_parse_severity_case_sensitive():
    """Severity stores 'Fail' / 'Warning' verbatim; lowercase rejected by design."""
    with pytest.raises(MCPUserError, match="Invalid severity `fail`"):
        parse_severity("fail")


# --- validate_page ---


@pytest.mark.parametrize("ok", [1, 2, 99])
def test_validate_page_accepts_positive(ok):
    validate_page(ok)  # does not raise


@pytest.mark.parametrize("bad", [0, -1, -100])
def test_validate_page_rejects_below_one(bad):
    with pytest.raises(MCPUserError, match=f"Invalid page `{bad}`"):
        validate_page(bad)


# --- validate_limit ---


@pytest.mark.parametrize("ok", [1, 50, 100])
def test_validate_limit_accepts_in_range(ok):
    validate_limit(ok, 100)  # does not raise


@pytest.mark.parametrize("bad", [0, -1, 101, 1000])
def test_validate_limit_rejects_out_of_range(bad):
    with pytest.raises(MCPUserError, match=f"Invalid limit `{bad}`"):
        validate_limit(bad, 100)


def test_validate_limit_message_includes_max():
    with pytest.raises(MCPUserError, match="between 1 and 200"):
        validate_limit(0, 200)


# --- parse_disposition / format_disposition ---


@pytest.mark.parametrize(
    "user_label,expected",
    [
        ("Confirmed", Disposition.CONFIRMED),
        ("Dismissed", Disposition.DISMISSED),
        ("Muted", Disposition.INACTIVE),
    ],
)
def test_parse_disposition_user_labels_to_db_value(user_label, expected):
    assert parse_disposition(user_label) is expected


def test_parse_disposition_rejects_db_value_inactive():
    """``Inactive`` is the DB value, not user-facing — accepting it would create two
    spellings for the same disposition."""
    with pytest.raises(MCPUserError, match="Invalid disposition"):
        parse_disposition("Inactive")


def test_parse_disposition_rejects_unknown_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_disposition("Bogus")
    msg = str(exc_info.value)
    assert "Confirmed" in msg
    assert "Dismissed" in msg
    assert "Muted" in msg


def test_parse_disposition_case_sensitive():
    with pytest.raises(MCPUserError):
        parse_disposition("confirmed")


@pytest.mark.parametrize(
    "db_value,expected",
    [
        (Disposition.CONFIRMED, "Confirmed"),
        (Disposition.DISMISSED, "Dismissed"),
        (Disposition.INACTIVE, "Muted"),
    ],
)
def test_format_disposition_db_to_user_label(db_value, expected):
    assert format_disposition(db_value) == expected


def test_format_disposition_accepts_string_form():
    """Coalesce on the column produces a plain string at runtime — both forms must work."""
    assert format_disposition("Inactive") == "Muted"
    assert format_disposition("Confirmed") == "Confirmed"


def test_format_disposition_unknown_falls_through_to_string():
    assert format_disposition("WhoKnows") == "WhoKnows"


# --- parse_impact_dimension ---


@pytest.mark.parametrize("value", [d.value for d in ImpactDimension])
def test_parse_impact_dimension_valid(value):
    assert parse_impact_dimension(value) == ImpactDimension(value)


def test_parse_impact_dimension_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Invalid impact_dimension") as exc_info:
        parse_impact_dimension("BadDim")
    msg = str(exc_info.value)
    for d in ImpactDimension:
        assert d.value in msg


# --- parse_quality_dimension ---


@pytest.mark.parametrize("value", [d.value for d in QualityDimension])
def test_parse_quality_dimension_valid(value):
    assert parse_quality_dimension(value) == QualityDimension(value)


def test_parse_quality_dimension_includes_recency():
    """Recency was added during the TG-1029 enum migration; pin it as a valid value."""
    assert parse_quality_dimension("Recency") == QualityDimension.RECENCY


def test_parse_quality_dimension_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Invalid quality_dimension") as exc_info:
        parse_quality_dimension("BadDim")
    msg = str(exc_info.value)
    for d in QualityDimension:
        assert d.value in msg


# --- parse_issue_likelihood_list ---


def test_parse_issue_likelihood_list_accepts_three_filterable_values():
    result = parse_issue_likelihood_list(["Definite", "Likely", "Possible"])
    assert result == [IssueLikelihood.DEFINITE, IssueLikelihood.LIKELY, IssueLikelihood.POSSIBLE]


def test_parse_issue_likelihood_list_rejects_potential_pii():
    """``Potential PII`` is a valid IssueLikelihood enum value but NOT a valid filter input —
    PII issues are filtered separately via ``pii_risk``. Locking this prevents a future
    'fix' that allows the full enum and breaks the auto-exclude API contract."""
    with pytest.raises(MCPUserError, match="Invalid issue_likelihood"):
        parse_issue_likelihood_list(["Potential PII"])


def test_parse_issue_likelihood_list_invalid_lists_valid_values_excluding_pii():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_issue_likelihood_list(["Bogus"])
    msg = str(exc_info.value)
    assert "Definite" in msg
    assert "Likely" in msg
    assert "Possible" in msg
    assert "Potential PII" not in msg


def test_parse_issue_likelihood_list_collects_all_invalid():
    with pytest.raises(MCPUserError) as exc_info:
        parse_issue_likelihood_list(["Definite", "Bogus", "Other"])
    msg = str(exc_info.value)
    assert "Bogus" in msg
    assert "Other" in msg


def test_parse_issue_likelihood_list_empty_returns_empty():
    assert parse_issue_likelihood_list([]) == []


# --- parse_pii_risk_list ---


def test_parse_pii_risk_list_accepts_high_moderate():
    assert parse_pii_risk_list(["High", "Moderate"]) == [PiiRisk.HIGH, PiiRisk.MODERATE]


def test_parse_pii_risk_list_rejects_low():
    with pytest.raises(MCPUserError, match="Invalid pii_risk"):
        parse_pii_risk_list(["Low"])


def test_parse_pii_risk_list_collects_all_invalid():
    with pytest.raises(MCPUserError) as exc_info:
        parse_pii_risk_list(["High", "Bogus", "Wrong"])
    msg = str(exc_info.value)
    assert "Bogus" in msg
    assert "Wrong" in msg


# --- resolve_issue_type ---


def test_resolve_issue_type_found_returns_id():
    fake = MagicMock()
    fake.id = "1015"
    with patch(
        "testgen.mcp.tools.common.HygieneIssueType.select_where", return_value=[fake]
    ) as select_where:
        result = resolve_issue_type("Personally Identifiable Information")
    assert result == "1015"
    assert select_where.call_count == 1


def test_resolve_issue_type_not_found_raises_with_resource_hint():
    with patch(
        "testgen.mcp.tools.common.HygieneIssueType.select_where", return_value=[]
    ):
        with pytest.raises(MCPUserError, match="Unknown hygiene issue type") as exc_info:
            resolve_issue_type("Made-Up Type")
    assert "testgen://hygiene-issue-types" in str(exc_info.value)


# --- resolve_profiling_run ---


def _mock_perms(allowed_projects=("demo",)):
    perms = MagicMock()
    perms.has_access.side_effect = lambda code: code in allowed_projects
    return perms


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.ProfilingRun")
def test_resolve_profiling_run_happy_path(mock_pr_cls, mock_get_perms, db_session_mock):
    run = MagicMock()
    run.project_code = "demo"
    mock_pr_cls.get.return_value = run
    mock_get_perms.return_value = _mock_perms(allowed_projects=("demo",))

    result = resolve_profiling_run(str(uuid4()))

    assert result is run


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.ProfilingRun")
def test_resolve_profiling_run_unknown_run_id(mock_pr_cls, mock_get_perms, db_session_mock):
    mock_pr_cls.get.return_value = None
    mock_get_perms.return_value = _mock_perms()

    with pytest.raises(MCPResourceNotAccessible, match=r"Profiling run .* not found or not accessible"):
        resolve_profiling_run(str(uuid4()))


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.ProfilingRun")
def test_resolve_profiling_run_inaccessible_project(mock_pr_cls, mock_get_perms, db_session_mock):
    """Run exists but caller can't access its project — same unified error as unknown run."""
    run = MagicMock()
    run.project_code = "forbidden"
    mock_pr_cls.get.return_value = run
    mock_get_perms.return_value = _mock_perms(allowed_projects=("demo",))

    with pytest.raises(MCPResourceNotAccessible, match=r"Profiling run .* not found or not accessible"):
        resolve_profiling_run(str(uuid4()))


def test_resolve_profiling_run_invalid_uuid():
    with pytest.raises(MCPUserError, match="Invalid job_execution_id"):
        resolve_profiling_run("not-a-uuid")


# --- resolve_test_note ---


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.get_current_session")
def test_resolve_test_note_happy_path(mock_get_session, mock_get_perms):
    note = MagicMock()
    session = MagicMock()
    session.scalars.return_value.first.return_value = note
    mock_get_session.return_value = session
    mock_get_perms.return_value = _mock_perms()

    assert resolve_test_note(str(uuid4())) is note


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.get_current_session")
def test_resolve_test_note_missing_or_inaccessible(mock_get_session, mock_get_perms):
    """Missing note, monitor-suite parent, and forbidden project all collapse to one error."""
    session = MagicMock()
    session.scalars.return_value.first.return_value = None
    mock_get_session.return_value = session
    mock_get_perms.return_value = _mock_perms()

    with pytest.raises(MCPResourceNotAccessible, match=r"Test note .* not found or not accessible"):
        resolve_test_note(str(uuid4()))


def test_resolve_test_note_invalid_uuid():
    with pytest.raises(MCPUserError, match="Invalid test_note_id"):
        resolve_test_note("not-a-uuid")


# --- resolve_hygiene_issue ---


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.HygieneIssue")
def test_resolve_hygiene_issue_happy_path(mock_hi_cls, mock_get_perms, db_session_mock):
    issue = MagicMock()
    mock_hi_cls.get.return_value = issue
    mock_get_perms.return_value = _mock_perms()

    assert resolve_hygiene_issue(str(uuid4())) is issue


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.HygieneIssue")
def test_resolve_hygiene_issue_missing_or_inaccessible(mock_hi_cls, mock_get_perms, db_session_mock):
    """Missing issue and forbidden-project issue both collapse to one error (project scoped in the query)."""
    mock_hi_cls.get.return_value = None
    mock_get_perms.return_value = _mock_perms()

    with pytest.raises(MCPResourceNotAccessible, match=r"Hygiene issue .* not found or not accessible"):
        resolve_hygiene_issue(str(uuid4()))


def test_resolve_hygiene_issue_invalid_uuid():
    with pytest.raises(MCPUserError, match="Invalid issue_id"):
        resolve_hygiene_issue("not-a-uuid")


# --- parse_pii_category ---


def test_parse_pii_category_translates_display_label_to_stored_code():
    from testgen.mcp.tools.common import parse_pii_category
    assert parse_pii_category("ID") == "ID"
    assert parse_pii_category("Name") == "NAME"
    assert parse_pii_category("Demographic") == "DEMO"
    assert parse_pii_category("Contact") == "CONTACT"


def test_parse_pii_category_rejects_stored_code_form():
    from testgen.mcp.tools.common import parse_pii_category
    with pytest.raises(MCPUserError, match="Invalid pii_category `NAME`"):
        parse_pii_category("NAME")


def test_parse_pii_category_lists_valid_values_in_error():
    from testgen.mcp.tools.common import parse_pii_category
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_pii_category("Address")
    for label in ("ID", "Name", "Demographic", "Contact"):
        assert label in str(exc_info.value)


# --- parse_pii_risk_level ---


def test_parse_pii_risk_level_translates_label_to_stored_prefix():
    from testgen.mcp.tools.common import parse_pii_risk_level
    assert parse_pii_risk_level("High") == "A"
    assert parse_pii_risk_level("Moderate") == "B"
    assert parse_pii_risk_level("Low") == "C"


def test_parse_pii_risk_level_rejects_unknown():
    from testgen.mcp.tools.common import parse_pii_risk_level
    with pytest.raises(MCPUserError, match="Invalid pii_risk_level `Critical`"):
        parse_pii_risk_level("Critical")


# --- parse_general_type ---


def test_parse_general_type_translates_word_to_letter_code():
    from testgen.mcp.tools.common import parse_general_type
    assert parse_general_type("Alpha") == "A"
    assert parse_general_type("Numeric") == "N"
    assert parse_general_type("Datetime") == "D"
    assert parse_general_type("Boolean") == "B"
    assert parse_general_type("Time") == "T"
    assert parse_general_type("Other") == "X"


def test_parse_general_type_rejects_letter_code_input():
    from testgen.mcp.tools.common import parse_general_type
    with pytest.raises(MCPUserError, match="Invalid general_type `A`"):
        parse_general_type("A")


def test_parse_general_type_is_case_sensitive():
    from testgen.mcp.tools.common import parse_general_type
    with pytest.raises(MCPUserError):
        parse_general_type("alpha")


# --- parse_suggested_data_type ---


def test_parse_suggested_data_type_accepts_title_case():
    from testgen.common.models.data_column import SuggestedDataType
    from testgen.mcp.tools.common import parse_suggested_data_type
    assert parse_suggested_data_type("Any") is SuggestedDataType.ANY
    assert parse_suggested_data_type("Integer") is SuggestedDataType.INTEGER
    assert parse_suggested_data_type("Varchar") is SuggestedDataType.VARCHAR


def test_parse_suggested_data_type_rejects_uppercase():
    from testgen.mcp.tools.common import parse_suggested_data_type
    with pytest.raises(MCPUserError, match="Invalid suggested_data_type `INTEGER`"):
        parse_suggested_data_type("INTEGER")


def test_parse_suggested_data_type_lists_valid_values_in_error():
    from testgen.mcp.tools.common import parse_suggested_data_type
    with pytest.raises(MCPUserError) as exc_info:
        parse_suggested_data_type("Bogus")
    for label in ("Any", "Integer", "Numeric", "Varchar", "Date", "Timestamp", "Boolean"):
        assert label in str(exc_info.value)


# --- parse_column_order_by ---


def test_parse_column_order_by_accepts_display_form():
    from testgen.common.models.data_column import ColumnOrderBy
    from testgen.mcp.tools.common import parse_column_order_by
    assert parse_column_order_by("Null Ratio") is ColumnOrderBy.NULL_RATIO
    assert parse_column_order_by("Profiling Score") is ColumnOrderBy.SCORE_PROFILING
    assert parse_column_order_by("Hygiene Count") is ColumnOrderBy.HYGIENE_COUNT


def test_parse_column_order_by_rejects_snake_case():
    from testgen.mcp.tools.common import parse_column_order_by
    with pytest.raises(MCPUserError, match="Invalid order_by `null_ratio`"):
        parse_column_order_by("null_ratio")


# --- build_ilike_pattern ---


def test_build_ilike_pattern_wraps_bare_token():
    from testgen.mcp.tools.common import build_ilike_pattern
    assert build_ilike_pattern("email") == "%email%"


def test_build_ilike_pattern_escapes_literal_underscore():
    from testgen.mcp.tools.common import build_ilike_pattern
    # Column names commonly contain underscores; treat them as literal, not as SQL wildcards.
    assert build_ilike_pattern("user_id") == r"%user\_id%"


def test_build_ilike_pattern_honors_explicit_percent():
    from testgen.mcp.tools.common import build_ilike_pattern
    # Caller-supplied % means "I'm doing my own wildcards" — don't double-wrap.
    assert build_ilike_pattern("%email") == "%email"
    assert build_ilike_pattern("user%") == "user%"


def test_build_ilike_pattern_escapes_underscores_even_with_explicit_percent():
    from testgen.mcp.tools.common import build_ilike_pattern
    # The `_` escape is unconditional — explicit `%` doesn't suppress it.
    assert build_ilike_pattern("user_%") == r"user\_%"


# --- parse_score_group_by ---


@pytest.mark.parametrize("member", list(ScoreGroupBy))
def test_parse_score_group_by_user_labels(member):
    assert parse_score_group_by(member.value) is member


def test_parse_score_group_by_label_maps_to_internal_column():
    """The enum value is the user-facing label; the mapping translates to the
    internal DB column name used downstream (``ScoreCategory``, the criteria
    filter list)."""
    assert SCORE_GROUP_BY_TO_COLUMN[ScoreGroupBy.QUALITY_DIMENSION] == "dq_dimension"
    assert SCORE_GROUP_BY_TO_COLUMN[ScoreGroupBy.TABLE_GROUP] == "table_groups_name"
    assert SCORE_GROUP_BY_TO_COLUMN[ScoreGroupBy.BUSINESS_DOMAIN] == "business_domain"


@pytest.mark.parametrize(
    "internal",
    ["dq_dimension", "impact_dimension", "business_domain", "table_groups_name"],
)
def test_parse_score_group_by_rejects_internal_column_name(internal):
    """Old internal vocabulary must be rejected — the tool now speaks user labels only."""
    with pytest.raises(MCPUserError, match="Invalid group_by") as exc_info:
        parse_score_group_by(internal)
    msg = str(exc_info.value)
    # Error must point users at the new user-facing vocabulary.
    assert "Quality Dimension" in msg
    assert "Business Domain" in msg


def test_parse_score_group_by_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_score_group_by("Made Up")
    msg = str(exc_info.value)
    for member in ScoreGroupBy:
        assert member.value in msg


# --- parse_score_filter_field ---


@pytest.mark.parametrize("member", list(ScoreFilterField))
def test_parse_score_filter_field_user_labels(member):
    assert parse_score_filter_field(member.value) is member


def test_parse_score_filter_field_label_maps_to_internal_column():
    assert SCORE_FILTER_FIELD_TO_COLUMN[ScoreFilterField.BUSINESS_DOMAIN] == "business_domain"
    assert SCORE_FILTER_FIELD_TO_COLUMN[ScoreFilterField.TABLE_GROUP] == "table_groups_name"


def test_parse_score_filter_field_does_not_include_dimensions():
    """Quality Dimension / Impact Dimension are valid only as group_by, not as filter fields."""
    values = {m.value for m in ScoreFilterField}
    assert "Quality Dimension" not in values
    assert "Impact Dimension" not in values


@pytest.mark.parametrize("label", ["Quality Dimension", "Impact Dimension"])
def test_parse_score_filter_field_rejects_dimension_with_hint(label):
    """Passing a dimension as filter.field hints at group_by= usage instead."""
    with pytest.raises(MCPUserError, match=f"`{label}`") as exc_info:
        parse_score_filter_field(label)
    msg = str(exc_info.value)
    assert "group_by" in msg
    assert label in msg


@pytest.mark.parametrize(
    "internal", ["business_domain", "data_source", "table_groups_name"],
)
def test_parse_score_filter_field_rejects_internal_column_name(internal):
    with pytest.raises(MCPUserError, match="Invalid filter field") as exc_info:
        parse_score_filter_field(internal)
    msg = str(exc_info.value)
    assert "Business Domain" in msg


def test_parse_score_filter_field_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_score_filter_field("Made Up")
    msg = str(exc_info.value)
    for member in ScoreFilterField:
        assert member.value in msg


# --- parse_score_type ---


@pytest.mark.parametrize(
    "label,expected_member",
    [
        ("Total", ScoreType.TOTAL),
        ("CDE", ScoreType.CDE),
    ],
)
def test_parse_score_type_user_labels(label, expected_member):
    member = parse_score_type(label)
    assert member is expected_member


@pytest.mark.parametrize("internal", ["total", "cde"])
def test_parse_score_type_rejects_internal_or_wrong_case(internal):
    """The internal vocabulary (``total``/``cde`` lowercase) must not be
    accepted on input; only the canonical user-facing values are."""
    with pytest.raises(MCPUserError, match="Invalid score_type") as exc_info:
        parse_score_type(internal)
    msg = str(exc_info.value)
    assert "Total" in msg
    assert "CDE" in msg


def test_parse_score_type_invalid_lists_valid_values():
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_score_type("BadType")
    msg = str(exc_info.value)
    for member in ScoreType:
        assert member.value in msg


# --- parse_category ---


@pytest.mark.parametrize(
    "display_value,expected",
    [
        ("Quality Dimension", ScoreCategory.dq_dimension),
        ("Impact Dimension", ScoreCategory.impact_dimension),
        ("Table Group", ScoreCategory.table_groups_name),
        ("Data Source", ScoreCategory.data_source),
        ("Data Location", ScoreCategory.data_location),
        ("Source System", ScoreCategory.source_system),
        ("Source Process", ScoreCategory.source_process),
        ("Business Domain", ScoreCategory.business_domain),
        ("Stakeholder Group", ScoreCategory.stakeholder_group),
        ("Transform Level", ScoreCategory.transform_level),
        ("Data Product", ScoreCategory.data_product),
    ],
)
def test_parse_category_display_form_returns_column_form_enum(display_value, expected):
    """``parse_category`` accepts display-form labels and emits the column-form ``ScoreCategory``."""
    assert parse_category(display_value) is expected


def test_parse_category_translation_dict_covers_all_args():
    """Every ``ScoreCategoryArg`` member has a translation to a valid ``ScoreCategory`` column."""
    for arg in ScoreCategoryArg:
        column = SCORE_CATEGORY_ARG_TO_COLUMN[arg]
        assert ScoreCategory(column) is ScoreCategory(column)  # raises if column isn't a valid enum value


@pytest.mark.parametrize(
    "internal",
    [
        "dq_dimension",
        "impact_dimension",
        "table_groups_name",
        "data_source",
        "data_location",
        "source_system",
        "source_process",
        "business_domain",
        "stakeholder_group",
        "transform_level",
        "data_product",
    ],
)
def test_parse_category_rejects_column_form_input(internal):
    """The old column-form values must not be accepted on input — display-form only."""
    with pytest.raises(MCPUserError, match="Invalid category") as exc_info:
        parse_category(internal)
    msg = str(exc_info.value)
    # Error message must list at least one display-form value to guide the caller.
    assert "Quality Dimension" in msg


def test_parse_category_invalid_lists_display_form_values():
    """An unrelated bad value lists every display-form value in the error message."""
    with pytest.raises(MCPUserError, match="Valid values:") as exc_info:
        parse_category("Made Up")
    msg = str(exc_info.value)
    for member in ScoreCategoryArg:
        assert member.value in msg


# --- ScoreChainLeafField ---


def test_score_chain_leaf_field_values():
    assert ScoreChainLeafField.TABLE.value == "Table"
    assert ScoreChainLeafField.COLUMN.value == "Column"


def test_score_chain_leaf_to_column_mapping():
    assert SCORE_CHAIN_LEAF_TO_COLUMN[ScoreChainLeafField.TABLE] == "table_name"
    assert SCORE_CHAIN_LEAF_TO_COLUMN[ScoreChainLeafField.COLUMN] == "column_name"


# --- SqlFlavorLabel ---


def test_sql_flavor_label_set_matches_common_layer():
    """Codes covered by the MCP enum and the common-layer maps must stay in sync."""
    from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, FLAVOR_CODE_TO_LABEL
    from testgen.mcp.tools.common import SQL_FLAVOR_CODE_TO_LABEL, SQL_FLAVOR_LABEL_TO_CODE

    assert set(SQL_FLAVOR_CODE_TO_LABEL) == set(FLAVOR_CODE_TO_LABEL)
    assert set(SQL_FLAVOR_LABEL_TO_CODE.values()) == set(FLAVOR_CODE_TO_FAMILY.keys())


def test_parse_sql_flavor_returns_label_code_family():
    from testgen.mcp.tools.common import SqlFlavorLabel, parse_sql_flavor

    label, code, family = parse_sql_flavor("Azure SQL Database")
    assert label == SqlFlavorLabel.AZURE_MSSQL
    assert code == "azure_mssql"
    assert family == "mssql"


def test_parse_sql_flavor_invalid_lists_display_values():
    from testgen.mcp.tools.common import SqlFlavorLabel, parse_sql_flavor

    with pytest.raises(MCPUserError, match="Invalid sql_flavor `bogus`") as exc:
        parse_sql_flavor("bogus")
    msg = str(exc.value)
    for member in SqlFlavorLabel:
        assert member.value in msg


# --- parse_test_result_disposition ---


@pytest.mark.parametrize(
    "user_label,expected",
    [
        ("Confirmed", Disposition.CONFIRMED),
        ("Dismissed", Disposition.DISMISSED),
        ("Muted", Disposition.INACTIVE),
        ("No Decision", None),
    ],
)
def test_parse_test_result_disposition_user_labels(user_label, expected):
    from testgen.mcp.tools.common import parse_test_result_disposition

    assert parse_test_result_disposition(user_label) is expected


def test_parse_test_result_disposition_rejects_unknown_and_lists_accepted():
    from testgen.mcp.tools.common import parse_test_result_disposition

    with pytest.raises(MCPUserError) as exc:
        parse_test_result_disposition("Inactive")  # DB value, not user-facing
    msg = str(exc.value)
    for label in ("Confirmed", "Dismissed", "Muted", "No Decision"):
        assert label in msg


# --- resolve_test_result ---


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.get_current_session")
def test_resolve_test_result_happy_path(mock_session, mock_perms, db_session_mock):
    from testgen.mcp.tools.common import resolve_test_result

    result = MagicMock()
    mock_session.return_value.scalars.return_value.first.return_value = result
    mock_perms.return_value = _mock_perms(allowed_projects=("demo",))

    assert resolve_test_result(str(uuid4())) is result


@patch("testgen.mcp.tools.common.get_project_permissions")
@patch("testgen.mcp.tools.common.get_current_session")
def test_resolve_test_result_missing_or_inaccessible(mock_session, mock_perms, db_session_mock):
    from testgen.mcp.tools.common import resolve_test_result

    mock_session.return_value.scalars.return_value.first.return_value = None
    mock_perms.return_value = _mock_perms(allowed_projects=("demo",))

    with pytest.raises(MCPResourceNotAccessible, match=r"Test result .* not found or not accessible"):
        resolve_test_result(str(uuid4()))


def test_resolve_test_result_invalid_uuid():
    from testgen.mcp.tools.common import resolve_test_result

    with pytest.raises(MCPUserError, match="Invalid test_result_id"):
        resolve_test_result("not-a-uuid")


# --- Monitor helpers ---


@pytest.mark.parametrize(
    "label,expected_value",
    [
        ("freshness", "Freshness_Trend"),
        ("volume", "Volume_Trend"),
        ("schema", "Schema_Drift"),
        ("metric", "Metric_Trend"),
    ],
)
def test_parse_monitor_type_user_labels(label, expected_value):
    from testgen.mcp.tools.common import parse_monitor_type

    assert parse_monitor_type(label).value == expected_value


def test_parse_monitor_type_rejects_db_codes():
    """Internal codes like ``Freshness_Trend`` are not accepted on the input boundary —
    only the lowercase user-facing short labels are."""
    from testgen.mcp.tools.common import parse_monitor_type

    with pytest.raises(MCPUserError, match="Invalid monitor_type"):
        parse_monitor_type("Freshness_Trend")


def test_parse_monitor_type_lists_valid_values_on_error():
    from testgen.mcp.tools.common import parse_monitor_type

    with pytest.raises(MCPUserError, match="Valid values:") as exc:
        parse_monitor_type("metrics")
    msg = str(exc.value)
    for label in ("freshness", "volume", "schema", "metric"):
        assert label in msg


def test_parse_monitor_type_label_override():
    """``label`` argument lets callers tailor the error to their public arg name
    (e.g. ``list_monitored_tables`` exposes it as ``anomaly_type``)."""
    from testgen.mcp.tools.common import parse_monitor_type

    with pytest.raises(MCPUserError, match=r"Invalid anomaly_type `bogus`"):
        parse_monitor_type("bogus", "anomaly_type")


@pytest.mark.parametrize(
    "value",
    ["table_name", "anomaly_count_desc", "latest_update_desc", "row_count_change_desc"],
)
def test_parse_monitor_table_sort_accepts_documented_values(value):
    from testgen.mcp.tools.common import parse_monitor_table_sort

    assert parse_monitor_table_sort(value).value == value


def test_parse_monitor_table_sort_rejects_unknown():
    from testgen.mcp.tools.common import parse_monitor_table_sort

    with pytest.raises(MCPUserError, match="Invalid sort_by") as exc:
        parse_monitor_table_sort("alphabetical")
    msg = str(exc.value)
    for valid in ("table_name", "anomaly_count_desc", "latest_update_desc", "row_count_change_desc"):
        assert valid in msg


def test_parse_monitor_table_sort_rejects_legacy_row_count_desc():
    """Guard against the pre-review-feedback ``row_count_desc`` name accidentally
    coming back: the rename to ``row_count_change_desc`` is the canonical signal
    that the column shows a delta, not the raw current count. Drop this only when
    introducing a deliberate replacement."""
    from testgen.mcp.tools.common import parse_monitor_table_sort

    with pytest.raises(MCPUserError, match="Invalid sort_by") as exc:
        parse_monitor_table_sort("row_count_desc")
    assert "row_count_change_desc" in str(exc.value)


def test_resolve_monitored_table_group_returns_suite():
    from testgen.common.models.table_group import TableGroup
    from testgen.common.models.test_suite import TestSuite
    from testgen.mcp.tools.common import resolve_monitored_table_group

    tg = MagicMock(spec=TableGroup)
    tg.id = uuid4()
    tg.monitor_test_suite_id = uuid4()
    suite = MagicMock(spec=TestSuite)
    suite.is_monitor = True

    with (
        patch("testgen.mcp.tools.common.resolve_table_group", return_value=tg),
        patch("testgen.mcp.tools.common.TestSuite.get", return_value=suite) as mock_get,
    ):
        out_tg, out_suite = resolve_monitored_table_group(str(tg.id))

    assert out_tg is tg
    assert out_suite is suite
    assert mock_get.call_args.args[0] == tg.monitor_test_suite_id


def test_resolve_monitored_table_group_returns_none_when_unlinked():
    """Table group exists but has no monitor suite pointer."""
    from testgen.common.models.table_group import TableGroup
    from testgen.mcp.tools.common import resolve_monitored_table_group

    tg = MagicMock(spec=TableGroup)
    tg.id = uuid4()
    tg.monitor_test_suite_id = None

    with patch("testgen.mcp.tools.common.resolve_table_group", return_value=tg):
        out_tg, suite = resolve_monitored_table_group(str(tg.id))

    assert out_tg is tg
    assert suite is None


def test_resolve_monitored_table_group_returns_none_when_pointer_stale():
    """Pointer set, but suite no longer exists or no longer ``is_monitor=True``."""
    from testgen.common.models.table_group import TableGroup
    from testgen.mcp.tools.common import resolve_monitored_table_group

    tg = MagicMock(spec=TableGroup)
    tg.id = uuid4()
    tg.monitor_test_suite_id = uuid4()

    with (
        patch("testgen.mcp.tools.common.resolve_table_group", return_value=tg),
        patch("testgen.mcp.tools.common.TestSuite.get", return_value=None),
    ):
        out_tg, suite = resolve_monitored_table_group(str(tg.id))

    assert out_tg is tg
    assert suite is None


def test_resolve_monitored_table_group_raises_when_tg_inaccessible():
    """Inaccessible TG propagates ``MCPResourceNotAccessible`` from ``resolve_table_group``
    — the "not monitored" path must not mask an access failure."""
    from testgen.mcp.tools.common import resolve_monitored_table_group

    bad_id = str(uuid4())
    with (
        patch(
            "testgen.mcp.tools.common.resolve_table_group",
            side_effect=MCPResourceNotAccessible("Table group", bad_id),
        ),
        pytest.raises(MCPResourceNotAccessible),
    ):
        resolve_monitored_table_group(bad_id)
