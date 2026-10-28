from types import SimpleNamespace
from uuid import uuid4

import pytest

from testgen.common.audit import recorder
from testgen.common.audit.record import Actor
from testgen.common.audit.recorder import AuditContext, bind
from testgen.common.audit.runs import RunOperation, record_run, record_runs
from testgen.common.enums import JobKey, JobSource, PublicJobKey

pytestmark = pytest.mark.unit

STARTED_BY_USERS_BUT_NOT_RUNS = {
    PublicJobKey.run_test_generation: "writes tests rather than producing a run",
}


@pytest.fixture(autouse=True)
def no_resolver(monkeypatch):
    monkeypatch.setattr(recorder, "_context_resolver", None)


def _job(job_key=JobKey.run_profile, project_code="DEMO", status="running"):
    return SimpleNamespace(id=uuid4(), job_key=job_key, project_code=project_code, status=status)


@pytest.mark.parametrize(
    ("job_key", "operation", "action", "target_type"),
    [
        (JobKey.run_profile, RunOperation.LAUNCHED, "profiling_run.launched", "profiling_run"),
        (JobKey.run_profile, RunOperation.PAUSED, "profiling_run.paused", "profiling_run"),
        (JobKey.run_profile, RunOperation.RESUMED, "profiling_run.resumed", "profiling_run"),
        (JobKey.run_profile, RunOperation.CANCELED, "profiling_run.canceled", "profiling_run"),
        (JobKey.run_tests, RunOperation.LAUNCHED, "test_run.launched", "test_run"),
        (JobKey.run_tests, RunOperation.CANCELED, "test_run.canceled", "test_run"),
    ],
)
def test_a_run_operation_records_the_run(job_key, operation, action, target_type, audit_session, audit_log):
    user = SimpleNamespace(id=uuid4(), username="alice", name="Alice A.")
    bind(AuditContext(source=JobSource.ui, actor=Actor.of(user)))
    job = _job(job_key)

    record_run(operation, job)
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["action"] == action
    assert entry["target_type"] == target_type
    assert (entry["targets"], entry["target_count"], entry["target_name"]) == ([str(job.id)], 1, None)
    assert entry["project_code"] == "DEMO"
    assert (entry["source"], entry["actor_id"]) == ("ui", str(user.id))
    assert entry["changes"] == {}


@pytest.mark.parametrize(
    ("job_key", "operation"),
    [
        (JobKey.run_tests, RunOperation.PAUSED),
        (JobKey.run_tests, RunOperation.RESUMED),
        (JobKey.run_test_generation, RunOperation.CANCELED),
        (JobKey.run_monitors, RunOperation.LAUNCHED),
        (JobKey.run_data_cleanup, RunOperation.LAUNCHED),
    ],
)
def test_a_job_that_is_not_a_profiling_or_test_run_records_nothing(job_key, operation, audit_session, audit_log):
    record_run(operation, _job(job_key))
    audit_session.commit()

    assert audit_log.records() == []


def test_a_request_that_moved_the_run_is_recorded(audit_session, audit_log):
    record_run(RunOperation.CANCELED, _job(status="cancel_requested"), previous_status="running")
    audit_session.commit()

    assert [entry["action"] for entry in audit_log.records()] == ["profiling_run.canceled"]


def test_a_repeated_request_that_left_the_run_where_it_was_records_nothing(audit_session, audit_log):
    record_run(RunOperation.CANCELED, _job(status="cancel_requested"), previous_status="cancel_requested")
    audit_session.commit()

    assert audit_log.records() == []


@pytest.mark.parametrize(
    ("job_key", "action"),
    [(JobKey.run_profile, "profiling_run.deleted"), (JobKey.run_tests, "test_run.deleted")],
)
def test_deleting_runs_records_one_entry_with_their_count(job_key, action, audit_session, audit_log):
    run_ids = [uuid4() for _ in range(3)]

    record_runs(RunOperation.DELETED, job_key, "DEMO", run_ids)
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["action"] == action
    assert entry["target_count"] == 3
    assert entry["targets"] == [str(run_id) for run_id in run_ids]


def test_deleting_no_runs_records_nothing(audit_session, audit_log):
    record_runs(RunOperation.DELETED, JobKey.run_profile, "DEMO", [])
    audit_session.commit()

    assert audit_log.records() == []


@pytest.mark.parametrize("operation", [RunOperation.LAUNCHED, RunOperation.CANCELED])
@pytest.mark.parametrize("job_key", [key for key in PublicJobKey if key not in STARTED_BY_USERS_BUT_NOT_RUNS])
def test_every_kind_of_run_users_can_start_records_its_launch_and_cancel(job_key, operation, audit_session, audit_log):
    """Runs are audited when users can start them. A run kind made startable by users needs actions of its own."""
    record_run(operation, _job(job_key))
    audit_session.commit()

    [entry] = audit_log.records()
    assert entry["action"].endswith(f".{operation}")
