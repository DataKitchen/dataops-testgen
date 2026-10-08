from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.test_generation import TestGeneration, run_conformance_generation, run_test_generation
from testgen.common.enums import SuiteType
from testgen.common.models.suite_version import FrozenVersionError

MODULE = "testgen.commands.test_generation"


@pytest.fixture(autouse=True)
def writable_target_version(monkeypatch):
    """Generation refuses a frozen target version, which costs it a query. Answer that query
    with a writable version so every other test here exercises the path it is about.
    """
    monkeypatch.setattr(
        "testgen.common.models.suite_version.get_current_session",
        MagicMock(return_value=MagicMock(**{"scalar.return_value": None})),
    )


def _make_generation(generation_sets=None, profile_run_id=None) -> TestGeneration:
    tg = TestGeneration.__new__(TestGeneration)  # bypass __init__ (needs no DB)
    tg.table_group = MagicMock(id="tg-id", table_group_schema="s")
    tg.test_suite = MagicMock(id="suite-id")
    tg.generation_sets = generation_sets or ["Standard"]
    tg.test_types_filter = None
    tg.run_date = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    tg.as_of_date = tg.run_date
    tg.flavor = "postgresql"
    tg.flavor_service = MagicMock(quote_character='"')
    tg.profile_run_id = profile_run_id or uuid4()
    tg.version_id = uuid4()
    tg.table_names = None
    return tg


def _generation(table_names=None) -> TestGeneration:
    tg = _make_generation()
    tg.table_names = table_names
    return tg


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
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
        ["Standard"], None, finishing,
    )

    _, kwargs = mock_profiling_run.latest_readable_id.call_args
    assert kwargs["finishing_run_id"] == finishing


@patch(f"{MODULE}.ProfilingRun")
def test_resolution_result_is_what_generation_reads(mock_profiling_run):
    resolved = uuid4()
    mock_profiling_run.latest_readable_id.return_value = resolved
    table_group = MagicMock(id="tg-id", profiling_delay_days=0)

    tg = TestGeneration(
        MagicMock(sql_flavor="postgresql"), table_group, MagicMock(id="suite-id"), ["Standard"],
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
        ["Standard"], None, uuid4(),
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
        ["Standard"],
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
        ["Standard"],
    )

    assert not mock_log.warning.called


# --- Generation sets ---


def test_params_bind_the_generation_set_list():
    tg = _make_generation(["Standard", "Plugin_Set"])

    params = tg._get_params()

    assert params["GENERATION_SETS"] == ["Standard", "Plugin_Set"]
    assert "GENERATION_SET" not in params


# --- run_test_generation ---


@pytest.fixture
def generation_mocks():
    with (
        patch(f"{MODULE}.TestSuite") as suite_cls,
        patch(f"{MODULE}.TableGroup") as tg_cls,
        patch(f"{MODULE}.Connection") as conn_cls,
        patch(f"{MODULE}.TestGeneration") as gen_cls,
        patch(f"{MODULE}.MixpanelService") as mixpanel_cls,
        patch(f"{MODULE}.resolve_generation_sets") as resolve,
        patch(f"{MODULE}.job_context") as ctx,
    ):
        suite = MagicMock(suite_type=SuiteType.REGULAR, generation_sets=None)
        suite_cls.get.return_value = suite
        tg_cls.get.return_value = MagicMock()
        conn_cls.get.return_value = MagicMock(sql_flavor="postgresql")
        ctx.get.return_value = MagicMock(source="ui")
        resolve.return_value = ["Standard"]
        yield {
            "suite": suite,
            "generation": gen_cls,
            "mixpanel": mixpanel_cls,
            "resolve": resolve,
        }


def test_run_test_generation_runs_all_sets_as_one_run(generation_mocks):
    generation_mocks["resolve"].return_value = ["Standard", "Plugin_Set"]

    run_test_generation("suite-1", ["Standard", "Plugin_Set"])

    generation_mocks["generation"].assert_called_once()
    passed_sets = generation_mocks["generation"].call_args[0][3]
    assert passed_sets == ["Standard", "Plugin_Set"]


def test_run_test_generation_persists_resolved_sets_on_success(generation_mocks):
    generation_mocks["resolve"].return_value = ["Standard", "Plugin_Set"]

    run_test_generation("suite-1", ["Standard", "Plugin_Set"])

    assert generation_mocks["suite"].generation_sets == ["Standard", "Plugin_Set"]


def test_run_test_generation_reraises_and_does_not_persist_on_failure(generation_mocks):
    generation_mocks["generation"].return_value.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_test_generation("suite-1", ["Standard"])

    assert generation_mocks["suite"].generation_sets is None


def test_run_test_generation_sends_the_full_set_list_to_mixpanel(generation_mocks):
    generation_mocks["resolve"].return_value = ["Standard", "Plugin_Set"]

    run_test_generation("suite-1", ["Standard", "Plugin_Set"])

    event_kwargs = generation_mocks["mixpanel"].return_value.send_event.call_args.kwargs
    assert event_kwargs["generation_sets"] == ["Standard", "Plugin_Set"]


def test_run_test_generation_sends_mixpanel_event_even_on_failure(generation_mocks):
    generation_mocks["generation"].return_value.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_test_generation("suite-1", ["Standard"])

    generation_mocks["mixpanel"].return_value.send_event.assert_called_once()


def test_run_test_generation_defaults_to_none_requested(generation_mocks):
    run_test_generation("suite-1")

    generation_mocks["resolve"].assert_called_once_with(generation_mocks["suite"], None)


def test_run_test_generation_rejects_monitor_suite(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.MONITOR

    with pytest.raises(ValueError, match="Cannot run regular test generation for monitor suite"):
        run_test_generation("suite-1", ["Standard"])


def test_generation_params_carry_the_resolved_version():
    tg = _make_generation()

    assert tg._get_params()["VERSION_ID"] == tg.version_id


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
def test_the_stale_delete_is_bound_to_a_version(_mock_gen, mock_exec):
    tg = _make_generation()

    tg.run()

    stale_query, stale_params = next(
        (query, params) for query, params in mock_exec.call_args[0][0]
        if "last_auto_gen_date < :RUN_DATE" in query
    )

    assert "version_id = :VERSION_ID" in stale_query
    assert stale_params["VERSION_ID"] == tg.version_id


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[])
def test_run_is_a_no_op_when_no_generation_queries_resolve(_mock_gen, mock_exec):
    """An empty generation set (a set name with no test types tagged to it, e.g. a contract
    suite before its member test types are curated) must not run the stale-delete: with no
    inserts, that delete would sweep every unlocked auto-generated test in the version."""
    tg = _make_generation()

    tg.run()

    mock_exec.assert_not_called()


# --- Table scope for contracts ---


def test_generation_for_declared_tables_binds_the_list_rather_than_interpolating_it():
    generation = _generation(table_names=["orders", "customers"])
    params = generation._get_params()

    assert params["TABLE_FILTER"] == "AND table_name = ANY(:TABLE_NAMES)"
    assert params["TABLE_NAMES"] == ["orders", "customers"]


def test_generation_without_declared_tables_applies_no_table_filter():
    params = _generation(table_names=None)._get_params()

    assert params["TABLE_FILTER"] == ""


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
def test_a_single_table_run_scopes_the_stale_delete_to_its_own_tables(_mock_gen, mock_exec):
    """A run scoped to a contract's declared tables must not sweep another declared table's
    terms: the stale-delete is not itself filtered by which tables this run generated, so
    without this scoping, declaring a second table would delete the first one's terms."""
    tg = _make_generation()
    tg.table_names = ["orders"]

    tg.run()

    stale_query, stale_params = next(
        (query, params) for query, params in mock_exec.call_args[0][0]
        if "last_auto_gen_date < :RUN_DATE" in query
    )

    assert "AND table_name = ANY(:TABLE_NAMES)" in stale_query
    assert stale_params["TABLE_NAMES"] == ["orders"]


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
def test_a_run_with_no_declared_tables_leaves_the_stale_delete_unscoped(_mock_gen, mock_exec):
    tg = _make_generation()

    tg.run()

    stale_query, _ = next(
        (query, params) for query, params in mock_exec.call_args[0][0]
        if "last_auto_gen_date < :RUN_DATE" in query
    )

    assert "table_name = ANY" not in stale_query


def test_a_contract_declaring_no_tables_generates_for_none_of_them():
    """An empty declared-table list is a scope of nothing, not an absent scope. A contract
    whose document declares no tables yet must generate no terms, rather than falling back
    to every table in the group.
    """
    params = _generation(table_names=[])._get_params()

    assert params["TABLE_FILTER"] == "AND table_name = ANY(:TABLE_NAMES)"
    assert params["TABLE_NAMES"] == []


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
def test_generation_refuses_to_write_a_frozen_contract_version(_mock_gen, _mock_exec):
    """Generation writes test_definitions through raw SQL, so the model-level guard never
    sees it. A contract whose only version is frozen must not have that version rewritten.
    """
    frozen_version_id = uuid4()
    generation = _make_generation()
    generation.version_id = frozen_version_id

    with patch(
        "testgen.common.models.suite_version.get_current_session",
        return_value=MagicMock(**{"scalar.return_value": frozen_version_id}),
    ):
        with pytest.raises(FrozenVersionError):
            generation.run()


# --- Managed tests ---


@patch(f"{MODULE}.execute_db_queries")
@patch.object(TestGeneration, "_get_generation_queries", return_value=[("SELECT 1", {})])
def test_the_stale_delete_spares_managed_tests(_mock_gen, mock_exec):
    """A conformance test is generated with a run date like any other but by no generation
    set, so set-based generation would find it stale on every run and delete it."""
    tg = _make_generation()

    tg.run()

    stale_query, stale_params = next(
        (query, params) for query, params in mock_exec.call_args[0][0]
        if "last_auto_gen_date < :RUN_DATE" in query
    )

    assert "NOT (test_type = ANY(:MANAGED_TEST_TYPES))" in stale_query
    assert stale_params["MANAGED_TEST_TYPES"] == ["Schema_Conformance"]


@patch(f"{MODULE}.execute_db_queries")
def test_conformance_run_adds_then_removes_against_the_resolved_version(mock_exec):
    tg = _make_generation()

    tg.conformance_run()

    (insert_query, insert_params), (delete_query, delete_params) = mock_exec.call_args[0][0]
    assert "INSERT INTO test_definitions" in insert_query
    assert "'Schema_Conformance'" in insert_query
    assert "DELETE FROM test_definitions" in delete_query
    assert insert_params["VERSION_ID"] == delete_params["VERSION_ID"] == tg.version_id


@patch(f"{MODULE}.execute_db_queries")
def test_conformance_run_scopes_additions_to_the_named_tables(mock_exec):
    tg = _generation(table_names=["orders"])

    tg.conformance_run()

    (insert_query, insert_params), (delete_query, _) = mock_exec.call_args[0][0]
    assert "AND table_name = ANY(:TABLE_NAMES)" in insert_query
    assert insert_params["TABLE_NAMES"] == ["orders"]
    assert "TABLE_NAMES" not in delete_query


@patch(f"{MODULE}.execute_db_queries")
def test_conformance_run_refuses_to_write_a_frozen_contract_version(mock_exec):
    frozen_version_id = uuid4()
    generation = _make_generation()
    generation.version_id = frozen_version_id

    with patch(
        "testgen.common.models.suite_version.get_current_session",
        return_value=MagicMock(**{"scalar.return_value": frozen_version_id}),
    ):
        with pytest.raises(FrozenVersionError):
            generation.conformance_run()

    mock_exec.assert_not_called()


@pytest.mark.parametrize("suite_type", [SuiteType.REGULAR, SuiteType.MONITOR])
def test_conformance_generation_refuses_a_suite_that_is_not_a_contract(generation_mocks, suite_type):
    generation_mocks["suite"].suite_type = suite_type

    with pytest.raises(ValueError, match="not a contract"):
        run_conformance_generation("suite-1")

    generation_mocks["generation"].assert_not_called()


def test_conformance_generation_reconciles_a_contract(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.CONTRACT

    run_conformance_generation("suite-1", table_names=["orders"])

    generation_mocks["generation"].return_value.conformance_run.assert_called_once_with()
    assert generation_mocks["generation"].call_args.kwargs["table_names"] == ["orders"]
