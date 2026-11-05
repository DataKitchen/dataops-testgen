import contextlib
import re
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import duckdb
import pytest

from testgen.commands.test_generation import (
    ContractGenerationResult,
    TestGeneration,
    TestTypeParams,
    _term_count,
    parse_regeneration_groups,
    reconcile_contract_conformance,
    report_test_generation,
    run_contract_generation,
    run_test_generation,
    run_test_generation_and_report,
)
from testgen.common.enums import JobSource, JobStatus, RegenerationGroup, SuiteType
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.suite_version import FrozenVersionError
from testgen.common.read_file import read_template_yaml_file
from tests.unit.sql_assertions import conjuncts, equality_conjunct

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
    ):
        suite = MagicMock(suite_type=SuiteType.REGULAR, generation_sets=None)
        suite_cls.get.return_value = suite
        tg_cls.get.return_value = MagicMock()
        conn_cls.get.return_value = MagicMock(sql_flavor="postgresql")
        resolve.return_value = ["Standard"]
        yield {
            "suite": suite,
            "table_group": tg_cls.get.return_value,
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


def test_an_inline_generation_reports_the_resolved_set_list(generation_mocks):
    generation_mocks["resolve"].return_value = ["Standard", "Plugin_Set"]

    run_test_generation_and_report(JobSource.ui, "suite-1", ["Standard", "Plugin_Set"])

    event_kwargs = generation_mocks["mixpanel"].return_value.send_event.call_args.kwargs
    assert event_kwargs["generation_sets"] == ["Standard", "Plugin_Set"]


def test_run_test_generation_defaults_to_none_requested(generation_mocks):
    run_test_generation("suite-1")

    generation_mocks["resolve"].assert_called_once_with(generation_mocks["suite"], None)


def test_run_test_generation_rejects_monitor_suite(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.MONITOR

    with pytest.raises(ValueError, match="Cannot run regular test generation for monitor suite"):
        run_test_generation("suite-1", ["Standard"])


def test_a_contracts_generation_runs_the_contract_generation(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.CONTRACT
    with patch(f"{MODULE}.run_contract_generation") as generate_contract:
        result = run_test_generation("suite-1", table_names=["orders"], regenerate=["tests"])

    generate_contract.assert_called_once_with(
        generation_mocks["suite"].id, table_names=["orders"], profile_run_id=None, groups=["tests"]
    )
    assert result is generate_contract.return_value
    generation_mocks["generation"].assert_not_called()


def test_regeneration_groups_are_refused_for_a_regular_suite(generation_mocks):
    with pytest.raises(ValueError, match="contracts only"):
        run_test_generation("suite-1", regenerate=["tests"])

    generation_mocks["generation"].assert_not_called()


def test_a_regular_suites_generation_opens_nothing(generation_mocks):
    with (
        patch(f"{MODULE}.TestDefinition.resolve_writable") as route,
        patch(f"{MODULE}.get_current_session") as get_session,
    ):
        run_test_generation("suite-1")

    route.assert_not_called()
    get_session.return_value.commit.assert_not_called()


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
    """An empty table-name list is a scope of nothing, not an absent scope: generation narrowed
    to no tables generates no terms rather than falling back to every table in the group.
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
@pytest.mark.parametrize("generate", [run_contract_generation, reconcile_contract_conformance])
def test_contract_generation_refuses_a_suite_that_is_not_a_contract(generation_mocks, suite_type, generate):
    generation_mocks["suite"].suite_type = suite_type

    with pytest.raises(ValueError, match="not a contract"):
        generate("suite-1")

    generation_mocks["generation"].assert_not_called()


def test_reconciling_conformance_generates_only_conformance_tests(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.CONTRACT

    with patch(f"{MODULE}.TestDefinition") as definitions:
        reconcile_contract_conformance("suite-1")

    generation = generation_mocks["generation"]
    generation.return_value.conformance_run.assert_called_once_with()
    generation.return_value.run.assert_not_called()
    definitions.assign_missing_term_ids.assert_called_once_with(generation.return_value.version_id)


@pytest.fixture
def contract_mocks(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.CONTRACT
    draft = MagicMock(metadata_document={"schema": [{"name": "orders"}, {"name": "customers"}]})
    version_id = uuid4()
    run_id = uuid4()
    events: list[str] = []
    session = MagicMock()
    session.commit.side_effect = lambda: events.append("commit")
    generation_mocks["generation"].return_value.run.side_effect = lambda: events.append("generate")
    generation_mocks["generation"].return_value.conformance_run.side_effect = lambda: events.append("conformance")
    with (
        patch(f"{MODULE}.TestDefinition") as definitions,
        patch(f"{MODULE}.SuiteVersion") as versions,
        patch(f"{MODULE}.contract_document") as document,
        patch(f"{MODULE}.resolve_generation_profile_run", return_value=run_id) as resolve_run,
        patch(f"{MODULE}.get_current_session", return_value=session),
        patch(f"{MODULE}.flag_modified"),
        patch(f"{MODULE}._term_count", return_value=7),
    ):
        definitions.resolve_write_target.return_value = (version_id, {})
        versions.get.return_value = draft
        document.declared_tables.side_effect = lambda doc: [table["name"] for table in doc.get("schema", [])]
        document.catalog_table_names.return_value = ["orders", "customers", "products"]
        document.refresh_tables.side_effect = lambda _doc, _group, names, **_flags: dict.fromkeys(names, 3)
        document.profiled_table_names.side_effect = lambda _run, names: list(names)
        yield {
            **generation_mocks,
            "draft": draft,
            "session": session,
            "version_id": version_id,
            "run_id": run_id,
            "events": events,
            "definitions": definitions,
            "document": document,
            "resolve_run": resolve_run,
        }


def test_generating_an_unprofiled_contract_writes_catalog_metadata_and_reconciles_conformance_only(contract_mocks):
    contract_mocks["resolve_run"].return_value = None

    result = run_contract_generation("suite-1")

    contract_mocks["document"].refresh_tables.assert_called_once()
    contract_mocks["generation"].return_value.run.assert_not_called()
    contract_mocks["generation"].return_value.conformance_run.assert_called_once_with()
    contract_mocks["document"].fill_profiled_values.assert_not_called()
    assert contract_mocks["events"] == ["commit", "conformance"]
    assert result.tables_not_profiled == ["orders", "customers"]


def test_a_generation_refreshes_the_contract_identity_before_its_tables(contract_mocks):
    calls = []
    contract_mocks["document"].refresh_identity.side_effect = lambda _doc, _group: calls.append("identity")
    contract_mocks["document"].refresh_tables.side_effect = lambda _doc, _group, names, **_flags: (
        calls.append("tables") or dict.fromkeys(names, 3)
    )

    run_contract_generation("suite-1")

    assert calls == ["identity", "tables"]


def test_a_generation_that_skips_the_identity_leaves_the_contract_fields_alone(contract_mocks):
    run_contract_generation("suite-1", table_names=["orders"], refresh_identity=False)

    contract_mocks["document"].refresh_identity.assert_not_called()
    contract_mocks["document"].refresh_tables.assert_called_once()


def test_a_generation_never_generates_terms_for_a_declared_table_the_profiling_run_missed(contract_mocks):
    """Generation deletes the terms of the tables it covers that it did not produce again, so a
    table the run has no results for would lose every generated term."""
    contract_mocks["document"].profiled_table_names.side_effect = lambda _run, _names: ["orders"]

    result = run_contract_generation("suite-1")

    assert contract_mocks["generation"].call_args_list[0].kwargs["table_names"] == ["orders"]
    assert result.tables_not_profiled == ["customers"]


def test_a_generation_with_no_profiled_table_generates_no_terms(contract_mocks):
    contract_mocks["document"].profiled_table_names.side_effect = lambda _run, _names: []

    result = run_contract_generation("suite-1")

    contract_mocks["generation"].return_value.run.assert_not_called()
    contract_mocks["generation"].return_value.conformance_run.assert_called_once_with()
    assert result.tables_not_profiled == ["orders", "customers"]


def test_a_generation_reports_what_it_did(contract_mocks):
    contract_mocks["document"].refresh_tables.side_effect = lambda _doc, _group, _names, **_flags: {"orders": 4, "customers": 0}

    result = run_contract_generation("suite-1")

    assert result == ContractGenerationResult(
        term_count=7, tables_declared=["orders", "customers"], tables_not_in_catalog=["customers"],
        tables_not_profiled=[],
    )


def test_generating_a_contract_generates_the_contract_set_for_its_declared_tables(contract_mocks):
    run_contract_generation("suite-1")

    generation = contract_mocks["generation"]
    set_generation = generation.call_args_list[0]
    assert set_generation.args[3] == ["Contract"]
    assert set_generation.kwargs["table_names"] == ["orders", "customers"]
    assert set_generation.kwargs["profile_run_id"] == contract_mocks["run_id"]
    generation.return_value.run.assert_called_once_with()
    generation.return_value.conformance_run.assert_called_once_with()


def test_generating_named_tables_reconciles_conformance_across_the_whole_draft(contract_mocks):
    run_contract_generation("suite-1", table_names=["orders"])

    set_generation, conformance = contract_mocks["generation"].call_args_list
    assert set_generation.kwargs["table_names"] == ["orders"]
    assert "table_names" not in conformance.kwargs


def test_generating_a_contract_that_declares_no_tables_declares_the_whole_catalog(contract_mocks):
    contract_mocks["draft"].metadata_document = {"schema": []}

    run_contract_generation("suite-1")

    tables = ["orders", "customers", "products"]
    assert contract_mocks["document"].refresh_tables.call_args.args[2] == tables
    assert contract_mocks["generation"].call_args_list[0].kwargs["table_names"] == tables


def test_generating_named_tables_covers_only_those(contract_mocks):
    run_contract_generation("suite-1", table_names=["orders"])

    assert contract_mocks["document"].refresh_tables.call_args.args[2] == ["orders"]
    assert contract_mocks["generation"].call_args_list[0].kwargs["table_names"] == ["orders"]


def test_generating_a_contract_commits_the_document_before_generating(contract_mocks):
    run_contract_generation("suite-1")

    assert contract_mocks["events"] == ["commit", "generate", "conformance"]


def test_generating_a_contract_reloads_the_draft_before_writing_profiled_values(contract_mocks):
    events = contract_mocks["events"]
    contract_mocks["session"].refresh.side_effect = lambda _draft: events.append("refresh")
    contract_mocks["document"].fill_profiled_values.side_effect = lambda *_args: events.append("profiled")

    run_contract_generation("suite-1")

    contract_mocks["session"].refresh.assert_called_once_with(contract_mocks["draft"])
    assert events[-2:] == ["refresh", "profiled"]


def test_generating_a_contract_fills_the_profiled_values_of_its_tables(contract_mocks):
    run_contract_generation("suite-1")

    contract_mocks["document"].fill_profiled_values.assert_called_once_with(
        contract_mocks["draft"].metadata_document,
        contract_mocks["table_group"].id,
        contract_mocks["run_id"],
        ["orders", "customers"],
    )


def test_regenerating_only_tests_leaves_the_document_and_profiled_values_alone(contract_mocks):
    result = run_contract_generation("suite-1", groups=["tests"])

    contract_mocks["document"].refresh_identity.assert_not_called()
    assert contract_mocks["document"].refresh_tables.call_args.kwargs == {"profiling": False, "catalog_metadata": False}
    contract_mocks["document"].fill_profiled_values.assert_not_called()
    assert contract_mocks["events"] == ["commit", "generate", "conformance"]
    assert result.groups == [RegenerationGroup.TESTS]


def test_regenerating_without_catalog_metadata_keeps_the_identity_and_refreshes_profiling(contract_mocks):
    result = run_contract_generation("suite-1", groups=["profiling", "tests"])

    contract_mocks["document"].refresh_identity.assert_not_called()
    assert contract_mocks["document"].refresh_tables.call_args.kwargs == {"profiling": True, "catalog_metadata": False}
    contract_mocks["document"].fill_profiled_values.assert_called_once()
    assert result.groups == [RegenerationGroup.TESTS, RegenerationGroup.PROFILING]


def test_regenerating_without_tests_generates_no_terms_but_reconciles_conformance(contract_mocks):
    result = run_contract_generation("suite-1", groups=["catalog"])

    contract_mocks["document"].refresh_identity.assert_called_once()
    assert contract_mocks["document"].refresh_tables.call_args.kwargs == {"profiling": False, "catalog_metadata": True}
    contract_mocks["generation"].return_value.run.assert_not_called()
    contract_mocks["generation"].return_value.conformance_run.assert_called_once_with()
    contract_mocks["document"].fill_profiled_values.assert_not_called()
    assert result.groups == [RegenerationGroup.CATALOG]


def test_regenerating_tests_and_profiling_unprofiled_refreshes_the_catalog_and_reports_no_tests(contract_mocks):
    contract_mocks["resolve_run"].return_value = None

    result = run_contract_generation("suite-1", groups=["tests", "profiling"])

    assert contract_mocks["document"].refresh_tables.call_args.kwargs == {"profiling": True, "catalog_metadata": False}
    contract_mocks["generation"].return_value.run.assert_not_called()
    assert result.groups == [RegenerationGroup.PROFILING]
    assert result.tables_not_profiled == ["orders", "customers"]


def test_regenerating_only_tests_unprofiled_is_refused_before_anything_is_written(contract_mocks):
    contract_mocks["resolve_run"].return_value = None

    with pytest.raises(ValueError, match="has not been profiled"):
        run_contract_generation("suite-1", groups=["tests"])

    contract_mocks["document"].refresh_tables.assert_not_called()
    assert contract_mocks["events"] == []


@pytest.mark.parametrize(("values", "has_run", "expected"), [
    (["catalog", "tests"], True, [RegenerationGroup.TESTS, RegenerationGroup.CATALOG]),
    (["profiling", "profiling"], False, [RegenerationGroup.PROFILING]),
    (["tests", "profiling"], False, [RegenerationGroup.TESTS, RegenerationGroup.PROFILING]),
])
def test_regeneration_groups_parse_in_enum_order(values, has_run, expected):
    assert parse_regeneration_groups(values, has_profiling_run=has_run) == expected


@pytest.mark.parametrize(("values", "has_run", "message"), [
    ([], True, "at least one"),
    (["tests", "docs"], True, "Unknown regeneration group `docs`. Accepted values: `tests`, `profiling`, `catalog`."),
    (["tests"], False, "has not been profiled"),
])
def test_regeneration_groups_refuse_an_invalid_choice(values, has_run, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_regeneration_groups(values, has_profiling_run=has_run)


def test_the_term_count_covers_the_draft_s_generated_tables_and_leaves_out_conformance_tests():
    version_id = uuid4()
    session = MagicMock()
    session.scalar.return_value = 4
    with patch(f"{MODULE}.get_current_session", return_value=session):
        assert _term_count(version_id, ["orders"]) == 4

    statement = session.scalar.call_args.args[0]
    terms = conjuncts(statement.whereclause)
    assert any(equality_conjunct(term, "version_id", "test_definitions", version_id) for term in terms)
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "table_name IN ('orders')" in compiled
    assert "test_type NOT IN ('Schema_Conformance')" in compiled


def test_run_test_generation_generates_a_contract(generation_mocks):
    generation_mocks["suite"].suite_type = SuiteType.CONTRACT
    generation_mocks["resolve"].return_value = ["Contract"]

    with patch(f"{MODULE}.run_contract_generation") as generate:
        run_test_generation("suite-1")

    generate.assert_called_once_with(
        generation_mocks["suite"].id, table_names=None, profile_run_id=None, groups=list(RegenerationGroup)
    )
    generation_mocks["generation"].assert_not_called()


# --- Exact-measure requirements ---


def _selection_query(exact_measures: list[str] | None) -> str:
    test_type = TestTypeParams(
        test_type="Match_Lead_Space_Ct",
        selection_criteria="general_type = 'A' AND value_ct > 0",
        generation_template=None,
        default_parm_columns="baseline_ct",
        default_parm_values="lead_space_ct",
        exact_measures=exact_measures,
    )
    query, _params = _make_generation()._get_query("gen_selection_tests.sql", test_type=test_type)
    return query


def test_a_type_declaring_a_sampled_measure_is_not_selected_on_a_sampled_column():
    assert "(general_type = 'A' AND value_ct > 0\n) AND (sample_ratio IS NULL OR value_ct = 0)" in _selection_query(
        ["lead_space_ct"]
    )


@pytest.mark.parametrize(
    ("sample_ratio", "selected"),
    [(None, True), (0.1, False)],
)
def test_value_match_is_generated_only_on_a_column_profiled_without_sampling(sample_ratio, selected):
    value_match = read_template_yaml_file("test_types_LOV_Match.yaml", "dbsetup_test_types")["test_types"]
    criteria = ProfileResult.apply_exact_measures(value_match["selection_criteria"], value_match["exact_measures"])
    profile = duckdb.connect()
    profile.execute(
        "CREATE TABLE p AS SELECT 'Code' AS functional_data_type, '{}' AS frequent_values,"
        " 3 AS distinct_value_ct, 100 AS value_ct, ?::DOUBLE AS sample_ratio",
        [sample_ratio],
    )

    assert profile.execute(f"SELECT COUNT(*) FROM p WHERE {criteria}").fetchone()[0] == int(selected)


def test_a_type_declaring_nothing_keeps_its_criteria():
    query = _selection_query(None)

    assert "general_type = 'A' AND value_ct > 0" in query
    assert "sample_ratio" not in query


def test_generation_sends_no_event_of_its_own(generation_mocks):
    """A job reports from its final callback and an inline caller through the reporting wrapper,
    so a caller that is neither, such as quick-start, reports nothing."""
    run_test_generation("suite-1", ["Standard"])

    generation_mocks["mixpanel"].return_value.send_event.assert_not_called()


@pytest.mark.parametrize(("fails", "status"), [(False, JobStatus.COMPLETED), (True, JobStatus.ERROR)])
def test_an_inline_generation_reports_its_status_and_source(generation_mocks, fails, status):
    if fails:
        generation_mocks["generation"].return_value.run.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError) if fails else contextlib.nullcontext():
        run_test_generation_and_report(JobSource.ui, "suite-1", ["Standard"])

    event = generation_mocks["mixpanel"].return_value.send_event.call_args
    assert event.kwargs["status"] == status
    assert event.kwargs["source"] == "UI"


def test_an_inline_generation_refused_before_it_starts_still_reports(generation_mocks):
    """An empty set list is refused while resolving it, before any generation runs."""
    generation_mocks["resolve"].side_effect = ValueError("At least one generation set is required")

    with pytest.raises(ValueError, match="generation set"):
        run_test_generation_and_report(JobSource.ui, "suite-1", [])

    event = generation_mocks["mixpanel"].return_value.send_event.call_args
    assert event.kwargs["status"] == JobStatus.ERROR
    assert event.kwargs["generation_sets"] == []


def _settled_generation_job(status=JobStatus.COMPLETED, started=True, **kwargs):
    return MagicMock(
        source="api", status=status, started_at=datetime.now(UTC) if started else None,
        kwargs={"test_suite_id": "suite-1", "generation_sets": ["Standard"], **kwargs},
    )


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELED])
def test_a_settled_generation_job_is_reported_with_its_status(generation_mocks, status):
    report_test_generation(_settled_generation_job(status))

    event = generation_mocks["mixpanel"].return_value.send_event.call_args
    assert event.args == ("generate-tests",)
    assert event.kwargs["status"] == status
    assert event.kwargs["source"] == "API"
    generation_mocks["resolve"].assert_called_once_with(generation_mocks["suite"], ["Standard"])


def test_a_generation_job_canceled_before_it_started_is_not_reported(generation_mocks):
    """No generation ran, the same as a profiling or test run canceled before it wrote its run."""
    report_test_generation(_settled_generation_job(JobStatus.CANCELED, started=False))

    generation_mocks["mixpanel"].return_value.send_event.assert_not_called()


def test_a_generation_job_refused_for_its_sets_still_reports_them(generation_mocks):
    """Resolving fails again here for the reason the job failed; the request is what it was asked."""
    generation_mocks["resolve"].side_effect = ValueError("Unknown generation set")

    report_test_generation(_settled_generation_job(JobStatus.ERROR, generation_sets=["Nope"]))

    assert generation_mocks["mixpanel"].return_value.send_event.call_args.kwargs["generation_sets"] == ["Nope"]


def test_a_generation_whose_suite_is_gone_still_reports(generation_mocks):
    """Settling releases what held the suite in place; report what is left rather than raising."""
    with patch(f"{MODULE}.TestSuite") as suite_cls:
        suite_cls.get.return_value = None
        report_test_generation(_settled_generation_job(test_suite_id="gone", generation_sets=None))

    event = generation_mocks["mixpanel"].return_value.send_event.call_args
    assert event.kwargs["sql_flavor"] is None
    assert event.kwargs["generation_sets"] is None


def test_a_reporting_failure_does_not_stand_in_for_the_generations_outcome(generation_mocks):
    """The report reads the database, which can be what failed the generation in the first place."""
    generation_mocks["generation"].return_value.run.side_effect = RuntimeError("generation failed")

    with (
        patch(f"{MODULE}._report_test_generation", side_effect=RuntimeError("report failed")),
        pytest.raises(RuntimeError, match="generation failed"),
    ):
        run_test_generation_and_report(JobSource.ui, "suite-1", ["Standard"])


def test_a_generation_that_succeeded_is_not_turned_into_a_failure_by_its_report(generation_mocks):
    with patch(f"{MODULE}._report_test_generation", side_effect=RuntimeError("report failed")):
        run_test_generation_and_report(JobSource.ui, "suite-1", ["Standard"])
