from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.models.data_column import ProfileMetric
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.tools.profile_history import (
    _column_metric_value,
    _delta_cell,
    _format_metric_value,
    _validate_metric_scope,
    compare_profiling_runs,
    get_profiling_trends,
    get_schema_history,
)


def _je(status=JobStatus.COMPLETED):
    """Build a JobExecution mock for ``session.get(JobExecution, ...)`` returns."""
    je = MagicMock()
    je.status = status
    return je


def _patch_session(jes):
    """Patch ``get_current_session`` so ``session.get(JobExecution, ...)`` returns the given JEs in order."""
    session = MagicMock()
    session.get.side_effect = jes
    return patch("testgen.mcp.tools.profile_history.get_current_session", return_value=session)

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _profile_row(
    run_id=None,
    table_name="orders",
    column_name="customer_email",
    general_type="A",
    schema_name="demo",
    record_ct=1000,
    null_value_ct=50,
    distinct_value_ct=900,
    filled_value_ct=10,
    column_type="varchar(200)",
    db_data_type="varchar",
    functional_data_type="Person Email",
    pii_flag=None,
    datatype_suggestion=None,
    avg_length=18.0,
    min_length=5,
    max_length=40,
    min_text=None,
    max_text=None,
    min_value=None,
    max_value=None,
    avg_value=None,
    stdev_value=None,
    min_date=None,
    max_date=None,
    boolean_true_ct=None,
):
    row = MagicMock()
    row.profile_run_id = run_id or uuid4()
    row.schema_name = schema_name
    row.table_name = table_name
    row.column_name = column_name
    row.general_type = general_type
    row.column_type = column_type
    row.db_data_type = db_data_type
    row.functional_data_type = functional_data_type
    row.pii_flag = pii_flag
    row.datatype_suggestion = datatype_suggestion
    row.record_ct = record_ct
    row.null_value_ct = null_value_ct
    row.distinct_value_ct = distinct_value_ct
    row.filled_value_ct = filled_value_ct
    row.avg_length = avg_length
    row.min_length = min_length
    row.max_length = max_length
    row.min_text = min_text
    row.max_text = max_text
    row.min_value = min_value
    row.max_value = max_value
    row.avg_value = avg_value
    row.stdev_value = stdev_value
    row.min_date = min_date
    row.max_date = max_date
    row.boolean_true_ct = boolean_true_ct
    return row


def _profiling_run(
    id_=None,
    job_execution_id=None,
    table_groups_id=None,
    status="Complete",
    profiling_starttime=None,
    dq_score_profiling=0.92,
    table_groups_name="Demo Sales",
):
    run = MagicMock()
    run.id = id_ or uuid4()
    run.job_execution_id = job_execution_id or uuid4()
    run.table_groups_id = table_groups_id or uuid4()
    run.status = status
    run.profiling_starttime = profiling_starttime or datetime(2026, 5, 10, 12, 0)
    run.dq_score_profiling = dq_score_profiling
    run.table_groups_name = table_groups_name
    return run


def _table_group(tg_id=None, project_code="demo", name="Demo Sales"):
    tg = MagicMock()
    tg.id = tg_id or uuid4()
    tg.project_code = project_code
    tg.table_groups_name = name
    return tg


# ----------------------------------------------------------------------
# _column_metric_value
# ----------------------------------------------------------------------


def test_column_metric_value_ratios():
    row = _profile_row(record_ct=1000, null_value_ct=250, distinct_value_ct=900, filled_value_ct=100)
    assert _column_metric_value(ProfileMetric.NULL_RATIO, row) == 0.25
    assert _column_metric_value(ProfileMetric.DISTINCT_RATIO, row) == 0.9
    assert _column_metric_value(ProfileMetric.FILLED_RATIO, row) == 0.1


def test_column_metric_value_record_count():
    row = _profile_row(record_ct=1234)
    assert _column_metric_value(ProfileMetric.RECORD_COUNT, row) == 1234


def test_column_metric_value_zero_record_ct_returns_none():
    row = _profile_row(record_ct=0, null_value_ct=0, distinct_value_ct=0)
    assert _column_metric_value(ProfileMetric.NULL_RATIO, row) is None
    assert _column_metric_value(ProfileMetric.DISTINCT_RATIO, row) is None


def test_column_metric_value_missing_row_returns_none():
    assert _column_metric_value(ProfileMetric.NULL_RATIO, None) is None
    assert _column_metric_value(ProfileMetric.RECORD_COUNT, None) is None


def test_column_metric_value_type_restriction():
    numeric_row = _profile_row(general_type="N", avg_value=5.5, avg_length=None)
    # Avg Length only applies to Alpha columns
    assert _column_metric_value(ProfileMetric.AVG_LENGTH, numeric_row) is None
    assert _column_metric_value(ProfileMetric.AVG, numeric_row) == 5.5

    alpha_row = _profile_row(general_type="A", avg_length=18.0, avg_value=None)
    assert _column_metric_value(ProfileMetric.AVG_LENGTH, alpha_row) == 18.0
    assert _column_metric_value(ProfileMetric.AVG, alpha_row) is None


def test_column_metric_value_date_min_max():
    row = _profile_row(
        general_type="D",
        min_date=datetime(2024, 1, 3),
        max_date=datetime(2026, 5, 10),
    )
    assert _column_metric_value(ProfileMetric.MIN_DATE, row) == datetime(2024, 1, 3)
    assert _column_metric_value(ProfileMetric.MAX_DATE, row) == datetime(2026, 5, 10)


def test_column_metric_value_boolean_true_count():
    row = _profile_row(general_type="B", boolean_true_ct=42)
    assert _column_metric_value(ProfileMetric.TRUE_COUNT, row) == 42


# ----------------------------------------------------------------------
# _format_metric_value
# ----------------------------------------------------------------------


def test_format_metric_value_percent():
    assert _format_metric_value(ProfileMetric.NULL_RATIO, 0.25) == "25.0%"
    assert _format_metric_value(ProfileMetric.DISTINCT_RATIO, 0.9) == "90.0%"


def test_format_metric_value_profiling_score_uses_friendly_score():
    # Profiling Score follows the codebase-wide friendly_score convention:
    # value (0-1) scaled to 0-100 with no '%' suffix.
    assert _format_metric_value(ProfileMetric.PROFILING_SCORE, 0.92) == "92.0"
    assert _format_metric_value(ProfileMetric.PROFILING_SCORE, 1.0) == "100"


def test_format_metric_value_record_count_thousands_separator():
    assert _format_metric_value(ProfileMetric.RECORD_COUNT, 12345) == "12,345"


def test_format_metric_value_datetime_date_only():
    assert _format_metric_value(ProfileMetric.MIN_DATE, datetime(2024, 1, 3, 14, 30)) == "2024-01-03"


def test_format_metric_value_none():
    assert _format_metric_value(ProfileMetric.NULL_RATIO, None) == "—"


# ----------------------------------------------------------------------
# _delta_cell
# ----------------------------------------------------------------------


def test_delta_cell_unchanged():
    assert _delta_cell(ProfileMetric.NULL_RATIO, 0.25, 0.25) == "25.0% (=)"


def test_delta_cell_changed():
    assert _delta_cell(ProfileMetric.NULL_RATIO, 0.30, 0.05) == "30.0% → 5.0%"


def test_delta_cell_dates_render_as_dates_only():
    # Different timestamps on the same date format identically -> rendered as (=)
    a = datetime(2024, 1, 3, 6, 0)
    b = datetime(2024, 1, 3, 18, 0)
    assert _delta_cell(ProfileMetric.MIN_DATE, a, b) == "2024-01-03 (=)"


def test_delta_cell_none_baseline():
    assert _delta_cell(ProfileMetric.RECORD_COUNT, None, 1000) == "— → 1,000"


# ----------------------------------------------------------------------
# _validate_metric_scope
# ----------------------------------------------------------------------


def test_validate_metric_scope_column_metric_requires_column():
    with pytest.raises(MCPUserError, match="require both `table_name` and `column_name`"):
        _validate_metric_scope([ProfileMetric.NULL_RATIO], table_name="orders", column_name=None)


def test_validate_metric_scope_table_metric_requires_table():
    with pytest.raises(MCPUserError, match="require `table_name`"):
        _validate_metric_scope([ProfileMetric.RECORD_COUNT], table_name=None, column_name=None)


def test_validate_metric_scope_tg_metric_accepts_any_scope():
    # No exception when no scope args provided
    _validate_metric_scope([ProfileMetric.PROFILING_SCORE], table_name=None, column_name=None)
    _validate_metric_scope([ProfileMetric.HYGIENE_COUNT], table_name=None, column_name=None)


def test_validate_metric_scope_mixed_scopes_all_satisfied():
    _validate_metric_scope(
        [ProfileMetric.NULL_RATIO, ProfileMetric.RECORD_COUNT, ProfileMetric.PROFILING_SCORE],
        table_name="orders",
        column_name="email",
    )


# ----------------------------------------------------------------------
# compare_profiling_runs — flow tests
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profile_history.HygieneIssue")
@patch("testgen.mcp.tools.profile_history.HygieneIssueType")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_auto_baseline(
    mock_resolve, mock_pr, mock_iss_type, mock_iss, db_session_mock,
):
    tg_id = uuid4()
    target_run = _profiling_run(table_groups_id=tg_id, profiling_starttime=datetime(2026, 5, 13))
    baseline_run = _profiling_run(table_groups_id=tg_id, profiling_starttime=datetime(2026, 5, 10))
    target_run.get_previous.return_value = baseline_run
    mock_resolve.return_value = target_run

    target_row = _profile_row(run_id=target_run.id, null_value_ct=50)
    baseline_row = _profile_row(run_id=baseline_run.id, null_value_ct=300)
    mock_pr.select_for_runs.return_value = [target_row, baseline_row]
    mock_iss.select_where.return_value = []
    mock_iss_type.select_where.return_value = []

    with _patch_session([_je(), _je()]):
        result = compare_profiling_runs(str(target_run.job_execution_id))

    assert "Profiling Run Comparison" in result
    assert "Target" in result and "Baseline" in result
    assert "Profiling Run" in result and "Started" in result
    target_run.get_previous.assert_called_once()


@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_rejects_non_completed_target(mock_resolve, db_session_mock):
    target_run = _profiling_run()
    mock_resolve.return_value = target_run

    with _patch_session([_je(status=JobStatus.RUNNING)]):
        with pytest.raises(MCPUserError, match="Target run is in `Running` state"):
            compare_profiling_runs(str(target_run.job_execution_id))


@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_rejects_canceled_target(mock_resolve, db_session_mock):
    target_run = _profiling_run()
    mock_resolve.return_value = target_run

    with _patch_session([_je(status=JobStatus.CANCELED)]):
        with pytest.raises(MCPUserError, match="`Canceled`"):
            compare_profiling_runs(str(target_run.job_execution_id))


@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_rejects_cross_table_group(mock_resolve, db_session_mock):
    target_run = _profiling_run(table_groups_id=uuid4())
    baseline_run = _profiling_run(table_groups_id=uuid4())
    mock_resolve.side_effect = [target_run, baseline_run]

    with _patch_session([_je()]):
        with pytest.raises(MCPUserError, match="same table group"):
            compare_profiling_runs(
                str(target_run.job_execution_id),
                str(baseline_run.job_execution_id),
            )


def test_compare_profiling_runs_column_requires_table(db_session_mock):
    with pytest.raises(MCPUserError, match="`column_name` requires `table_name`"):
        compare_profiling_runs(str(uuid4()), column_name="email")


@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_auto_baseline_first_run(mock_resolve, db_session_mock):
    target_run = _profiling_run()
    target_run.get_previous.return_value = None
    mock_resolve.return_value = target_run

    with _patch_session([_je()]):
        with pytest.raises(MCPUserError, match="no earlier completed profiling run"):
            compare_profiling_runs(str(target_run.job_execution_id))


@patch("testgen.mcp.tools.profile_history.HygieneIssue")
@patch("testgen.mcp.tools.profile_history.HygieneIssueType")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.profile_history.resolve_profiling_run")
def test_compare_profiling_runs_identical_runs_renders_no_changes(
    mock_resolve, mock_pr, mock_iss_type, mock_iss, db_session_mock,
):
    tg_id = uuid4()
    target_run = _profiling_run(table_groups_id=tg_id)
    baseline_run = _profiling_run(table_groups_id=tg_id, profiling_starttime=datetime(2026, 5, 1))
    target_run.get_previous.return_value = baseline_run
    mock_resolve.return_value = target_run

    target_row = _profile_row(run_id=target_run.id)
    baseline_row = _profile_row(run_id=baseline_run.id)  # same values
    mock_pr.select_for_runs.return_value = [target_row, baseline_row]
    mock_iss.select_where.return_value = []
    mock_iss_type.select_where.return_value = []

    with _patch_session([_je(), _je()]):
        result = compare_profiling_runs(str(target_run.job_execution_id))

    assert "No changes between target and baseline" in result


# ----------------------------------------------------------------------
# get_profiling_trends
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_happy_path(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    tg = _table_group()
    mock_tg_cls.get.return_value = tg

    run_old = _profiling_run(profiling_starttime=datetime(2026, 5, 1))
    run_new = _profiling_run(profiling_starttime=datetime(2026, 5, 13))
    mock_pr_cls.list_recent_complete.return_value = [run_new, run_old]
    mock_pr_cls.count_confirmed_hygiene_issues.return_value = {}

    rows = [
        _profile_row(run_id=run_old.id, null_value_ct=300),
        _profile_row(run_id=run_new.id, null_value_ct=50),
    ]
    mock_pr.select_for_runs.return_value = rows

    result = get_profiling_trends(
        str(tg.id),
        metrics=["Null Ratio", "Distinct Ratio"],
        table_name="orders",
        column_name="customer_email",
    )

    assert "Profiling trends" in result
    assert "Null Ratio" in result
    assert "Distinct Ratio" in result
    assert "2026-05-13" in result and "2026-05-01" in result


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_invalid_metric(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()

    with pytest.raises(MCPUserError, match="Invalid metrics"):
        get_profiling_trends(str(uuid4()), metrics=["Unknown Metric"])


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_empty_metrics(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()

    with pytest.raises(MCPUserError, match="cannot be empty"):
        get_profiling_trends(str(uuid4()), metrics=[])


@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_column_requires_table(mock_tg_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()

    with pytest.raises(MCPUserError, match="`column_name` requires `table_name`"):
        get_profiling_trends(
            str(uuid4()),
            metrics=["Null Ratio"],
            column_name="email",
        )


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_no_runs(mock_tg_cls, mock_pr_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()
    mock_pr_cls.list_recent_complete.return_value = []

    # TG-scope metric so we skip the profile-row fetch entirely
    result = get_profiling_trends(str(uuid4()), metrics=["Profiling Score"])
    assert "No completed profiling runs" in result


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_first_appears_note(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    """Entity missing from the oldest run but present in newer runs."""
    mock_tg_cls.get.return_value = _table_group()
    run_old = _profiling_run(profiling_starttime=datetime(2026, 5, 1, 9, 0))
    run_mid = _profiling_run(profiling_starttime=datetime(2026, 5, 10, 14, 0))
    run_new = _profiling_run(profiling_starttime=datetime(2026, 5, 13, 10, 0))
    mock_pr_cls.list_recent_complete.return_value = [run_new, run_mid, run_old]
    # Only mid and new runs have the column — entity first appears at run_mid.
    mock_pr.select_for_runs.return_value = [
        _profile_row(run_id=run_mid.id),
        _profile_row(run_id=run_new.id),
    ]

    result = get_profiling_trends(
        str(uuid4()),
        metrics=["Null Ratio"],
        table_name="orders",
        column_name="customer_email",
    )
    assert "first appears in the run started 2026-05-10 14:00" in result
    assert "last appears" not in result  # present in newest run, no trailing-gap note


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_last_appears_note(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    """Entity present in early runs but missing from the newest run."""
    mock_tg_cls.get.return_value = _table_group()
    run_old = _profiling_run(profiling_starttime=datetime(2026, 5, 1, 9, 0))
    run_mid = _profiling_run(profiling_starttime=datetime(2026, 5, 10, 14, 0))
    run_new = _profiling_run(profiling_starttime=datetime(2026, 5, 13, 10, 0))
    mock_pr_cls.list_recent_complete.return_value = [run_new, run_mid, run_old]
    # Only old and mid runs have the column — entity last appears at run_mid.
    mock_pr.select_for_runs.return_value = [
        _profile_row(run_id=run_old.id),
        _profile_row(run_id=run_mid.id),
    ]

    result = get_profiling_trends(
        str(uuid4()),
        metrics=["Null Ratio"],
        table_name="orders",
        column_name="legacy_id",
    )
    assert "last appears in the run started 2026-05-10 14:00" in result
    assert "first appears" not in result  # present in oldest run, no leading-gap note


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_both_notes(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    """Entity has a bounded lifetime — missing on both ends of the window."""
    mock_tg_cls.get.return_value = _table_group()
    run_oldest = _profiling_run(profiling_starttime=datetime(2026, 5, 9, 9, 0))
    run_first = _profiling_run(profiling_starttime=datetime(2026, 5, 10, 14, 0))
    run_last = _profiling_run(profiling_starttime=datetime(2026, 5, 12, 22, 0))
    run_newest = _profiling_run(profiling_starttime=datetime(2026, 5, 13, 10, 0))
    mock_pr_cls.list_recent_complete.return_value = [run_newest, run_last, run_first, run_oldest]
    # Only the middle two runs carry the column.
    mock_pr.select_for_runs.return_value = [
        _profile_row(run_id=run_first.id),
        _profile_row(run_id=run_last.id),
    ]

    result = get_profiling_trends(
        str(uuid4()),
        metrics=["Null Ratio"],
        table_name="orders",
        column_name="customer_email_v2",
    )
    assert "first appears in the run started 2026-05-10 14:00" in result
    assert "last appears in the run started 2026-05-12 22:00" in result


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_profiling_trends_no_notes_when_present_throughout(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    """Entity present in every run — no first/last-appears noise."""
    mock_tg_cls.get.return_value = _table_group()
    run_old = _profiling_run(profiling_starttime=datetime(2026, 5, 1, 9, 0))
    run_new = _profiling_run(profiling_starttime=datetime(2026, 5, 13, 10, 0))
    mock_pr_cls.list_recent_complete.return_value = [run_new, run_old]
    mock_pr.select_for_runs.return_value = [
        _profile_row(run_id=run_old.id),
        _profile_row(run_id=run_new.id),
    ]

    result = get_profiling_trends(
        str(uuid4()),
        metrics=["Null Ratio"],
        table_name="orders",
        column_name="customer_id",
    )
    assert "first appears" not in result
    assert "last appears" not in result


# ----------------------------------------------------------------------
# get_schema_history
# ----------------------------------------------------------------------


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.profile_history.ProfileResult")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_schema_history_happy_path(mock_tg_cls, mock_pr, mock_pr_cls, db_session_mock):
    tg = _table_group()
    mock_tg_cls.get.return_value = tg

    run_old = _profiling_run(profiling_starttime=datetime(2026, 5, 1))
    run_new = _profiling_run(profiling_starttime=datetime(2026, 5, 13))
    mock_pr_cls.list_recent_complete.return_value = [run_new, run_old]

    rows = [
        _profile_row(run_id=run_old.id, table_name="orders", column_name="id", general_type="N", record_ct=900),
        _profile_row(run_id=run_old.id, table_name="orders", column_name="email", general_type="A", record_ct=900),
        _profile_row(run_id=run_new.id, table_name="orders", column_name="id", general_type="N", record_ct=1000),
        _profile_row(run_id=run_new.id, table_name="orders", column_name="email", general_type="A", record_ct=1000),
        _profile_row(run_id=run_new.id, table_name="orders", column_name="phone", general_type="A", record_ct=1000),
    ]
    mock_pr.select_for_runs.return_value = rows

    result = get_schema_history(str(tg.id))

    assert "Schema history" in result
    assert "phone" in result  # newly added column
    assert "Record count" in result  # 900 → 1,000 delta


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_schema_history_single_run_short_circuits(mock_tg_cls, mock_pr_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()
    mock_pr_cls.list_recent_complete.return_value = [_profiling_run()]

    result = get_schema_history(str(uuid4()))
    assert "at least two are needed" in result


@patch("testgen.mcp.tools.profile_history.ProfilingRun")
@patch("testgen.mcp.tools.common.TableGroup")
def test_get_schema_history_no_runs(mock_tg_cls, mock_pr_cls, db_session_mock):
    mock_tg_cls.get.return_value = _table_group()
    mock_pr_cls.list_recent_complete.return_value = []

    result = get_schema_history(str(uuid4()))
    assert "No completed profiling runs" in result
