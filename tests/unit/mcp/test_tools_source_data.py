from unittest.mock import patch
from uuid import uuid4

import pandas as pd
import pytest

from testgen.common.source_data_service import SourceDataResult
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions


def _make_context(**overrides):
    base = {
        "test_type": "Alpha_Trunc",
        "schema_name": "public",
        "table_name": "orders",
        "column_names": "customer_name",
        "project_code": "demo",
    }
    base.update(overrides)
    return base


# --- get_source_data_query ---


@patch("testgen.mcp.tools.source_data.build_test_result_query")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_query_basic(mock_td, mock_build, db_session_mock):
    td_id = str(uuid4())
    context = _make_context()
    mock_td.get_source_data_context.return_value = context
    mock_build.return_value = "SELECT * FROM orders WHERE customer_name LIKE '%trunc%'"

    from testgen.mcp.tools.source_data import get_source_data_query

    result = get_source_data_query(td_id)

    assert f"# Source Data Query for Test Definition `{td_id}`" in result
    assert "Alpha_Trunc" in result
    assert "public.orders" in result
    assert "`customer_name`" in result
    assert "SELECT * FROM orders" in result
    mock_build.assert_called_once()


@patch("testgen.mcp.tools.source_data.build_test_result_query")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_query_no_query_available(mock_td, mock_build, db_session_mock):
    context = _make_context(test_type="Freshness_Trend")
    mock_td.get_source_data_context.return_value = context
    mock_build.return_value = None

    from testgen.mcp.tools.source_data import get_source_data_query

    result = get_source_data_query(str(uuid4()))

    assert "not available" in result
    assert "Freshness_Trend" in result


@patch("testgen.mcp.tools.source_data.build_test_result_query")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_query_no_column(mock_td, mock_build, db_session_mock):
    context = _make_context(column_names=None)
    mock_td.get_source_data_context.return_value = context
    mock_build.return_value = "SELECT count(*) FROM orders"

    from testgen.mcp.tools.source_data import get_source_data_query

    result = get_source_data_query(str(uuid4()))

    assert "Column" not in result


@pytest.mark.parametrize("bad_limit", [-1, 0, 9999])
def test_get_source_data_query_rejects_out_of_range_limit(bad_limit, db_session_mock):
    from testgen.mcp.tools.source_data import get_source_data_query

    with pytest.raises(MCPUserError, match="Invalid limit"):
        get_source_data_query(str(uuid4()), limit=bad_limit)


def test_get_source_data_query_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.source_data import get_source_data_query

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_source_data_query("bad-uuid")


@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_query_not_found(mock_td, db_session_mock):
    mock_td.get_source_data_context.return_value = None

    from testgen.mcp.tools.source_data import get_source_data_query

    with pytest.raises(MCPResourceNotAccessible, match="Test definition .* not found or not accessible"):
        get_source_data_query(str(uuid4()))


@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_query_invalid_date(mock_td, db_session_mock):
    mock_td.get_source_data_context.return_value = _make_context()

    from testgen.mcp.tools.source_data import get_source_data_query

    with pytest.raises(MCPUserError, match="Invalid reference_date"):
        get_source_data_query(str(uuid4()), reference_date="not-a-date")


@patch("testgen.mcp.tools.source_data.build_test_result_query")
@patch("testgen.mcp.tools.source_data.TestDefinition")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_source_data_query_passes_project_codes(mock_compute, mock_td, mock_build, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    context = _make_context()
    mock_td.get_source_data_context.return_value = context
    mock_build.return_value = "SELECT 1"

    from testgen.mcp.tools.source_data import get_source_data_query

    get_source_data_query(str(uuid4()))

    call_kwargs = mock_td.get_source_data_context.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]


# --- get_source_data ---


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_ok(mock_td, mock_fetch, db_session_mock):
    td_id = str(uuid4())
    context = _make_context()
    mock_td.get_source_data_context.return_value = context

    df = pd.DataFrame({"customer_name": ["Alice", "Bob"], "value": [10, 20]})
    mock_fetch.return_value = SourceDataResult(status="OK", message=None, query="SELECT ...", df=df)

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(td_id)

    assert f"# Source Data for Test Definition `{td_id}`" in result
    assert "**Rows returned:** 2" in result
    assert "Alice" in result
    assert "Bob" in result
    assert "SELECT ..." in result


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_ok_with_pii_masking(mock_td, mock_fetch, db_session_mock):
    context = _make_context(project_code="demo")
    mock_td.get_source_data_context.return_value = context

    df = pd.DataFrame({"col": ["redacted"]})
    mock_fetch.return_value = SourceDataResult(status="OK", message=None, query=None, df=df)

    from testgen.mcp.tools.source_data import get_source_data

    # Default conftest gives "demo" with "role_a"; view_pii may or may not be granted.
    # Just verify the function runs and passes mask_pii to fetch.
    get_source_data(str(uuid4()))

    call_args = mock_fetch.call_args
    # mask_pii is the third positional arg
    assert isinstance(call_args[0][2], bool)


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_banner_only_when_redaction_happened(mock_td, mock_fetch, db_session_mock):
    """The PII banner must key on whether masking actually changed the df, not on the mask_pii flag."""
    mock_td.get_source_data_context.return_value = _make_context()

    df = pd.DataFrame({"col": ["unredacted"]})
    mock_fetch.return_value = SourceDataResult(
        status="OK", message=None, query="SELECT 1", df=df, pii_redacted=False,
    )

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(str(uuid4()))

    assert "PII columns have been redacted" not in result


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_banner_shown_when_redaction_happened(mock_td, mock_fetch, db_session_mock):
    mock_td.get_source_data_context.return_value = _make_context()

    df = pd.DataFrame({"col": ["[PII Redacted]"]})
    mock_fetch.return_value = SourceDataResult(
        status="OK", message=None, query="SELECT 1", df=df, pii_redacted=True,
    )

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(str(uuid4()))

    assert "PII columns have been redacted" in result


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_na_status(mock_td, mock_fetch, db_session_mock):
    mock_td.get_source_data_context.return_value = _make_context()
    mock_fetch.return_value = SourceDataResult(status="NA", message="Not available for this test type.", query=None, df=None)

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(str(uuid4()))

    assert "Not available for this test type." in result


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_nd_status(mock_td, mock_fetch, db_session_mock):
    mock_td.get_source_data_context.return_value = _make_context()
    mock_fetch.return_value = SourceDataResult(
        status="ND", message="No data returned.", query="SELECT * FROM orders WHERE 1=0", df=None,
    )

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(str(uuid4()))

    assert "No data returned." in result
    assert "SELECT * FROM orders WHERE 1=0" in result


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
def test_get_source_data_err_status(mock_td, mock_fetch, db_session_mock):
    mock_td.get_source_data_context.return_value = _make_context()
    mock_fetch.return_value = SourceDataResult(
        status="ERR", message="Connection refused", query="SELECT 1", df=None,
    )

    from testgen.mcp.tools.source_data import get_source_data

    result = get_source_data(str(uuid4()))

    assert "**Error:** Connection refused" in result
    assert "SELECT 1" in result


def test_get_source_data_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.source_data import get_source_data

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_source_data("bad-uuid")


@patch("testgen.mcp.tools.source_data.fetch_test_result_source_data")
@patch("testgen.mcp.tools.source_data.TestDefinition")
@patch("testgen.mcp.permissions._compute_project_permissions")
def test_get_source_data_passes_project_codes(mock_compute, mock_td, mock_fetch, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"proj_a": "role_a"},
        permission="view",
    )
    context = _make_context(project_code="proj_a")
    mock_td.get_source_data_context.return_value = context

    df = pd.DataFrame({"x": [1]})
    mock_fetch.return_value = SourceDataResult(status="OK", message=None, query=None, df=df)

    from testgen.mcp.tools.source_data import get_source_data

    get_source_data(str(uuid4()))

    call_kwargs = mock_td.get_source_data_context.call_args.kwargs
    assert call_kwargs["project_codes"] == ["proj_a"]
