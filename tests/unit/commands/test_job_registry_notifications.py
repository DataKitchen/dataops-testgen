from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands import job_registry

pytestmark = pytest.mark.unit


def _job_exec():
    job = MagicMock()
    job.id = uuid4()
    return job


def _run_with(version_id):
    run = MagicMock()
    run.version_id = version_id
    return run


@pytest.mark.parametrize("is_draft, sends", [(True, False), (False, True)])
def test_a_draft_run_notifies_nobody_and_a_frozen_one_notifies(is_draft, sends):
    run = _run_with(uuid4())
    with (
        patch.object(job_registry, "database_session"),
        patch.object(job_registry, "select"),
        patch.object(job_registry.SuiteVersion, "is_draft", return_value=is_draft),
        patch.object(job_registry, "send_test_run_notifications") as send,
    ):
        session = job_registry.database_session.return_value.__enter__.return_value
        session.scalars.return_value.first.return_value = run
        job_registry._notify_test_run(_job_exec())

    assert send.called is sends


def test_a_run_with_no_version_still_notifies():
    run = _run_with(None)
    with (
        patch.object(job_registry, "database_session"),
        patch.object(job_registry, "select"),
        patch.object(job_registry, "send_test_run_notifications") as send,
    ):
        session = job_registry.database_session.return_value.__enter__.return_value
        session.scalars.return_value.first.return_value = run
        job_registry._notify_test_run(_job_exec())

    assert send.called
