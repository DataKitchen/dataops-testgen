from datetime import datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import literal_column

from testgen.commands import run_test_execution
from testgen.common.enums import JobKey, JobSource, JobStatus
from testgen.common.job_context import JobContext, job_context, measurements_for, record_measurement
from testgen.common.models.job_execution import RESTARTED_MESSAGE

pytestmark = pytest.mark.unit


@pytest.fixture
def mocked_collaborators(monkeypatch):
    """Stub every collaborator ``run_test_execution`` touches so it runs to completion
    against a suite with no active test definitions, and hand back the pieces a test
    needs to assert on.
    """
    test_suite = MagicMock(last_complete_test_run_id=None)
    test_suite.suite_type = "standard"
    table_group = MagicMock()
    connection = MagicMock()
    session = MagicMock()
    test_run = MagicMock()

    def _stamped_test_run(**kwargs):
        # The run carries the version it was stamped with, as the real constructor leaves it:
        # the pointer and writeback gates both read it back off the run rather than off the
        # local, so a mock that left it unset would compare as a MagicMock and never match.
        test_run.version_id = kwargs.get("version_id")
        return test_run

    test_run_cls = MagicMock(side_effect=_stamped_test_run)

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
    # A standard suite's placeholder version is frozen but owned by no suite, so the default
    # here is the answer every non-contract run gets.
    monkeypatch.setattr(
        run_test_execution.SuiteVersion, "is_frozen_agreement", MagicMock(return_value=False)
    )

    return {
        "test_suite": test_suite,
        "test_run": test_run,
        "test_run_cls": test_run_cls,
        "session": session,
    }


@pytest.mark.parametrize("in_force, expect_pointer_advanced", [(True, True), (False, False)])
def test_the_pointer_advances_only_for_a_run_of_the_version_in_force_when_it_started(
    mocked_collaborators, in_force, expect_pointer_advanced
):
    test_suite = mocked_collaborators["test_suite"]
    test_run = mocked_collaborators["test_run"]
    test_run.checked_version_in_force.return_value = in_force

    run_test_execution.run_test_execution(uuid4())

    if expect_pointer_advanced:
        assert test_suite.last_complete_test_run_id is test_run.id
    else:
        assert test_suite.last_complete_test_run_id is None



@pytest.mark.parametrize(
    "latest_start, expect_pointer_advanced",
    [(datetime(2026, 10, 1, 10, 6), False), (datetime(2026, 10, 1, 9, 55), True)],
    ids=["a-later-run-is-latest", "an-earlier-run-is-latest"],
)
def test_a_contract_run_that_finishes_last_does_not_displace_a_run_that_started_after_it(
    monkeypatch, mocked_collaborators, latest_start, expect_pointer_advanced
):
    # A run of a superseded version can overlap the first run of the version frozen after it.
    monkeypatch.setattr(run_test_execution, "select", MagicMock())
    test_suite = mocked_collaborators["test_suite"]
    test_suite.suite_type = "contract"
    previous_run_id = uuid4()
    test_suite.last_complete_test_run_id = previous_run_id
    test_run = mocked_collaborators["test_run"]
    test_run.checked_version_in_force.return_value = True
    test_run.test_starttime = datetime(2026, 10, 1, 10, 0)
    mocked_collaborators["session"].scalar.return_value = latest_start

    run_test_execution.run_test_execution(uuid4(), version_id=uuid4())

    expected = test_run.id if expect_pointer_advanced else previous_run_id
    assert test_suite.last_complete_test_run_id is expected

def test_a_run_with_no_version_id_is_stamped_through_for_run_not_resolved_for(monkeypatch, mocked_collaborators):
    """``for_run`` prefers the frozen version over the draft; ``resolved_for`` prefers the
    draft, and stamping through it would make every run of a contract a run of its draft.
    """
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


@pytest.mark.parametrize(
    "is_frozen_agreement, expect_writeback",
    [(True, False), (False, True)],
)
def test_a_run_of_a_frozen_agreement_rewrites_none_of_its_terms(
    monkeypatch, mocked_collaborators, is_frozen_agreement, expect_writeback
):
    """Both writeback steps bind the run's version, which for a contract is the frozen
    agreement. Rewriting tolerances or predictions there means the terms in force are no
    longer the terms that were frozen, and re-running the version stops being reproducible.
    """
    monkeypatch.setattr(
        run_test_execution.SuiteVersion,
        "is_frozen_agreement",
        MagicMock(return_value=is_frozen_agreement),
    )
    prediction = MagicMock()
    monkeypatch.setattr(run_test_execution, "TestThresholdsPrediction", prediction)
    sql_generator = run_test_execution.TestExecutionSQL.return_value

    run_test_execution.run_test_execution(uuid4())

    assert sql_generator.update_history_calc_thresholds.called is expect_writeback
    assert prediction.called is expect_writeback


def test_the_writeback_gate_asks_about_the_runs_own_version(monkeypatch, mocked_collaborators):
    # Asking about the suite instead would gate a draft preview the same way as the frozen
    # agreement, and a preview's terms are exactly the ones that should still be refreshed.
    is_frozen = MagicMock(return_value=False)
    monkeypatch.setattr(run_test_execution.SuiteVersion, "is_frozen_agreement", is_frozen)
    test_run = mocked_collaborators["test_run"]

    run_test_execution.run_test_execution(uuid4())

    assert is_frozen.call_args.args[0] == test_run.version_id


def test_a_run_that_fails_early_still_attempts_its_prediction(monkeypatch, mocked_collaborators):
    """The prediction runs from a ``finally`` so that a failed run still gets one. Deciding the
    writeback gate inside the ``try`` would leave the name unbound for exactly those runs, and
    the ``UnboundLocalError`` would be swallowed and logged as a prediction failure.
    """
    monkeypatch.setattr(
        run_test_execution, "run_data_chars_refresh", MagicMock(side_effect=RuntimeError("target is down"))
    )
    prediction = MagicMock()
    monkeypatch.setattr(run_test_execution, "TestThresholdsPrediction", prediction)

    with pytest.raises(RuntimeError, match="target is down"):
        run_test_execution.run_test_execution(uuid4())

    prediction.assert_called_once()


def test_a_run_opens_its_own_database_session(monkeypatch, mocked_collaborators):
    # Quick start calls the run outside any session
    database_session = MagicMock()
    monkeypatch.setattr("testgen.common.models.database_session", database_session)

    run_test_execution.run_test_execution(uuid4())

    database_session.return_value.__enter__.assert_called_once()


@pytest.fixture
def running_as_job():
    job_id = uuid4()
    token = job_context.set(JobContext(job_id=job_id, source=JobSource.scheduler))
    yield job_id
    job_context.reset(token)


def test_a_run_leaves_its_telemetry_to_the_final_callback(mocked_collaborators, monkeypatch):
    """Sent from the run, a run that is canceled or killed would never report."""
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)

    run_test_execution.run_test_execution(uuid4())

    mixpanel.return_value.send_event.assert_not_called()


def test_a_run_keeps_its_prediction_time_for_the_final_callback(mocked_collaborators, running_as_job):
    run_test_execution.run_test_execution(uuid4())

    assert "prediction_duration" in measurements_for(running_as_job)


def _settled_job(job_id, status=JobStatus.COMPLETED, job_key=JobKey.run_tests, error_message=None):
    return MagicMock(
        id=job_id, job_key=job_key, source="scheduler", status=status, active_seconds=12.5, kwargs={},
        error_message=error_message,
    )


@pytest.mark.parametrize("status", [JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELED])
def test_a_settled_run_is_reported_with_its_status(mocked_collaborators, monkeypatch, status):
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)
    mocked_collaborators["test_run_cls"].get.return_value = MagicMock(test_ct=7)

    run_test_execution.report_test_run(_settled_job(uuid4(), status=status))

    event = mixpanel.return_value.send_event.call_args
    assert event.args == ("run-tests",)
    assert event.kwargs["status"] == status
    assert event.kwargs["test_count"] == 7
    assert event.kwargs["run_duration"] == 12.5


def test_a_run_is_reported_with_its_suite_type(mocked_collaborators, monkeypatch):
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)
    mocked_collaborators["test_suite"].suite_type = "contract"

    run_test_execution.report_test_run(_settled_job(uuid4()))

    assert mixpanel.return_value.send_event.call_args.kwargs["suite_type"] == "contract"


def test_a_monitor_run_is_reported_as_one(mocked_collaborators, monkeypatch):
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)

    run_test_execution.report_test_run(_settled_job(uuid4(), job_key=JobKey.run_monitors))

    assert mixpanel.return_value.send_event.call_args.args == ("run-monitors",)


def test_the_prediction_time_is_reported_by_the_process_that_measured_it(
    mocked_collaborators, monkeypatch, running_as_job,
):
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)
    record_measurement("prediction_duration", 1.5)

    run_test_execution.report_test_run(_settled_job(running_as_job))
    assert mixpanel.return_value.send_event.call_args.kwargs["prediction_duration"] == 1.5

    run_test_execution.report_test_run(_settled_job(uuid4()))
    assert "prediction_duration" not in mixpanel.return_value.send_event.call_args.kwargs


def test_a_run_with_no_run_row_is_not_reported(mocked_collaborators, monkeypatch):
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)
    mocked_collaborators["test_run_cls"].get.return_value = None

    run_test_execution.report_test_run(_settled_job(uuid4()))

    mixpanel.return_value.send_event.assert_not_called()


def test_a_run_a_restart_ended_reports_no_duration(mocked_collaborators, monkeypatch):
    """Its worked time runs up to the restart, downtime included."""
    mixpanel = MagicMock()
    monkeypatch.setattr(run_test_execution, "MixpanelService", mixpanel)

    run_test_execution.report_test_run(_settled_job(uuid4(), JobStatus.ERROR, error_message=RESTARTED_MESSAGE))

    event = mixpanel.return_value.send_event.call_args.kwargs
    assert event["status"] == JobStatus.ERROR
    assert "run_duration" not in event


@pytest.mark.parametrize(
    "override",
    [
        {"match_schema_name": "build_123"},
        {"schema_name": "build_123"},
        {"table_names": {"orders": "build_orders"}},
        {"match_table_names": {"orders": "build_orders"}},
        {"variables": {"END_DATE": "2026-01-01"}},
    ],
    ids=lambda o: next(iter(o)),
)
def test_an_overridden_run_still_refreshes_its_thresholds(monkeypatch, mocked_collaborators, override):
    """Both writeback steps read the history the suite has already recorded, which an override
    does not change. Holding them back leaves every test of the suite on the thresholds of
    whenever a run last went without one, and a prediction that never leaves training."""
    prediction = MagicMock()
    monkeypatch.setattr(run_test_execution, "TestThresholdsPrediction", prediction)
    sql_generator = run_test_execution.TestExecutionSQL.return_value

    run_test_execution.run_test_execution(uuid4(), **override)

    assert sql_generator.update_history_calc_thresholds.called
    assert prediction.called
