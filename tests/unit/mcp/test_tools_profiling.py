from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.data_column import ColumnProfileSummary
from testgen.mcp.exceptions import MCPResourceNotAccessible, MCPUserError
from testgen.mcp.permissions import ProjectPermissions

# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------


def _mock_table_group(tg_id=None, project_code="demo"):
    tg = MagicMock()
    tg.id = tg_id or uuid4()
    tg.project_code = project_code
    return tg


def _mock_overview(**overrides):
    overview = MagicMock()
    overview.id = uuid4()
    overview.table_groups_id = uuid4()
    overview.schema_name = "demo"
    overview.table_name = "orders"
    overview.record_ct = 1000
    overview.column_ct = 5
    overview.cde_count = 2
    overview.dq_score_profiling = 95.0
    overview.dq_score_testing = 90.0
    overview.hygiene_issue_count = 3
    overview.latest_profile_id = uuid4()
    overview.latest_profile_started_at = "2026-04-23 12:00:00"
    overview.latest_profile_job_execution_id = uuid4()
    overview.columns = [
        MagicMock(
            column_name="id", general_type="N", functional_data_type="ID-Unique",
            db_data_type="integer", has_nulls=False,
        ),
        MagicMock(
            column_name="customer_name", general_type="A", functional_data_type="Person Given Name",
            db_data_type="varchar(50)", has_nulls=True,
        ),
    ]
    for k, v in overrides.items():
        setattr(overview, k, v)
    return overview


def _column_summary(**overrides) -> ColumnProfileSummary:
    defaults = {
        "column_name": "customer_name",
        "table_name": "customers",
        "general_type": "A",
        "functional_data_type": "Person Given Name",
        "datatype_suggestion": "VARCHAR(20)",
        "pii_flag": "B/NAME/Individual",
        "critical_data_element": False,
        "record_ct": 500,
        "null_value_ct": 0,
        "distinct_value_ct": 260,
        "filled_value_ct": 0,
        "dq_score_profiling": 100.0,
        "dq_score_testing": 98.5,
        "hygiene_issue_count": 1,
    }
    defaults.update(overrides)
    return ColumnProfileSummary(**defaults)


def _mock_summary(**overrides):
    s = MagicMock()
    s.id = uuid4()
    s.table_groups_name = "demo-tg"
    s.connection_name = "main"
    s.table_ct = 5
    s.column_ct = 69
    s.record_ct = 1903
    s.dq_score_profiling = 98.6
    s.dq_score_testing = 81.4
    s.latest_profile_id = uuid4()
    s.latest_profile_job_execution_id = uuid4()
    s.latest_profile_start = "2026-04-23 23:24"
    s.latest_hygiene_issues_definite_ct = 2
    s.latest_hygiene_issues_likely_ct = 2
    s.latest_hygiene_issues_possible_ct = 11
    s.monitor_lookback_end = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


# ----------------------------------------------------------------------
# get_table
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_happy_path(mock_tg_cls, mock_dt_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dt_cls.get_profiling_overview.return_value = _mock_overview()

    from testgen.mcp.tools.profiling import get_table
    result = get_table(str(uuid4()), "orders")

    assert "Table: demo.orders" in result
    assert "Record count" in result
    assert "Profiling Score" in result
    assert "Profiling Run" in result
    assert "Columns" in result
    assert "customer_name" in result


@patch("testgen.mcp.tools.profiling.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_does_not_surface_internal_table_id(mock_tg_cls, mock_dt_cls, db_session_mock):
    """`Table ID` (data_table_chars.id) is an internal PK no MCP tool consumes — must not appear."""
    overview = _mock_overview()
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dt_cls.get_profiling_overview.return_value = overview

    from testgen.mcp.tools.profiling import get_table
    result = get_table(str(uuid4()), "orders")

    assert "Table ID" not in result
    assert str(overview.id) not in result


@patch("testgen.mcp.tools.profiling.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_schema_less_heading(mock_tg_cls, mock_dt_cls, db_session_mock):
    """When schema_name is None the heading falls back to bare table name."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dt_cls.get_profiling_overview.return_value = _mock_overview(schema_name=None, table_name="orders")

    from testgen.mcp.tools.profiling import get_table
    result = get_table(str(uuid4()), "orders")

    assert "Table: orders" in result
    assert "Table: ." not in result


@patch("testgen.mcp.tools.profiling.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_no_columns(mock_tg_cls, mock_dt_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dt_cls.get_profiling_overview.return_value = _mock_overview(columns=[])

    from testgen.mcp.tools.profiling import get_table
    result = get_table(str(uuid4()), "orders")

    assert "_No columns recorded for this table._" in result


@patch("testgen.mcp.tools.profiling.DataTable")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_table_not_found(mock_tg_cls, mock_dt_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dt_cls.get_profiling_overview.return_value = None

    from testgen.mcp.tools.profiling import get_table
    with pytest.raises(MCPUserError, match="not found in this table group"):
        get_table(str(uuid4()), "ghost_table")


def test_get_table_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.profiling import get_table

    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_table("not-a-uuid", "orders")


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_table_inaccessible_tg(mock_tg_cls, db_session_mock):
    """Inaccessible TG and unknown TG collapse to the same message."""
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.profiling import get_table
    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        get_table(str(uuid4()), "orders")


# ----------------------------------------------------------------------
# list_column_profiles
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_happy_path(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.list_for_table_group.return_value = ([_column_summary()], 1)

    from testgen.mcp.tools.profiling import list_column_profiles
    result = list_column_profiles(str(uuid4()))

    assert "Column profiles for table group" in result
    assert "customer_name" in result
    assert "Profiling Score" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_scoped_to_table(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.list_for_table_group.return_value = ([_column_summary()], 1)

    from testgen.mcp.tools.profiling import list_column_profiles
    result = list_column_profiles(str(uuid4()), table_name="customers")

    assert "Column profiles for table `customers`" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_empty_first_page(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.list_for_table_group.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    result = list_column_profiles(str(uuid4()))

    assert "No column profiles found" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_empty_overshoot_page(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.list_for_table_group.return_value = ([], 69)

    from testgen.mcp.tools.profiling import list_column_profiles
    result = list_column_profiles(str(uuid4()), page=99)

    assert "No column profiles on page 99 (total: 69)." == result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_paginates(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    rows = [_column_summary(column_name=f"col_{i}") for i in range(2)]
    mock_dcc_cls.list_for_table_group.return_value = (rows, 100)

    from testgen.mcp.tools.profiling import list_column_profiles
    result = list_column_profiles(str(uuid4()), limit=2, page=1)

    assert "Showing 1" in result and "2 of 100" in result
    assert "Use `page=2` for more" in result


@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_with_valid_job_execution_id(
    mock_tg_cls, mock_dcc_cls, mock_pr_cls, db_session_mock,
):
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = tg.id

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr
    mock_dcc_cls.list_for_table_group.return_value = ([_column_summary()], 1)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), job_execution_id=str(uuid4()))

    assert mock_dcc_cls.list_for_table_group.call_args.kwargs["profiling_run_id"] == pr.id


@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_rejects_je_from_different_tg(
    mock_tg_cls, mock_pr_cls, db_session_mock,
):
    """JE belonging to a different TG → 'not found or not accessible' (existence hidden)."""
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = uuid4()  # different TG

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPResourceNotAccessible, match="Profiling run .* not found or not accessible"):
        list_column_profiles(str(uuid4()), job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_rejects_unknown_je(mock_tg_cls, mock_pr_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_pr_cls.get_by_id_or_job.return_value = None

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPResourceNotAccessible, match="Profiling run .* not found or not accessible"):
        list_column_profiles(str(uuid4()), job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_invalid_je_uuid(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPUserError, match="Invalid job_execution_id"):
        list_column_profiles(str(uuid4()), job_execution_id="bad-uuid")


def test_list_column_profiles_invalid_tg_uuid(db_session_mock):
    from testgen.mcp.tools.profiling import list_column_profiles

    with pytest.raises(MCPUserError, match="Invalid table_group_id"):
        list_column_profiles("bad-uuid")


@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_inaccessible_tg(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        list_column_profiles(str(uuid4()))


# ----------------------------------------------------------------------
# _format_pii — parser mirroring PiiDisplay in metadata_tags.js
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("MANUAL", "PII"),
        ("A/ID/Passport", "PII (High Risk - ID / Passport)"),
        ("B/NAME/Individual", "PII (Moderate Risk - Name / Individual)"),
        ("C/CONTACT", "PII (Low Risk - Contact)"),
        ("B/ID/ID", "PII (Moderate Risk - ID)"),  # detail collapses when equal to type label
        ("X/UNKNOWN/Detail", "PII (Moderate Risk / Detail)"),  # unknown risk falls back; unknown type drops label
    ],
)
def test_format_pii(value, expected):
    from testgen.mcp.tools.profiling import _format_pii
    assert _format_pii(value) == expected


# ----------------------------------------------------------------------
# _render_column_profile_row — direct rendering tests
# ----------------------------------------------------------------------


def test_render_row_renders_parsed_pii_label():
    from testgen.mcp.tools.profiling import _render_column_profile_row
    row = _render_column_profile_row(_column_summary(pii_flag="B/NAME/Individual"))
    assert row[5] == "PII (Moderate Risk - Name / Individual)"


def test_render_row_falsy_pii_renders_none():
    from testgen.mcp.tools.profiling import _render_column_profile_row
    assert _render_column_profile_row(_column_summary(pii_flag=None))[5] is None


def test_render_row_cde_collapsed_to_y_or_none():
    from testgen.mcp.tools.profiling import _render_column_profile_row
    row_yes = _render_column_profile_row(_column_summary(critical_data_element=True))
    row_no = _render_column_profile_row(_column_summary(critical_data_element=False))
    assert row_yes[6] == "Y"
    assert row_no[6] is None


# ----------------------------------------------------------------------
# list_profiling_summaries
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.TableGroup")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_summaries_table_group_mode(mock_common_tg, mock_profiling_tg, db_session_mock):
    mock_common_tg.get.return_value = _mock_table_group()
    mock_profiling_tg.select_summary.return_value = ([_mock_summary()], 1)

    from testgen.mcp.tools.profiling import list_profiling_summaries
    tg_id = str(uuid4())
    result = list_profiling_summaries(table_group_id=tg_id)

    assert f"Profiling summary for table group `{tg_id}`" in result
    assert "demo-tg" in result
    assert "Tables" in result
    assert "Profiling Run" in result
    # Single-TG mode skips pagination header.
    assert "Showing" not in result


@patch("testgen.mcp.tools.profiling.TableGroup")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_summaries_never_profiled_tg(mock_common_tg, mock_profiling_tg, db_session_mock):
    mock_common_tg.get.return_value = _mock_table_group()
    mock_profiling_tg.select_summary.return_value = ([_mock_summary(latest_profile_id=None)], 1)

    from testgen.mcp.tools.profiling import list_profiling_summaries
    result = list_profiling_summaries(table_group_id=str(uuid4()))

    assert "_Not profiled yet._" in result
    # Field block omitted when never profiled.
    assert "Profiling Score" not in result
    assert "Hygiene issues" not in result


@patch("testgen.mcp.tools.profiling.TableGroup")
def test_list_profiling_summaries_project_mode(mock_tg_cls, db_session_mock):
    """With project_code we hit verify_access + paginated select_summary."""
    mock_tg_cls.select_summary.return_value = ([_mock_summary(), _mock_summary()], 2)

    from testgen.mcp.tools.profiling import list_profiling_summaries
    result = list_profiling_summaries(project_code="demo")

    assert "Profiling summary for project `demo`" in result
    assert "demo-tg" in result
    assert "Showing 1" in result and "2 of 2" in result


@patch("testgen.mcp.tools.profiling.TableGroup")
def test_list_profiling_summaries_project_mode_empty_first_page(mock_tg_cls, db_session_mock):
    mock_tg_cls.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_profiling_summaries
    result = list_profiling_summaries(project_code="demo")

    assert "No table groups in project `demo`." == result


@patch("testgen.mcp.tools.profiling.TableGroup")
def test_list_profiling_summaries_project_mode_empty_overshoot_page(mock_tg_cls, db_session_mock):
    mock_tg_cls.select_summary.return_value = ([], 5)

    from testgen.mcp.tools.profiling import list_profiling_summaries
    result = list_profiling_summaries(project_code="demo", page=99)

    assert "No table groups on page 99 (total: 5)." == result


def test_list_profiling_summaries_both_args_rejected(db_session_mock):
    from testgen.mcp.tools.profiling import list_profiling_summaries

    with pytest.raises(MCPUserError, match="Pass either"):
        list_profiling_summaries(table_group_id=str(uuid4()), project_code="demo")


def test_list_profiling_summaries_neither_arg_rejected(db_session_mock):
    from testgen.mcp.tools.profiling import list_profiling_summaries

    with pytest.raises(MCPUserError, match="Provide either"):
        list_profiling_summaries()


@patch("testgen.mcp.permissions._compute_project_permissions")
def test_list_profiling_summaries_rejects_inaccessible_project(mock_compute, db_session_mock):
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_a"}, permission="catalog",
        username="test_user",
    )

    from testgen.mcp.tools.profiling import list_profiling_summaries
    with pytest.raises(MCPResourceNotAccessible, match="Project .* not found or not accessible"):
        list_profiling_summaries(project_code="forbidden_project")


@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_summaries_inaccessible_tg(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.profiling import list_profiling_summaries
    with pytest.raises(MCPResourceNotAccessible, match="Table group .* not found or not accessible"):
        list_profiling_summaries(table_group_id=str(uuid4()))
