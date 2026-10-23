import ast
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

import testgen
from testgen.common.audit.runs import RunOperation
from testgen.common.enums import JobKey, JobSource
from testgen.common.run_service import launch_run, request_run_transition

pytestmark = pytest.mark.unit

MODULE = "testgen.common.run_service"

PACKAGE_ROOT = Path(testgen.__file__).parent

RUN_JOB_KEYS = {JobKey.run_profile.value, JobKey.run_tests.value}

SUBMITS_RUNS_DIRECTLY = {
    "common/run_service.py": "launch_run itself",
    "commands/job_runner.py": "the deprecated CLI job commands, which have no signed-in user to record",
}


@patch(f"{MODULE}.record_run")
@patch(f"{MODULE}.JobExecution.submit")
def test_launching_a_run_submits_it_and_records_the_launch(mock_submit, mock_record):
    schedule_id = uuid4()

    job = launch_run(
        JobKey.run_tests, {"test_suite_id": "s1"}, JobSource.api, "DEMO",
        job_schedule_id=schedule_id, external_url="https://ci", caller_metadata={"build": 7},
    )

    mock_submit.assert_called_once_with(
        job_key=JobKey.run_tests,
        kwargs={"test_suite_id": "s1"},
        source=JobSource.api,
        project_code="DEMO",
        job_schedule_id=schedule_id,
        external_url="https://ci",
        caller_metadata={"build": 7},
    )
    assert job is mock_submit.return_value
    mock_record.assert_called_once_with(RunOperation.LAUNCHED, job)


@pytest.mark.parametrize(
    ("operation", "transition"),
    [
        (RunOperation.CANCELED, "request_cancel"),
        (RunOperation.PAUSED, "request_pause"),
        (RunOperation.RESUMED, "request_resume"),
    ],
)
@patch(f"{MODULE}.record_run")
def test_an_accepted_request_is_recorded_against_the_status_it_left(mock_record, operation, transition):
    job = MagicMock(status="running")

    def move():
        job.status = "requested"
        return True

    getattr(job, transition).side_effect = move

    assert request_run_transition(job, operation) is True

    mock_record.assert_called_once_with(operation, job, "running")


@patch(f"{MODULE}.record_run")
def test_a_refused_request_is_not_recorded(mock_record):
    job = MagicMock(status="completed")
    job.request_cancel.return_value = False

    assert request_run_transition(job, RunOperation.CANCELED) is False

    mock_record.assert_not_called()


def _submitted_job_key(call: ast.Call) -> str | None:
    """The job key a ``JobExecution.submit`` call names, or None when it is not a literal or a ``JobKey`` member."""
    node = next((keyword.value for keyword in call.keywords if keyword.arg == "job_key"), None)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "JobKey":
        return JobKey[node.attr].value
    return None


def _direct_run_submissions() -> set[str]:
    found = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "submit"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "JobExecution"
                and (_submitted_job_key(node) or next(iter(RUN_JOB_KEYS))) in RUN_JOB_KEYS
            ):
                found.add(f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}")
    return found


def test_runs_are_launched_only_through_launch_run():
    """A profiling or test run queued with ``JobExecution.submit`` directly writes no audit record of its launch.

    A call whose job key is not a literal is treated as one that may queue a run.
    """
    unexpected = {
        location for location in _direct_run_submissions()
        if location.rsplit(":", 1)[0] not in SUBMITS_RUNS_DIRECTLY
    }

    assert not unexpected, f"Queue profiling and test runs with launch_run: {sorted(unexpected)}"
