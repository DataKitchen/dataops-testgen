from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen.common.audit.runs import RunOperation
from testgen.ui.views.test_runs import on_cancel_run, on_delete_runs

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.test_runs"


@pytest.fixture
def toast():
    with patch(f"{MODULE}.fm") as form_service:
        yield form_service.reset_post_updates


@pytest.fixture
def can_edit():
    with patch(f"{MODULE}.session") as ui_session:
        ui_session.auth.user_has_permission.return_value = True
        yield ui_session.auth.user_has_permission


@pytest.fixture
def cache():
    with patch(f"{MODULE}.get_test_run_summaries") as summaries, patch(f"{MODULE}.get_project_summary"):
        yield summaries


def _job(job_key="run-tests", project_code="DEMO", status="running"):
    return MagicMock(id=uuid4(), job_key=job_key, project_code=project_code, status=status)


@pytest.fixture
def model():
    with patch(f"{MODULE}.JobExecution") as job_execution:
        job_execution.get.return_value = _job()
        yield job_execution


@pytest.fixture
def job_exec(model):
    return model.get.return_value


@pytest.fixture
def recorded():
    with patch("testgen.common.run_service.record_run") as record_run:
        yield record_run


def _message(toast):
    return toast.call_args.kwargs["str_message"]


def test_a_canceled_run_is_recorded(job_exec, toast, cache, can_edit, recorded, db_session_mock):
    job_exec.request_cancel.return_value = True

    on_cancel_run({"job_execution_id": str(uuid4())})

    recorded.assert_called_once_with(RunOperation.CANCELED, job_exec, job_exec.status)
    assert _message(toast) == ":green[Cancellation requested.]"
    cache.clear.assert_called_once()


def test_a_refused_cancellation_is_not_recorded(job_exec, toast, cache, can_edit, recorded, db_session_mock):
    job_exec.request_cancel.return_value = False

    on_cancel_run({"job_execution_id": str(uuid4())})

    recorded.assert_not_called()
    assert _message(toast) == ":red[This run cannot be canceled.]"


def test_a_payload_without_a_run_is_refused_without_a_lookup(model, toast, cache, can_edit, db_session_mock):
    on_cancel_run({})

    model.get.assert_not_called()
    assert _message(toast) == ":red[This run cannot be canceled.]"


def test_a_cancellation_without_edit_permission_on_the_runs_project_is_refused(
    job_exec, toast, cache, can_edit, recorded, db_session_mock
):
    job_exec.project_code = "OTHER"
    can_edit.side_effect = lambda _permission, project_code=None: project_code != "OTHER"

    on_cancel_run({"job_execution_id": str(uuid4())})

    assert can_edit.call_args == call("edit", "OTHER")
    job_exec.request_cancel.assert_not_called()
    recorded.assert_not_called()
    assert _message(toast) == ":red[This run cannot be canceled.]"


def test_canceling_a_profiling_run_is_refused(job_exec, toast, cache, can_edit, recorded, db_session_mock):
    job_exec.job_key = "run-profile"

    on_cancel_run({"job_execution_id": str(uuid4())})

    job_exec.request_cancel.assert_not_called()
    assert _message(toast) == ":red[This run cannot be canceled.]"


@pytest.fixture
def deletion():
    with (
        patch(f"{MODULE}.record_runs") as record_runs,
        patch(f"{MODULE}.select_test_runs_where") as select_runs,
        patch(f"{MODULE}.TestRun") as test_run,
        patch(f"{MODULE}.get_current_session") as current_session,
        patch(f"{MODULE}.Router"),
        patch(f"{MODULE}.st") as streamlit,
    ):
        select_runs.return_value = [MagicMock()]
        yield SimpleNamespace(
            record_runs=record_runs,
            cascade_delete=test_run.cascade_delete,
            session=current_session.return_value,
            toast=streamlit.toast,
        )


def _lookup(model, *jobs):
    by_id = {str(job.id): job for job in jobs}
    model.get.side_effect = by_id.get
    return list(by_id)


def test_deleting_runs_records_them_once_per_project_with_their_count(
    model, cache, can_edit, deletion, db_session_mock
):
    demo = [_job(status="completed") for _ in range(2)]
    other = _job(status="completed", project_code="OTHER")
    ids = _lookup(model, *demo, other)

    on_delete_runs([*ids, str(uuid4())])

    assert deletion.cascade_delete.call_count == 3
    assert deletion.record_runs.call_args_list == [
        call(RunOperation.DELETED, "run-tests", "DEMO", [str(job.id) for job in demo]),
        call(RunOperation.DELETED, "run-tests", "OTHER", [str(other.id)]),
    ]


def test_a_profiling_run_sent_for_deletion_is_left_alone(model, cache, can_edit, deletion, db_session_mock):
    test_run, profiling = _job(status="completed"), _job(job_key="run-profile", status="completed")
    ids = _lookup(model, test_run, profiling)

    on_delete_runs(ids)

    deletion.cascade_delete.assert_called_once()
    deletion.record_runs.assert_called_once_with(RunOperation.DELETED, "run-tests", "DEMO", [str(test_run.id)])


def test_runs_are_not_deleted_when_any_is_in_a_project_without_edit_permission(
    model, cache, can_edit, deletion, db_session_mock
):
    ids = _lookup(model, _job(status="completed"), _job(status="completed", project_code="OTHER"))
    can_edit.side_effect = lambda _permission, project_code=None: project_code != "OTHER"

    on_delete_runs(ids)

    deletion.cascade_delete.assert_not_called()
    deletion.record_runs.assert_not_called()
    deletion.toast.assert_called_once()


def test_a_failed_deletion_is_rolled_back_and_not_recorded(model, cache, can_edit, deletion, db_session_mock):
    deletion.cascade_delete.side_effect = RuntimeError("deadlock")

    on_delete_runs([str(model.get.return_value.id)])

    deletion.session.rollback.assert_called_once()
    deletion.record_runs.assert_not_called()
