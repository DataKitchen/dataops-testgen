from datetime import UTC, datetime
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.test_run import TestRunSummary
from testgen.ui.services.contract_summary_service import contract_summary

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 8, 1, tzinfo=UTC)
STARTED = datetime(2026, 8, 16, 14, 2, tzinfo=UTC)
NOT_FROZEN_YET = "Not frozen yet. Runs of the draft are previews."


def _version(number: int, frozen: bool) -> SuiteVersion:
    return SuiteVersion(id=uuid4(), version=number, frozen_at=FROZEN if frozen else None)


def _run(status: JobStatus = JobStatus.COMPLETED) -> TestRunSummary:
    return TestRunSummary(
        job_execution_id=uuid4(), test_run_id=uuid4(), job_schedule_id=None, status=status,
        created_at=STARTED, started_at=STARTED, completed_at=STARTED, active_seconds=60.0, error_message=None,
        progress=[], table_groups_name="sales_tables", test_suite="orders_contract", project_code="demo",
        project_name="Demo", test_ct=142, passed_ct=130, warning_ct=4, failed_ct=6, error_ct=1, log_ct=1,
        dismissed_ct=0, dq_score_testing=None, version_number=3, version_frozen_at=FROZEN,
        active_version_number=3, test_starttime=STARTED.replace(tzinfo=None),
    )


SUPERSEDED, ACTIVE, DRAFT = _version(2, True), _version(3, True), _version(4, False)
WITH_DRAFT = [SUPERSEDED, ACTIVE, DRAFT]
FROZEN_ONLY = [SUPERSEDED, ACTIVE]
DRAFT_ONLY = [_version(1, False)]


def _actions(summary: dict) -> set[str]:
    return {name for name, shown in summary["actions"].items() if shown}


def test_lists_versions_newest_first_named_by_state():
    summary = contract_summary(WITH_DRAFT, None, can_edit=True, verification=None)
    assert summary["versions"] == [
        {"value": 4, "label": "v4 draft"},
        {"value": 3, "label": "v3 active"},
        {"value": 2, "label": "v2 superseded"},
    ]


@pytest.mark.parametrize(
    ("versions", "expected"),
    [(WITH_DRAFT, 4), (FROZEN_ONLY, 3), (DRAFT_ONLY, 1)],
    ids=["draft", "frozen-only", "draft-only"],
)
def test_opens_on_the_editable_version(versions, expected):
    assert contract_summary(versions, None, can_edit=True, verification=None)["selected_version"] == expected


def test_an_unknown_version_falls_back_to_the_editable_one():
    assert contract_summary(WITH_DRAFT, 9, can_edit=True, verification=None)["selected_version"] == 4


@pytest.mark.parametrize(
    ("versions", "expected"),
    [(WITH_DRAFT, "v3 active · v4 draft"), (FROZEN_ONLY, "v3 active"), (DRAFT_ONLY, "v1 draft")],
    ids=["draft", "frozen-only", "draft-only"],
)
def test_state_names_the_active_version_and_the_draft(versions, expected):
    assert contract_summary(versions, None, can_edit=True, verification=None)["state"] == expected


def test_editing_the_active_version_says_it_creates_the_next_draft():
    summary = contract_summary(FROZEN_ONLY, 3, can_edit=True, verification=None)
    assert summary["caption"] == "Editing creates draft v4."
    assert summary["caption_link"] is None


def test_the_draft_carries_no_caption():
    summary = contract_summary(WITH_DRAFT, 4, can_edit=True, verification=None)
    assert summary["caption"] is None
    assert summary["caption_link"] is None


def test_a_read_only_user_is_not_told_about_editing():
    summary = contract_summary(FROZEN_ONLY, 3, can_edit=False, verification=None)
    assert summary["caption"] is None


def test_viewing_the_active_version_beside_a_draft_links_back_to_the_draft():
    summary = contract_summary(WITH_DRAFT, 3, can_edit=True, verification=None)
    assert summary["caption"] == "Viewing v3, the active version. Edits go to the draft."
    assert summary["caption_link"] == {"label": "Go to v4 draft", "version": 4}


def test_viewing_a_superseded_version_beside_a_draft_links_back_to_the_draft():
    summary = contract_summary(WITH_DRAFT, 2, can_edit=True, verification=None)
    assert summary["caption"] == "Viewing v2, a superseded version. Edits go to the draft."
    assert summary["caption_link"] == {"label": "Go to v4 draft", "version": 4}


def test_viewing_a_superseded_version_without_a_draft_links_to_the_active_version():
    summary = contract_summary(FROZEN_ONLY, 2, can_edit=True, verification=None)
    assert summary["caption"] == "Viewing v2, a superseded version. v3 is the active version."
    assert summary["caption_link"] == {"label": "Go to v3 active", "version": 3}


def test_a_read_only_user_viewing_an_older_version_still_gets_the_link():
    summary = contract_summary(WITH_DRAFT, 3, can_edit=False, verification=None)
    assert summary["caption"] == "Viewing v3, the active version."
    assert summary["caption_link"] == {"label": "Go to v4 draft", "version": 4}


def test_the_draft_offers_freeze_and_discard():
    summary = contract_summary(WITH_DRAFT, 4, can_edit=True, verification=None)
    assert _actions(summary) == {"history", "export", "import", "discard", "freeze"}
    assert summary["draft_version"] == 4


def test_a_draft_with_nothing_frozen_offers_no_discard():
    summary = contract_summary(DRAFT_ONLY, 1, can_edit=True, verification=None)
    assert _actions(summary) == {"history", "export", "import", "freeze"}


def test_the_editable_active_version_offers_import_only():
    summary = contract_summary(FROZEN_ONLY, 3, can_edit=True, verification=None)
    assert _actions(summary) == {"history", "export", "import"}
    assert summary["draft_version"] is None


@pytest.mark.parametrize("selected", [3, 2], ids=["active", "superseded"])
def test_a_version_beside_the_draft_offers_no_editing_action(selected):
    summary = contract_summary(WITH_DRAFT, selected, can_edit=True, verification=None)
    assert _actions(summary) == {"history", "export"}


@pytest.mark.parametrize(("versions", "selected"), [(WITH_DRAFT, 4), (FROZEN_ONLY, 3), (DRAFT_ONLY, 1)])
def test_a_read_only_user_gets_history_and_export_only(versions, selected):
    summary = contract_summary(versions, selected, can_edit=False, verification=None)
    assert _actions(summary) == {"history", "export"}


def test_nothing_frozen_reports_that_runs_are_previews():
    summary = contract_summary(DRAFT_ONLY, None, can_edit=True, verification=None)
    assert summary["verification"] is None
    assert summary["verification_message"] == NOT_FROZEN_YET


def test_an_active_version_that_has_not_run_says_so():
    summary = contract_summary(WITH_DRAFT, None, can_edit=True, verification=None)
    assert summary["verification"] is None
    assert summary["verification_message"] == "v3 has not run since it was frozen."


@pytest.mark.parametrize(
    ("status", "label"),
    [(JobStatus.RUNNING, "Running"), (JobStatus.ERROR, "Error"), (JobStatus.CANCELED, "Canceled")],
)
def test_an_active_version_whose_only_run_is_incomplete_names_its_status(status, label):
    summary = contract_summary(WITH_DRAFT, None, can_edit=True, verification=None, incomplete_run=_run(status))
    assert summary["verification"] is None
    assert summary["verification_message"] == f"v3 has no completed run since it was frozen. Latest run: {label}."


def test_a_newer_incomplete_run_leaves_the_latest_verification_shown():
    run = _run()
    summary = contract_summary(
        WITH_DRAFT, None, can_edit=True, verification=run, incomplete_run=_run(JobStatus.RUNNING)
    )
    assert summary["verification_message"] is None
    assert summary["verification"]["run_id"] == str(run.job_execution_id)


def test_the_latest_verification_carries_its_counts():
    run = _run()
    summary = contract_summary(WITH_DRAFT, 2, can_edit=True, verification=run)
    assert summary["verification_message"] is None
    assert summary["verification"] == {
        "version": "v3",
        "run_id": str(run.job_execution_id),
        "started_at": int(STARTED.timestamp() * 1000),
        "passed_ct": 130,
        "warning_ct": 4,
        "failed_ct": 6,
        "error_ct": 1,
        "log_ct": 1,
        "dismissed_ct": 0,
    }
