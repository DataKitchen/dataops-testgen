from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from testgen.commands.test_generation import TestGeneration

MODULE = "testgen.commands.test_generation"


def _make_generation(profile_run_id=None) -> TestGeneration:
    tg = TestGeneration.__new__(TestGeneration)  # bypass __init__ (needs no DB)
    tg.table_group = MagicMock(id="tg-id", table_group_schema="s")
    tg.test_suite = MagicMock(id="suite-id")
    tg.generation_set = "Standard"
    tg.test_types_filter = None
    tg.run_date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    tg.as_of_date = tg.run_date
    tg.flavor = "postgresql"
    tg.flavor_service = MagicMock(quote_character='"')
    tg.profile_run_id = profile_run_id or uuid4()
    return tg


@patch("testgen.commands.test_generation.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[])
def test_run_appends_override_delete_after_stale_delete(_mock_gen, mock_exec):
    tg = _make_generation()

    tg.run()

    executed_queries = [query for query, _params in mock_exec.call_args[0][0]]
    override_idx = next(
        i for i, q in enumerate(executed_queries)
        if "tt.overrides = g.test_type" in q
    )
    stale_idx = next(
        i for i, q in enumerate(executed_queries)
        if "last_auto_gen_date < :RUN_DATE" in q
    )
    assert override_idx > stale_idx, "override delete must run after the stale delete"


# --- Which profiling run generation reads ---


@patch(f"{MODULE}.ProfilingRun")
def test_finishing_run_id_is_passed_through_to_resolution(mock_profiling_run):
    """A caller that just finished a profiling run passes its id so it counts as complete --
    its job execution is still 'running' at this point. It does not skip resolution, because
    the as-of date still applies."""
    finishing = uuid4()
    table_group = MagicMock(id="tg-id", profiling_delay_days=0)

    TestGeneration(
        MagicMock(sql_flavor="postgresql"), table_group, MagicMock(id="suite-id"),
        "Standard", None, finishing,
    )

    _, kwargs = mock_profiling_run.latest_readable_id.call_args
    assert kwargs["finishing_run_id"] == finishing


@patch(f"{MODULE}.ProfilingRun")
def test_resolution_result_is_what_generation_reads(mock_profiling_run):
    resolved = uuid4()
    mock_profiling_run.latest_readable_id.return_value = resolved
    table_group = MagicMock(id="tg-id", profiling_delay_days=0)

    tg = TestGeneration(
        MagicMock(sql_flavor="postgresql"), table_group, MagicMock(id="suite-id"), "Standard",
    )

    assert tg.profile_run_id == resolved
    args, _ = mock_profiling_run.latest_readable_id.call_args
    assert args == ("tg-id", tg.as_of_date)


@patch(f"{MODULE}.ProfilingRun")
def test_profiling_delay_days_still_bounds_a_freshly_finished_run(mock_profiling_run):
    """With a delay configured, generation reads an older run even when handed the run that
    just finished -- the delay is the point of the setting."""
    table_group = MagicMock(id="tg-id", profiling_delay_days=3)

    tg = TestGeneration(
        MagicMock(sql_flavor="postgresql"), table_group, MagicMock(id="suite-id"),
        "Standard", None, uuid4(),
    )

    args, _ = mock_profiling_run.latest_readable_id.call_args
    assert args[1] == tg.as_of_date
    assert (tg.run_date - args[1]).days == 3


def test_generation_queries_are_scoped_to_the_resolved_run():
    run_id = uuid4()
    tg = _make_generation(profile_run_id=run_id)

    assert tg._get_params()["PROFILE_RUN_ID"] == run_id


@patch(f"{MODULE}.LOG")
@patch(f"{MODULE}.ProfilingRun")
def test_no_eligible_run_is_logged(mock_profiling_run, mock_log):
    """A NULL run id joins to zero rows in every generation template, so generation ends
    reporting success with nothing created. The warning is the only signal it happened."""
    mock_profiling_run.latest_readable_id.return_value = None

    TestGeneration(
        MagicMock(sql_flavor="postgresql"),
        MagicMock(id="tg-id", profiling_delay_days=0),
        MagicMock(id="suite-id"),
        "Standard",
    )

    assert mock_log.warning.called


@patch(f"{MODULE}.LOG")
@patch(f"{MODULE}.ProfilingRun")
def test_eligible_run_is_not_logged_as_a_warning(mock_profiling_run, mock_log):
    mock_profiling_run.latest_readable_id.return_value = uuid4()

    TestGeneration(
        MagicMock(sql_flavor="postgresql"),
        MagicMock(id="tg-id", profiling_delay_days=0),
        MagicMock(id="suite-id"),
        "Standard",
    )

    assert not mock_log.warning.called
