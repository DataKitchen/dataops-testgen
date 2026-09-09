from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.ui.views.profiling_runs import on_cancel_run, on_pause_run, on_resume_run

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


@pytest.fixture
def model():
    with patch(f"{MODULE}.JobExecution") as job_execution:
        job = MagicMock()
        job_execution.get.return_value = job
        # The handlers pass the unbound method, so the class attributes have to route to the
        # instance the way the real ones do.
        for name in ("request_cancel", "request_pause", "request_resume"):
            setattr(job_execution, name, getattr(job, name))
        yield job_execution


@pytest.fixture
def job_exec(model):
    return model.get.return_value


def _message(toast):
    return toast.call_args.kwargs["str_message"]


@pytest.mark.parametrize(
    ("handler", "transition", "confirmation"),
    [
        (on_cancel_run, "request_cancel", "Cancellation requested."),
        (on_pause_run, "request_pause", "Pause requested."),
        (on_resume_run, "request_resume", "Resume requested."),
    ],
)
def test_an_accepted_action_reports_it_and_drops_the_cached_page(
    handler, transition, confirmation, job_exec, toast, cache, can_edit, db_session_mock
):
    getattr(job_exec, transition).return_value = True

    handler({"job_execution_id": str(uuid4())})

    getattr(job_exec, transition).assert_called_once_with(job_exec)
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
    handler, transition, refusal, job_exec, toast, cache, can_edit, db_session_mock
):
    """The lifecycle guard is the authority, not the button that was on screen: a run that
    finished between the render and the click has to be turned down, not acted on."""
    getattr(job_exec, transition).return_value = False

    handler({"job_execution_id": str(uuid4())})

    assert _message(toast) == f":red[{refusal}]"
    cache.clear.assert_not_called()


@pytest.mark.parametrize("handler", [on_cancel_run, on_pause_run, on_resume_run])
def test_a_payload_without_a_run_is_refused_without_a_lookup(handler, model, toast, cache, can_edit, db_session_mock):
    handler({})

    model.get.assert_not_called()
    assert _message(toast).startswith(":red[")
    cache.clear.assert_not_called()


@pytest.mark.parametrize("handler", [on_cancel_run, on_pause_run, on_resume_run])
def test_an_action_without_edit_permission_is_refused_before_the_lookup(
    handler, model, toast, cache, can_edit, db_session_mock
):
    """Hiding the control keeps it off the page; it does not stop the event from arriving, so
    the handler has to turn it down on its own."""
    can_edit.return_value = False

    handler({"job_execution_id": str(uuid4())})

    model.get.assert_not_called()
    assert _message(toast).startswith(":red[")
    cache.clear.assert_not_called()
