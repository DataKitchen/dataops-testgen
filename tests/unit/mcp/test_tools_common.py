from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from testgen.common.enums import ImpactDimension, QualityDimension
from testgen.common.models.hygiene_issue import Disposition, IssueLikelihood, PiiRisk
from testgen.common.models.test_result import TestResultStatus
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.common import (
    format_disposition,
    parse_disposition,
    parse_impact_dimension,
    parse_issue_likelihood_list,
    parse_pii_risk_list,
    parse_quality_dimension,
    parse_result_status,
    parse_uuid,
    resolve_issue_type,
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
