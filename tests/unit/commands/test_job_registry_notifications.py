from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands import job_registry

pytestmark = pytest.mark.unit


def _job_exec():
    job = MagicMock()
    job.id = uuid4()
    return job


def _run_with(in_force):
    run = MagicMock()
    run.checked_version_in_force.return_value = in_force
    return run


@pytest.mark.parametrize("in_force, sends", [(False, False), (True, True)])
def test_only_a_run_of_the_version_in_force_notifies(in_force, sends):
    with (
        patch.object(job_registry, "database_session"),
        patch.object(job_registry, "select"),
        patch.object(job_registry, "send_test_run_notifications") as send,
    ):
        session = job_registry.database_session.return_value.__enter__.return_value
        session.scalars.return_value.first.return_value = _run_with(in_force)
        job_registry._notify_test_run(_job_exec())

    assert send.called is sends


@pytest.mark.parametrize("in_force, rolls_up", [(False, False), (True, True)])
def test_only_a_run_of_the_version_in_force_rolls_up_scores(in_force, rolls_up):
    # A score refresh writes a score-history entry per definition per category, timestamped at the run,
    # and runs the score-drop notification path -- neither of which a run of a version not in force
    # should cause.
    job = _job_exec()
    job.status = job_registry.JobStatus.COMPLETED
    job.job_key = job_registry.JobKey.run_tests
    with (
        patch.object(job_registry, "database_session"),
        patch.object(job_registry, "select"),
        patch.object(job_registry, "rollup_run_and_request_refresh") as rollup,
    ):
        session = job_registry.database_session.return_value.__enter__.return_value
        session.scalars.return_value.first.return_value = _run_with(in_force)
        job_registry._rollup_scores(job)

    assert rollup.called is rolls_up


def test_a_completed_profiling_run_still_rolls_up_scores():
    # Only a test run carries a version; the version gate must not reach for one on a profiling run.
    job = _job_exec()
    job.status = job_registry.JobStatus.COMPLETED
    job.job_key = job_registry.JobKey.run_profile
    with (
        patch.object(job_registry, "database_session") as database_session,
        patch.object(job_registry, "rollup_run_and_request_refresh") as rollup,
    ):
        job_registry._rollup_scores(job)

    database_session.assert_not_called()
    rollup.assert_called_once_with(parent_job_id=str(job.id), parent_job_key=job_registry.JobKey.run_profile)
