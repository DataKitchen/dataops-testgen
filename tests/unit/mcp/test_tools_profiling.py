from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.data_column import ColumnProfileDetail, ColumnProfileSummary, DataColumnChars
from testgen.common.pii_masking import PII_REDACTED
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


@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_with_valid_job_execution_id(
    mock_tg_cls, mock_dcc_cls, mock_pr_cls, db_session_mock,
):
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = tg.id
    pr.project_code = tg.project_code

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr
    mock_dcc_cls.list_for_table_group.return_value = ([_column_summary()], 1)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), job_execution_id=str(uuid4()))

    assert mock_dcc_cls.list_for_table_group.call_args.kwargs["profiling_run_id"] == pr.id


@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_rejects_je_from_different_tg(
    mock_tg_cls, mock_pr_cls, db_session_mock,
):
    """JE belonging to a different TG → 'not found or not accessible' (existence hidden)."""
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = uuid4()  # different TG
    pr.project_code = tg.project_code

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPResourceNotAccessible, match="Profiling run .* not found or not accessible"):
        list_column_profiles(str(uuid4()), job_execution_id=str(uuid4()))


@patch("testgen.mcp.tools.common.ProfilingRun")
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
        (None, "No"),
        ("", "No"),
        ("MANUAL", "Yes"),
        ("A/ID/Passport", "Yes (High Risk - ID / Passport)"),
        ("B/NAME/Individual", "Yes (Moderate Risk - Name / Individual)"),
        ("C/CONTACT", "Yes (Low Risk - Contact)"),
        ("B/ID/ID", "Yes (Moderate Risk - ID)"),  # detail collapses when equal to type label
        ("X/UNKNOWN/Detail", "Yes (Moderate Risk / Detail)"),  # unknown risk falls back; unknown type drops label
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
    assert row[5] == "Yes (Moderate Risk - Name / Individual)"


def test_render_row_falsy_pii_renders_no():
    from testgen.mcp.tools.profiling import _render_column_profile_row
    assert _render_column_profile_row(_column_summary(pii_flag=None))[5] == "No"


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


# ----------------------------------------------------------------------
# list_profiling_runs
# ----------------------------------------------------------------------

from datetime import UTC

from testgen.common.enums import JobStatus

_RUN_CREATED = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
_RUN_STARTED = datetime(2026, 4, 1, 10, 0, 5, tzinfo=UTC)
_RUN_COMPLETED = datetime(2026, 4, 1, 10, 1, 30, tzinfo=UTC)


def _mock_profiling_run(**overrides):
    defaults = {
        "job_execution_id": uuid4(),
        "profiling_run_id": uuid4(),
        "project_code": "demo",
        "status": JobStatus.COMPLETED,
        "status_label": "Completed",
        "created_at": _RUN_CREATED,
        "started_at": _RUN_STARTED,
        "completed_at": _RUN_COMPLETED,
        "error_message": None,
        "table_groups_name": "demo-tg",
        "table_group_schema": "demo",
        "table_ct": 5, "column_ct": 30, "record_ct": 1000,
        "anomaly_ct": 4,
        "anomalies_definite_ct": 1, "anomalies_likely_ct": 1,
        "anomalies_possible_ct": 2, "anomalies_dismissed_ct": 0,
        "dq_score_profiling": 95.5,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@patch("testgen.mcp.tools.profiling.JobExecution")
@patch("testgen.mcp.tools.profiling.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_runs_default(mock_tg_cls, mock_run_cls, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    tg = _mock_table_group()
    tg.table_groups_name = "demo-tg"
    mock_tg_cls.get.return_value = tg
    mock_run_cls.select_summary.return_value = ([_mock_profiling_run()], 1)

    from testgen.mcp.tools.profiling import list_profiling_runs
    result = list_profiling_runs(table_group_id=str(uuid4()))

    assert "Profiling runs for `demo-tg`" in result
    assert "Completed" in result
    call_kwargs = mock_run_cls.select_summary.call_args.kwargs
    assert call_kwargs["statuses"] is None


@patch("testgen.mcp.tools.profiling.JobExecution")
@patch("testgen.mcp.tools.profiling.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_runs_status_filter(mock_tg_cls, mock_run_cls, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_run_cls.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_profiling_runs
    list_profiling_runs(table_group_id=str(uuid4()), status="Pending")

    call_kwargs = mock_run_cls.select_summary.call_args.kwargs
    assert call_kwargs["statuses"] == [JobStatus.PENDING, JobStatus.CLAIMED]


@patch("testgen.mcp.tools.profiling.JobExecution")
@patch("testgen.mcp.tools.profiling.next_scheduled_run", return_value=_RUN_STARTED)
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_runs_shows_next_scheduled(mock_tg_cls, mock_run_cls, mock_next, mock_je, db_session_mock):
    mock_je.select_active_by_kwargs.return_value = []
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_run_cls.select_summary.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_profiling_runs
    result = list_profiling_runs(table_group_id=str(uuid4()))

    assert "Next scheduled run" in result


@patch("testgen.mcp.tools.profiling.next_scheduled_run", return_value=None)
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_profiling_runs_invalid_status(mock_tg_cls, mock_run_cls, mock_next, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()

    from testgen.mcp.tools.profiling import list_profiling_runs
    with pytest.raises(MCPUserError, match="Invalid status"):
        list_profiling_runs(table_group_id=str(uuid4()), status="Bogus")


# ----------------------------------------------------------------------
# get_profiling_run
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.ProfilingRun")
def test_get_profiling_run_returns_detail(mock_run_cls, db_session_mock):
    summary = _mock_profiling_run()
    mock_run_cls.select_summary.return_value = ([summary], 1)
    mock_run = MagicMock(project_code="demo")
    mock_run_cls.get_by_id_or_job.return_value = mock_run
    mock_run_cls.select_table_breakdown.return_value = [
        MagicMock(schema_name="demo", table_name="orders", record_ct=1000, column_ct=5, anomaly_ct=2),
    ]

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"}, permission="catalog", username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]

            from testgen.mcp.tools.profiling import get_profiling_run
            result = get_profiling_run(str(summary.job_execution_id))

    assert "Profiling run: demo-tg" in result
    assert "Completed" in result
    assert "Per-table breakdown" in result
    assert "orders" in result


@patch("testgen.mcp.tools.profiling.ProfilingRun")
def test_get_profiling_run_pending_no_breakdown(mock_run_cls, db_session_mock):
    summary = _mock_profiling_run(
        status=JobStatus.PENDING, status_label="Pending",
        profiling_run_id=None, started_at=None, completed_at=None,
        table_ct=None, column_ct=None, record_ct=None, anomaly_ct=None,
        anomalies_definite_ct=None, anomalies_likely_ct=None,
        anomalies_possible_ct=None, dq_score_profiling=None,
    )
    mock_run_cls.select_summary.return_value = ([summary], 1)
    mock_run_cls.get_by_id_or_job.return_value = MagicMock(project_code="demo")

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"}, permission="catalog", username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]

            from testgen.mcp.tools.profiling import get_profiling_run
            result = get_profiling_run(str(summary.job_execution_id))

    assert "Pending" in result
    assert "In progress" in result
    assert "Per-table breakdown" not in result


@patch("testgen.mcp.tools.profiling.ProfilingRun")
def test_get_profiling_run_not_found(mock_run_cls, db_session_mock):
    mock_run_cls.select_summary.return_value = ([], 0)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"}, permission="catalog", username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]

            from testgen.mcp.tools.profiling import get_profiling_run
            with pytest.raises(MCPResourceNotAccessible):
                get_profiling_run(str(uuid4()))


@patch("testgen.mcp.tools.profiling.ProfilingRun")
def test_get_profiling_run_inaccessible_project(mock_run_cls, db_session_mock):
    summary = _mock_profiling_run(project_code="secret")
    mock_run_cls.select_summary.return_value = ([summary], 1)

    with patch("testgen.mcp.permissions._compute_project_permissions") as mock_compute:
        mock_compute.return_value = ProjectPermissions(
            memberships={"demo": "role_a"}, permission="catalog", username="test_user",
        )
        with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
            mock_hook.instance().rbac.get_roles_with_permission.return_value = ["role_a"]

            from testgen.mcp.tools.profiling import get_profiling_run
            with pytest.raises(MCPResourceNotAccessible):
                get_profiling_run(str(summary.job_execution_id))


def test_get_profiling_run_invalid_uuid(db_session_mock):
    from testgen.mcp.tools.profiling import get_profiling_run
    with pytest.raises(MCPUserError, match="not a valid UUID"):
        get_profiling_run("not-a-uuid")


# ----------------------------------------------------------------------
# get_column_profile_detail
# ----------------------------------------------------------------------


def _column_detail(**overrides) -> ColumnProfileDetail:
    """Build a ColumnProfileDetail with sensible alpha-column defaults; override per test."""
    base: dict = {
        # Identity
        "column_name": "customer_name",
        "table_name": "customers",
        "schema_name": "demo",
        # Types & metadata
        "general_type": "A",
        "column_type": "varchar(50)",
        "db_data_type": "varchar(50)",
        "functional_data_type": "Person Given Name",
        "datatype_suggestion": "VARCHAR(20)",
        "functional_table_type": None,
        "pii_flag": None,
        "critical_data_element": False,
        # Counts
        "record_ct": 500,
        "value_ct": 500,
        "distinct_value_ct": 260,
        "null_value_ct": 0,
        "filled_value_ct": 0,
        "zero_value_ct": 0,
        # Alpha
        "min_length": 3,
        "max_length": 50,
        "avg_length": 12.4,
        "min_text": "Aaron",
        "max_text": "Zoey",
        "top_freq_values": "| Mary | 12\n| John | 10",
        "top_patterns": "10 | A(5) | 8 | A(6)",
        "distinct_std_value_ct": 250,
        "distinct_pattern_ct": 35,
        "std_pattern_match": None,
        "mixed_case_ct": 100,
        "lower_case_ct": 350,
        "upper_case_ct": 50,
        "non_alpha_ct": 0,
        "includes_digit_ct": 0,
        "numeric_ct": 0,
        "date_ct": 0,
        "quoted_value_ct": 0,
        "lead_space_ct": 0,
        "embedded_space_ct": 0,
        "avg_embedded_spaces": 0.0,
        "zero_length_ct": 0,
        # Numeric
        "min_value": None,
        "min_value_over_0": None,
        "max_value": None,
        "avg_value": None,
        "stdev_value": None,
        "percentile_25": None,
        "percentile_50": None,
        "percentile_75": None,
        # Date
        "min_date": None,
        "max_date": None,
        "before_1yr_date_ct": None,
        "before_5yr_date_ct": None,
        "before_20yr_date_ct": None,
        "within_1yr_date_ct": None,
        "within_1mo_date_ct": None,
        "future_date_ct": None,
        # Boolean
        "boolean_true_ct": None,
        # Per-column profiling failure
        "query_error": None,
        # Scores & hygiene
        "dq_score_profiling": 95.2,
        "dq_score_testing": 90.0,
        "hygiene_issue_count": 2,
        # Run identity
        "profile_run_id": uuid4(),
        "profile_run_je_id": uuid4(),
        "profile_run_status": "Complete",
        "profile_run_started_at": datetime(2026, 5, 1, 12, 0, 0),
        "profile_run_ended_at": datetime(2026, 5, 1, 12, 5, 0),
        "profile_run_log_message": None,
    }
    base.update(overrides)
    return ColumnProfileDetail(**base)


# --- happy paths per general_type ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_alpha_renders_alpha_sections(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(general_type="A")

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    assert "Column Profile" in result
    assert "customer_name" in result
    assert "Profiling Run" in result
    # Alpha-specific sections present
    assert "Length" in result
    assert "Text Range" in result
    assert "Patterns" in result
    assert "Aaron" in result
    assert "Zoey" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_alpha_renders_distinct_standard_values(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    """`distinct_std_value_ct` (alpha-only) renders under the Patterns section as 'Distinct Standard Values'."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        general_type="A",
        distinct_std_value_ct=247,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    assert "Distinct Standard Values" in result
    assert "247" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_numeric_renders_numeric_sections(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        column_name="amount",
        general_type="N",
        db_data_type="numeric",
        functional_data_type="Currency",
        # Numeric stats
        min_value=0.0,
        min_value_over_0=0.01,
        max_value=99999.99,
        avg_value=125.34,
        stdev_value=42.1,
        percentile_25=50.0,
        percentile_50=100.0,
        percentile_75=200.0,
        # Alpha fields cleared (numeric column wouldn't have these populated)
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
        min_length=None,
        max_length=None,
        avg_length=None,
        std_pattern_match=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "orders", "amount")

    # Numeric-specific content present
    assert "Median" in result or "Percentile" in result or "percentile_50" in result.lower()
    assert "99999.99" in result or "99,999.99" in result
    # Alpha-only sections absent
    assert "Text Range" not in result
    assert "Min Text" not in result
    assert "Aaron" not in result
    assert "Length" not in result.replace("Avg Length", "")  # rough — ensures no Length section


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_date_renders_date_sections(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        column_name="created_at",
        general_type="D",
        db_data_type="timestamp",
        functional_data_type="Datetime-Created",
        min_date=datetime(2024, 1, 1, 0, 0, 0),
        max_date=datetime(2026, 4, 30, 23, 59, 59),
        before_1yr_date_ct=10000,
        before_5yr_date_ct=2000,
        before_20yr_date_ct=0,
        within_1yr_date_ct=40000,
        within_1mo_date_ct=5000,
        future_date_ct=0,
        # Alpha fields cleared
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
        min_length=None,
        max_length=None,
        avg_length=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "orders", "created_at")

    # Date-specific content
    assert "Within 1" in result or "Before 1" in result or "Date Range" in result
    assert "2024" in result
    # Alpha-only sections absent
    assert "Aaron" not in result
    assert "Pattern" not in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_boolean_renders_boolean_section(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        column_name="is_active",
        general_type="B",
        db_data_type="boolean",
        functional_data_type="Boolean",
        boolean_true_ct=420,
        value_ct=500,
        # Alpha fields cleared
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
        min_length=None,
        max_length=None,
        avg_length=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "users", "is_active")

    assert "True" in result
    assert "420" in result
    # Alpha-only sections absent
    assert "Pattern" not in result
    assert "Length" not in result.replace("Avg Length", "")


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_unknown_general_type_renders_counts_only(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        column_name="payload",
        general_type="X",
        db_data_type="json",
        functional_data_type=None,
        # All type-specific fields cleared
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
        min_length=None,
        max_length=None,
        avg_length=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "events", "payload")

    assert "payload" in result
    assert "Counts" in result
    assert "Pattern" not in result
    assert "Boolean Distribution" not in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_general_type_t_treated_as_unknown(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    """T mirrors current UI behavior — falls through to common counts only."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        column_name="ts",
        general_type="T",
        db_data_type="time",
        functional_data_type=None,
        min_text=None,
        max_text=None,
        top_freq_values=None,
        top_patterns=None,
        min_length=None,
        max_length=None,
        avg_length=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "events", "ts")

    assert "Counts" in result
    assert "Date Range" not in result  # not dispatched as date


# --- never-profiled / no-profile-for-pinned-run ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_never_profiled_column_rejects(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    """Column row exists in data_column_chars but has no completed profiling run yet
    (`last_complete_profile_run_id IS NULL`). The model returns a detail with NULL run
    fields; the tool must reject rather than render an empty profile.
    """
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        profile_run_id=None,
        profile_run_je_id=None,
        profile_run_status=None,
        profile_run_started_at=None,
        profile_run_ended_at=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError) as exc_info:
        get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    msg = str(exc_info.value)
    assert "customer_name" in msg
    assert "not been profiled" in msg


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pinned_run_without_column_rejects(
    mock_tg_cls, mock_pr_cls, mock_dcc_cls, db_session_mock,
):
    """User pins a valid run via job_execution_id, but that run has no profile_results
    row for this column. Surface the pinned run id so the LLM knows what to try next.
    """
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = tg.id
    pr.project_code = tg.project_code

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        profile_run_id=None,
        profile_run_je_id=None,
        profile_run_status=None,
        profile_run_started_at=None,
        profile_run_ended_at=None,
    )

    je_id_str = str(uuid4())
    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError) as exc_info:
        get_column_profile_detail(
            str(uuid4()), "customers", "customer_name", job_execution_id=je_id_str
        )

    msg = str(exc_info.value)
    assert "customer_name" in msg
    assert je_id_str in msg


# --- error paths ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_column_not_found_unified_error(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = None

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPResourceNotAccessible, match=r"Column .* not found or not accessible"):
        get_column_profile_detail(str(uuid4()), "customers", "ghost_column")


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_inaccessible_tg(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = None

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPResourceNotAccessible, match=r"Table group .* not found or not accessible"):
        get_column_profile_detail(str(uuid4()), "customers", "x")


def test_get_column_profile_detail_invalid_tg_uuid(db_session_mock):
    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError, match="Invalid table_group_id"):
        get_column_profile_detail("not-a-uuid", "customers", "x")


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_invalid_je_uuid(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError, match="Invalid job_execution_id"):
        get_column_profile_detail(
            str(uuid4()), "customers", "x", job_execution_id="bad"
        )


# --- job_execution_id pinning ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pinned_run_passes_id_to_model(
    mock_tg_cls, mock_pr_cls, mock_dcc_cls, db_session_mock,
):
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = tg.id
    pr.project_code = tg.project_code

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr
    mock_dcc_cls.get_column_detail.return_value = _column_detail()

    from testgen.mcp.tools.profiling import get_column_profile_detail
    get_column_profile_detail(str(uuid4()), "customers", "customer_name", job_execution_id=str(uuid4()))

    assert mock_dcc_cls.get_column_detail.call_args.kwargs["profiling_run_id"] == pr.id


@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pinned_run_from_different_tg_unified_error(
    mock_tg_cls, mock_pr_cls, db_session_mock,
):
    tg = _mock_table_group()
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = uuid4()  # different
    pr.project_code = tg.project_code

    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_by_id_or_job.return_value = pr

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPResourceNotAccessible, match=r"Profiling run .* not found or not accessible"):
        get_column_profile_detail(
            str(uuid4()), "customers", "x", job_execution_id=str(uuid4())
        )


@patch("testgen.mcp.tools.common.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pinned_run_unknown_unified_error(
    mock_tg_cls, mock_pr_cls, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_pr_cls.get_by_id_or_job.return_value = None

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPResourceNotAccessible, match=r"Profiling run .* not found or not accessible"):
        get_column_profile_detail(
            str(uuid4()), "customers", "x", job_execution_id=str(uuid4())
        )


# --- run-status preconditions ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_running_run_rejects_with_status(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    mock_tg_cls.get.return_value = _mock_table_group()
    je_id = uuid4()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        profile_run_status="Running",
        profile_run_je_id=je_id,
        profile_run_ended_at=None,
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError) as exc_info:
        get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    msg = str(exc_info.value)
    assert "Running" in msg
    assert str(je_id) in msg


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_error_run_includes_log_message(
    mock_tg_cls, mock_dcc_cls, db_session_mock
):
    mock_tg_cls.get.return_value = _mock_table_group()
    je_id = uuid4()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        profile_run_status="Error",
        profile_run_je_id=je_id,
        profile_run_log_message="connection timed out",
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    with pytest.raises(MCPUserError) as exc_info:
        get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    msg = str(exc_info.value)
    assert "Error" in msg
    assert str(je_id) in msg
    assert "connection timed out" in msg


# --- PII redaction ---


@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pii_column_no_view_pii_redacts(
    mock_tg_cls, mock_dcc_cls, mock_compute, db_session_mock,
):
    """User has 'catalog' on demo but NOT 'view_pii' → 8 raw-value fields redacted; aggregates kept."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        pii_flag="B/CONTACT/Email",
        column_name="customer_email",
        general_type="A",
        std_pattern_match="EMAIL",
        min_text="aaron@example.com",
        max_text="zoey@example.com",
        top_freq_values="| mary@x.com | 1\n| john@x.com | 1",
    )
    # No project includes view_pii — only catalog allowed
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_c"},  # role_c has 'catalog' but not 'view_pii' in test matrix
        permission="catalog",
        username="test_user",
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "customers", "customer_email")

    # Raw-value fields redacted
    assert PII_REDACTED in result
    assert "aaron@example.com" not in result
    assert "zoey@example.com" not in result
    assert "mary@x.com" not in result
    # Aggregates / counts / std_pattern_match still visible
    assert "260" in result or "Distinct" in result
    assert "EMAIL" in result or "Email" in result


@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_pii_column_with_view_pii_shows_values(
    mock_tg_cls, mock_dcc_cls, mock_compute, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        pii_flag="B/CONTACT/Email",
        column_name="customer_email",
        min_text="aaron@example.com",
        max_text="zoey@example.com",
    )
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_a"},  # role_a has 'view_pii' in conftest matrix? actually no — but we need a role that includes view_pii. Use role-with-view_pii via "edit" mapping.
        permission="catalog",
        username="test_user",
    )
    # Patch the rbac mapping so role_a includes view_pii for this test
    with patch("testgen.mcp.permissions.PluginHook") as mock_hook:
        mock_hook.instance.return_value.rbac.get_roles_with_permission.side_effect = (
            lambda perm: ["role_a"] if perm in ("catalog", "view_pii") else []
        )
        from testgen.mcp.tools.profiling import get_column_profile_detail
        result = get_column_profile_detail(str(uuid4()), "customers", "customer_email")

    assert "aaron@example.com" in result
    assert PII_REDACTED not in result


@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_non_pii_column_never_redacts(
    mock_tg_cls, mock_dcc_cls, mock_compute, db_session_mock,
):
    """No pii_flag → raw values shown regardless of view_pii grant."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        pii_flag=None,
        min_text="Aaron",
        max_text="Zoey",
    )
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_c"},
        permission="catalog",
        username="test_user",
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    assert "Aaron" in result
    assert "Zoey" in result
    assert PII_REDACTED not in result


# --- query_error surfacing ---


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_profile_detail_query_error_section(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.get_column_detail.return_value = _column_detail(
        query_error="ORA-01017: invalid username/password",
    )

    from testgen.mcp.tools.profiling import get_column_profile_detail
    result = get_column_profile_detail(str(uuid4()), "customers", "customer_name")

    assert "Profiling Error" in result
    assert "ORA-01017" in result


# ----------------------------------------------------------------------
# list_column_profiles — predicate filters
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_null_ratio_above_adds_clause(mock_tg_cls, mock_dcc_cls, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_dcc_cls.list_for_table_group.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), null_ratio_above=0.2)

    clauses = mock_dcc_cls.list_for_table_group.call_args[0]
    assert any("null_value_ct" in str(c) for c in clauses)


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_score_profiling_above_converts_to_0_to_1_scale(
    mock_tg_cls, mock_method, db_session_mock,
):
    """The user-facing 0-100 score range maps to the 0-1 fraction the DB stores."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), score_profiling_above=70)

    sql = _compile_clauses(mock_method)
    assert "dq_score_profiling > 0.7" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_score_testing_below_converts_to_0_to_1_scale(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), score_testing_below=50)

    sql = _compile_clauses(mock_method)
    assert "dq_score_testing < 0.5" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_pii_true_adds_is_not_null_clause(mock_tg_cls, mock_method, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), pii=True)

    sql = _compile_clauses(mock_method)
    assert "pii_flag IS NOT NULL" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_cde_true_coalesces_column_and_table_flag(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), cde=True)

    sql = _compile_clauses(mock_method)
    assert "data_column_chars.critical_data_element IS true" in sql
    assert "data_table_chars.critical_data_element IS true" in sql
    assert "OR" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_suggested_data_type_any_uses_is_not_null(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), suggested_data_type="Any")

    sql = _compile_clauses(mock_method)
    assert "datatype_suggestion IS NOT NULL" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_suggested_data_type_concrete_uses_prefix_ilike(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), suggested_data_type="Integer")

    sql = _compile_clauses(mock_method)
    assert "INTEGER%" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_general_type_translates_word_to_letter(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), general_type="Numeric")

    sql = _compile_clauses(mock_method)
    assert "general_type = 'N'" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_pii_category_translated_to_stored_code(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), pii_category="Contact")

    sql = _compile_clauses(mock_method)
    assert "%/CONTACT/%" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_pii_risk_level_high_includes_manual(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), pii_risk_level="High")

    sql = _compile_clauses(mock_method)
    assert "'A/%'" in sql and "'MANUAL'" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_pii_risk_level_moderate_does_not_include_manual(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), pii_risk_level="Moderate")

    sql = _compile_clauses(mock_method)
    assert "'B/%'" in sql
    assert "MANUAL" not in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_semantic_data_type_uses_ilike(
    mock_tg_cls, mock_method, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), semantic_data_type="Person Given")

    sql = _compile_clauses(mock_method)
    # Default dialect renders ILIKE as ``LOWER(col) LIKE LOWER(pat) ESCAPE`` — same semantic.
    assert "LIKE" in sql.upper()
    assert "%Person Given%" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_semantic_data_type_underscore_escaped(
    mock_tg_cls, mock_method, db_session_mock,
):
    """Underscores in the input must be escaped (column names commonly contain them)."""
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), semantic_data_type="ID_FK")

    sql = _compile_clauses(mock_method)
    # The escape clause appears, and the underscore is escaped in the pattern.
    assert "ID\\_FK" in sql or "ID\\\\_FK" in sql


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_semantic_data_type_empty_rejected(mock_tg_cls, mock_method, db_session_mock):
    mock_tg_cls.get.return_value = _mock_table_group()

    from testgen.mcp.tools.profiling import list_column_profiles
    with pytest.raises(MCPUserError, match="`semantic_data_type` cannot be empty"):
        list_column_profiles(str(uuid4()), semantic_data_type="   ")


@patch.object(DataColumnChars, "list_for_table_group")
@patch("testgen.mcp.tools.common.TableGroup")
def test_list_column_profiles_order_by_passes_enum_to_model(mock_tg_cls, mock_method, db_session_mock):
    from testgen.common.models.data_column import ColumnOrderBy

    mock_tg_cls.get.return_value = _mock_table_group()
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import list_column_profiles
    list_column_profiles(str(uuid4()), order_by="Null Ratio")

    assert mock_method.call_args.kwargs["order_by"] is ColumnOrderBy.NULL_RATIO


def _compile_clauses(mock_method):
    """Compile the *clauses arg of a captured ``list_for_table_group`` call into a single SQL string."""
    clauses = mock_method.call_args[0]
    return " ".join(str(c.compile(compile_kwargs={"literal_binds": True})) for c in clauses)


# ----------------------------------------------------------------------
# get_column_frequent_values
# ----------------------------------------------------------------------


def _mock_profile_result(**overrides):
    pr = MagicMock()
    pr.profile_run_id = uuid4()
    pr.record_ct = 500
    pr.distinct_value_ct = 3
    pr.pii_flag = None
    pr.general_type = "A"
    pr.top_freq_values = "| Mexico | 200\n| USA | 180\n| Canada | 120"
    pr.top_patterns = "200 | Aaaaaa | 100 | AAA"
    for k, v in overrides.items():
        setattr(pr, k, v)
    return pr


def _mock_profiling_run_for_tg(tg_id):
    pr = MagicMock()
    pr.id = uuid4()
    pr.table_groups_id = tg_id
    pr.job_execution_id = uuid4()
    return pr


def _mock_data_column(pii_flag=None):
    """Build a mock `DataColumnChars` row carrying just the fields the helper reads."""
    col = MagicMock()
    col.pii_flag = pii_flag
    return col


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_happy_path(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result()
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_frequent_values
    result = get_column_frequent_values(str(uuid4()), "customers", "country")

    assert "Frequent values: customers.country" in result
    assert "Mexico" in result and "USA" in result and "Canada" in result
    assert "40.00%" in result  # 200/500
    assert "Top values" in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_surfaces_job_execution_id_not_profile_run_id(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    profile = _mock_profile_result()
    mock_pr_cls.get_for_column.return_value = profile
    run = _mock_profiling_run_for_tg(tg.id)
    mock_run_cls.get.return_value = run
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_frequent_values
    result = get_column_frequent_values(str(uuid4()), "customers", "country")

    # The internal profile_run_id PK must not leak; only the job_execution_id is followable.
    assert str(run.job_execution_id) in result
    assert str(profile.profile_run_id) not in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_pii_value_redacted_when_caller_lacks_view_pii(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group(project_code="demo")
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        top_freq_values="| alice@example.com | 5\n| bob@example.com | 3",
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    # The pii_flag the tool reads comes from DataColumnChars, not ProfileResult.
    mock_dcc_select.return_value = [_mock_data_column(pii_flag="B/CONTACT/Email")]

    # Default test conftest grants no view_pii (TEST_PERM_MATRIX has no entry).
    from testgen.mcp.tools.profiling import get_column_frequent_values
    result = get_column_frequent_values(str(uuid4()), "customers", "email")

    assert PII_REDACTED in result
    assert "alice@example.com" not in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.permissions._compute_project_permissions")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_pii_value_visible_with_view_pii_grant(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_compute, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group(project_code="demo")
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        top_freq_values="| alice@example.com | 5\n| bob@example.com | 3",
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column(pii_flag="B/CONTACT/Email")]
    mock_compute.return_value = ProjectPermissions(
        memberships={"demo": "role_a"},
        permission="catalog",
        username="test_user",
    )
    # Add view_pii to the matrix for this test by patching the role-lookup.
    with patch("testgen.mcp.permissions.PluginHook") as hook_mock:
        hook_mock.instance.return_value.rbac.get_roles_with_permission.return_value = ["role_a"]
        from testgen.mcp.tools.profiling import get_column_frequent_values
        result = get_column_frequent_values(str(uuid4()), "customers", "email")

    assert "alice@example.com" in result
    assert PII_REDACTED not in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_high_cardinality_fallback(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        top_freq_values=None, distinct_value_ct=10000,
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_frequent_values
    result = get_column_frequent_values(str(uuid4()), "customers", "customer_id")

    assert "Frequency data not available" in result
    assert "10000" in result


@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_missing_profile_raises_not_accessible(
    mock_tg_cls, mock_pr_cls, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    mock_pr_cls.get_for_column.return_value = None

    from testgen.mcp.tools.profiling import get_column_frequent_values
    with pytest.raises(MCPResourceNotAccessible, match="Column profile"):
        get_column_frequent_values(str(uuid4()), "customers", "ghost")


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_frequent_values_pii_source_is_data_column_chars_not_profile_result(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    """``data_column_chars.pii_flag`` is the source of truth; ``profile_result.pii_flag`` is ignored."""
    tg = _mock_table_group(project_code="demo")
    mock_tg_cls.get.return_value = tg
    # ProfileResult carries a stale/wrong pii_flag; DataColumnChars says None.
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        pii_flag="A/CONTACT/Email",  # stale value; should NOT drive redaction
        top_freq_values="| alice@example.com | 5",
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column(pii_flag=None)]

    from testgen.mcp.tools.profiling import get_column_frequent_values
    result = get_column_frequent_values(str(uuid4()), "customers", "email")

    # No redaction, no PII field — because DataColumnChars says the column is not PII.
    assert PII_REDACTED not in result
    assert "alice@example.com" in result
    assert "PII" not in result.splitlines()[1:6]  # no "PII:" field in the header block


# ----------------------------------------------------------------------
# get_column_patterns
# ----------------------------------------------------------------------


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_patterns_happy_path(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        general_type="A",
        top_patterns="326 | Aaaaaa | 176 | AAA",
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_patterns
    result = get_column_patterns(str(uuid4()), "customers", "country")

    assert "Character patterns: customers.country" in result
    assert "Aaaaaa" in result and "AAA" in result
    assert "Top patterns" in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_patterns_non_string_column_fallback(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        general_type="N",
        top_patterns=None,
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_patterns
    result = get_column_patterns(str(uuid4()), "products", "price")

    assert "column is not a string type" in result


@patch.object(DataColumnChars, "select_where")
@patch("testgen.mcp.tools.profiling.ProfilingRun")
@patch("testgen.mcp.tools.profiling.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_column_patterns_high_cardinality_fallback(
    mock_tg_cls, mock_pr_cls, mock_run_cls, mock_dcc_select, db_session_mock,
):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_pr_cls.get_for_column.return_value = _mock_profile_result(
        general_type="A",
        top_patterns=None,
        distinct_value_ct=9999,
    )
    mock_run_cls.get.return_value = _mock_profiling_run_for_tg(tg.id)
    mock_dcc_select.return_value = [_mock_data_column()]

    from testgen.mcp.tools.profiling import get_column_patterns
    result = get_column_patterns(str(uuid4()), "customers", "address")

    assert "Pattern data not available" in result
    assert "9999" in result


# ----------------------------------------------------------------------
# search_columns
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profiling.DataColumnChars")
def test_search_columns_no_scope_uses_all_accessible_projects(mock_dcc_cls, db_session_mock):
    mock_dcc_cls.search_by_name.return_value = ([], 0)
    mock_dcc_cls.summarize_matches_by_project.return_value = []

    from testgen.mcp.tools.profiling import search_columns
    result = search_columns("email")

    assert "all accessible projects" in result or "No columns matching" in result


@patch.object(DataColumnChars, "search_by_name")
@patch("testgen.mcp.tools.common.TableGroup")
def test_search_columns_table_group_scope_passes_tg_id_clause(mock_tg_cls, mock_method, db_session_mock):
    tg = _mock_table_group()
    mock_tg_cls.get.return_value = tg
    mock_method.return_value = ([], 0)

    from testgen.mcp.tools.profiling import search_columns
    search_columns("email", table_group_id=str(uuid4()))

    sql = " ".join(
        str(c.compile(compile_kwargs={"literal_binds": True})) for c in mock_method.call_args[0]
    )
    assert "table_groups_id" in sql


def test_search_columns_rejects_both_scopes_passed(db_session_mock):
    from testgen.mcp.tools.profiling import search_columns
    with pytest.raises(MCPUserError, match="not both"):
        search_columns("email", project_code="demo", table_group_id=str(uuid4()))


def test_search_columns_empty_pattern_rejected(db_session_mock):
    from testgen.mcp.tools.profiling import search_columns
    with pytest.raises(MCPUserError, match="`pattern` is required"):
        search_columns("   ")


@patch("testgen.mcp.tools.profiling.DataColumnChars")
def test_search_columns_renders_per_project_summary_when_no_scope(mock_dcc_cls, db_session_mock):
    hit = MagicMock()
    hit.project_code = "DEFAULT"
    hit.table_groups_name = "default"
    hit.schema_name = "demo"
    hit.table_name = "d_ebike_suppliers"
    hit.column_name = "contact_email"
    mock_dcc_cls.search_by_name.return_value = ([hit], 1)
    mock_dcc_cls.summarize_matches_by_project.return_value = [("DEFAULT", 1), ("DEMO_2", 0)]

    from testgen.mcp.tools.profiling import search_columns
    result = search_columns("email")

    assert "Matches by project" in result
    assert "DEFAULT" in result


@patch("testgen.mcp.tools.profiling.DataColumnChars")
@patch("testgen.mcp.tools.common.TableGroup")
def test_search_columns_table_group_scope_skips_per_project_summary(
    mock_tg_cls, mock_dcc_cls, db_session_mock,
):
    mock_tg_cls.get.return_value = _mock_table_group()
    hit = MagicMock()
    hit.project_code = "demo"
    hit.table_groups_name = "default"
    hit.schema_name = "demo"
    hit.table_name = "customers"
    hit.column_name = "email"
    mock_dcc_cls.search_by_name.return_value = ([hit], 1)

    from testgen.mcp.tools.profiling import search_columns
    result = search_columns("email", table_group_id=str(uuid4()))

    assert "Matches by project" not in result
    mock_dcc_cls.summarize_matches_by_project.assert_not_called()
