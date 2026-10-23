from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from testgen.common.audit.runs import RunOperation
from testgen.ui.views.profiling_runs import on_cancel_run, on_delete_runs, on_pause_run, on_resume_run

pytestmark = pytest.mark.unit

MODULE = "testgen.ui.views.profiling_runs"


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
    with patch(f"{MODULE}.get_profiling_run_summaries") as summaries:
        yield summaries


def _job(job_key="run-profile", project_code="DEMO", status="running"):
    return MagicMock(id=uuid4(), job_key=job_key, project_code=project_code, status=status)


@pytest.fixture
def model():
    with patch(f"{MODULE}.JobExecution") as job_execution:
        job_execution.get.return_value = _job()
        yield job_execution


@pytest.fixture
def recorded():
    with patch("testgen.common.run_service.record_run") as record_run:
        yield record_run


@pytest.fixture
def job_exec(model):
    return model.get.return_value


def _message(toast):
    return toast.call_args.kwargs["str_message"]


@pytest.mark.parametrize(
    ("handler", "transition", "operation", "confirmation"),
    [
        (on_cancel_run, "request_cancel", RunOperation.CANCELED, "Cancellation requested."),
        (on_pause_run, "request_pause", RunOperation.PAUSED, "Pause requested."),
        (on_resume_run, "request_resume", RunOperation.RESUMED, "Resume requested."),
    ],
)
def test_an_accepted_action_reports_it_and_drops_the_cached_page(
    handler, transition, operation, confirmation, job_exec, toast, cache, can_edit, recorded, db_session_mock
):
    getattr(job_exec, transition).return_value = True

    handler({"job_execution_id": str(uuid4())})

    getattr(job_exec, transition).assert_called_once_with()
    recorded.assert_called_once_with(operation, job_exec, job_exec.status)
    assert _message(toast) == f":green[{confirmation}]"
    cache.clear.assert_called_once()


@pytest.mark.parametrize(
    ("handler", "transition", "refusal"),
    [
        (on_cancel_run, "request_cancel", "This run cannot be canceled."),
        (on_pause_run, "request_pause", "This run cannot be paused."),
        (on_resume_run, "request_resume", "This run cannot be resumed."),
    ],
)
def test_a_refused_action_says_so_and_leaves_the_page_alone(
    handler, transition, refusal, job_exec, toast, cache, can_edit, recorded, db_session_mock
):
    """The lifecycle guard is the authority, not the button that was on screen: a run that
    finished between the render and the click has to be turned down, not acted on."""
    getattr(job_exec, transition).return_value = False

    handler({"job_execution_id": str(uuid4())})

    assert _message(toast) == f":red[{refusal}]"
    cache.clear.assert_not_called()
    recorded.assert_not_called()


@pytest.mark.parametrize("handler", [on_cancel_run, on_pause_run, on_resume_run])
def test_a_payload_without_a_run_is_refused_without_a_lookup(handler, model, toast, cache, can_edit, db_session_mock):
    handler({})

    model.get.assert_not_called()
    assert _message(toast).startswith(":red[")
    cache.clear.assert_not_called()


@pytest.mark.parametrize(
    ("handler", "transition"),
    [(on_cancel_run, "request_cancel"), (on_pause_run, "request_pause"), (on_resume_run, "request_resume")],
)
def test_an_action_without_edit_permission_on_the_runs_project_is_refused(
    handler, transition, job_exec, toast, cache, can_edit, recorded, db_session_mock
):
    """Hiding the control keeps it off the page; it does not stop the event from arriving, nor
    keep it from naming a run of another project, so the handler checks the run's own project."""
    job_exec.project_code = "OTHER"
    can_edit.side_effect = lambda _permission, project_code=None: project_code != "OTHER"

    handler({"job_execution_id": str(uuid4())})

    assert can_edit.call_args == call("edit", "OTHER")
    getattr(job_exec, transition).assert_not_called()
    recorded.assert_not_called()
    assert _message(toast).startswith(":red[")
    cache.clear.assert_not_called()


@pytest.mark.parametrize("handler", [on_cancel_run, on_pause_run, on_resume_run])
def test_an_action_on_a_test_run_is_refused(handler, job_exec, toast, cache, can_edit, recorded, db_session_mock):
    job_exec.job_key = "run-tests"

    handler({"job_execution_id": str(uuid4())})

    job_exec.request_cancel.assert_not_called()
    recorded.assert_not_called()
    assert _message(toast).startswith(":red[")


@pytest.fixture
def deletion():
    with (
        patch(f"{MODULE}.record_runs") as record_runs,
        patch(f"{MODULE}.select_profiling_runs_where") as select_runs,
        patch(f"{MODULE}.ProfilingRun") as profiling_run,
        patch(f"{MODULE}.get_current_session") as current_session,
        patch(f"{MODULE}.get_project_summary"),
        patch(f"{MODULE}.Router"),
        patch(f"{MODULE}.st") as streamlit,
    ):
        select_runs.return_value = [MagicMock()]
        yield SimpleNamespace(
            record_runs=record_runs,
            cascade_delete=profiling_run.cascade_delete,
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
    demo = [_job(status="completed") for _ in range(3)]
    other = _job(status="completed", project_code="OTHER")
    ids = _lookup(model, *demo, other)

    on_delete_runs([*ids, str(uuid4())])

    assert deletion.cascade_delete.call_count == 4
    assert deletion.record_runs.call_args_list == [
        call(RunOperation.DELETED, "run-profile", "DEMO", [str(job.id) for job in demo]),
        call(RunOperation.DELETED, "run-profile", "OTHER", [str(other.id)]),
    ]


def test_a_test_run_sent_for_deletion_is_left_alone(model, cache, can_edit, deletion, db_session_mock):
    profiling, test_run = _job(status="completed"), _job(job_key="run-tests", status="completed")
    ids = _lookup(model, profiling, test_run)

    on_delete_runs(ids)

    deletion.cascade_delete.assert_called_once()
    deletion.record_runs.assert_called_once_with(RunOperation.DELETED, "run-profile", "DEMO", [str(profiling.id)])


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
