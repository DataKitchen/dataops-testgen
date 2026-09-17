from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal_column

from testgen.commands import run_test_execution

pytestmark = pytest.mark.unit


@pytest.fixture
def mocked_collaborators(monkeypatch):
    """Stub every collaborator ``run_test_execution`` touches so it runs to completion
    against a suite with no active test definitions, and hand back the pieces a test
    needs to assert on.
    """
    test_suite = MagicMock(last_complete_test_run_id=None)
    test_suite.suite_type = "regular"
    table_group = MagicMock()
    connection = MagicMock()
    session = MagicMock()
    test_run = MagicMock()
    test_run_cls = MagicMock(return_value=test_run)

    sql_generator = MagicMock()
    sql_generator.get_active_test_definitions.return_value = ()

    monkeypatch.setattr(run_test_execution.TestSuite, "get", MagicMock(return_value=test_suite))
    monkeypatch.setattr(run_test_execution.TableGroup, "get", MagicMock(return_value=table_group))
    monkeypatch.setattr(run_test_execution.Connection, "get", MagicMock(return_value=connection))
    monkeypatch.setattr(run_test_execution, "set_target_db_params", MagicMock())
    monkeypatch.setattr(run_test_execution, "run_data_chars_refresh", MagicMock(return_value=[]))
    monkeypatch.setattr(run_test_execution, "TestExecutionSQL", MagicMock(return_value=sql_generator))
    monkeypatch.setattr(run_test_execution, "execute_db_queries", MagicMock())
    monkeypatch.setattr(run_test_execution, "fetch_dict_from_db", MagicMock(return_value=[]))
    monkeypatch.setattr(run_test_execution, "get_current_session", MagicMock(return_value=session))
    monkeypatch.setattr(run_test_execution, "TestThresholdsPrediction", MagicMock())
    monkeypatch.setattr(run_test_execution, "MixpanelService", MagicMock())
    monkeypatch.setattr(run_test_execution, "TestRun", test_run_cls)

    return {
        "test_suite": test_suite,
        "test_run": test_run,
        "test_run_cls": test_run_cls,
        "session": session,
    }


@pytest.mark.parametrize("is_active, expect_pointer_advanced", [(True, True), (False, False)])
def test_the_pointer_advances_only_for_the_active_version(
    monkeypatch, mocked_collaborators, is_active, expect_pointer_advanced
):
    monkeypatch.setattr(run_test_execution.SuiteVersion, "is_active", MagicMock(return_value=is_active))
    test_suite = mocked_collaborators["test_suite"]
    test_run = mocked_collaborators["test_run"]

    run_test_execution.run_test_execution(uuid4())

    if expect_pointer_advanced:
        assert test_suite.last_complete_test_run_id is test_run.id
    else:
        assert test_suite.last_complete_test_run_id is None


def test_a_run_with_no_version_id_is_stamped_through_for_run_not_resolved_for(monkeypatch, mocked_collaborators):
    """``for_run`` prefers the frozen version over the draft; ``resolved_for`` prefers the
    draft, and stamping through it would make every run of a contract a run of its draft.
    """
    monkeypatch.setattr(run_test_execution.SuiteVersion, "is_active", MagicMock(return_value=True))
    for_run = MagicMock(wraps=run_test_execution.SuiteVersion.for_run)
    resolved_for = MagicMock(wraps=run_test_execution.SuiteVersion.resolved_for)
    monkeypatch.setattr(run_test_execution.SuiteVersion, "for_run", for_run)
    monkeypatch.setattr(run_test_execution.SuiteVersion, "resolved_for", resolved_for)
    session = mocked_collaborators["session"]
    active_version_id = uuid4()
    session.scalar.return_value = active_version_id
    test_suite_id = uuid4()

    run_test_execution.run_test_execution(test_suite_id)

    for_run.assert_called_once_with(test_suite_id)
    resolved_for.assert_not_called()
    test_run_cls = mocked_collaborators["test_run_cls"]
    assert test_run_cls.call_args.kwargs["version_id"] == active_version_id


def test_a_given_version_id_is_stamped_as_is_without_resolving_the_active_version(monkeypatch, mocked_collaborators):
    monkeypatch.setattr(run_test_execution.SuiteVersion, "is_active", MagicMock(return_value=True))
    for_run = MagicMock(wraps=run_test_execution.SuiteVersion.for_run)
    monkeypatch.setattr(run_test_execution.SuiteVersion, "for_run", for_run)
    given_version_id = uuid4()

    run_test_execution.run_test_execution(uuid4(), version_id=given_version_id)

    for_run.assert_not_called()
    test_run_cls = mocked_collaborators["test_run_cls"]
    assert test_run_cls.call_args.kwargs["version_id"] == given_version_id


PLACEHOLDER_VERSION_ID = UUID("00000000-0000-0000-0000-000000000000")


def test_a_contract_with_no_frozen_version_stamps_its_run_with_the_draft(monkeypatch, mocked_collaborators):
    """A contract holding only a draft has no agreement in force, and ``active_for`` coalesces
    down to the placeholder for it. Stamping that placeholder executes none of the draft's
    terms and still reads as an official run -- advancing the last-run pointer, notifying
    every subscriber and taking the suite's score. Such a run is a preview of the draft, so
    the draft is what it is stamped with.
    """
    draft_version_id = uuid4()
    monkeypatch.setattr(
        run_test_execution.SuiteVersion, "active_for",
        MagicMock(return_value=literal_column("'ACTIVE'")), raising=False,
    )
    monkeypatch.setattr(
        run_test_execution.SuiteVersion, "for_run",
        MagicMock(return_value=literal_column("'FOR_RUN'")), raising=False,
    )
    session = mocked_collaborators["session"]
    session.scalar.side_effect = lambda statement: (
        PLACEHOLDER_VERSION_ID if "ACTIVE" in str(statement) else draft_version_id
    )
    monkeypatch.setattr(
        "testgen.common.models.suite_version.get_current_session",
        MagicMock(return_value=MagicMock(**{"scalar.return_value": PLACEHOLDER_VERSION_ID})),
    )
    mocked_collaborators["test_suite"].suite_type = "contract"

    run_test_execution.run_test_execution(uuid4())

    stamped = mocked_collaborators["test_run_cls"].call_args.kwargs["version_id"]
    assert stamped == draft_version_id
