from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.models.test_run import TestRunSummary
from testgen.ui.services.contract_run_service import run_version_block, run_version_caption

pytestmark = pytest.mark.unit

FROZEN = datetime(2026, 9, 12, tzinfo=UTC)
AFTER = (FROZEN + timedelta(days=1)).replace(tzinfo=None)
BEFORE = (FROZEN - timedelta(days=1)).replace(tzinfo=None)
PREVIEW_TOOLTIP = "{} was not frozen when this run started. A preview does not count as the contract's status."


def _run(**overrides) -> TestRunSummary:
    fields = {
        "job_execution_id": uuid4(), "test_run_id": uuid4(), "job_schedule_id": None,
        "status": JobStatus.COMPLETED, "created_at": FROZEN, "started_at": FROZEN,
        "completed_at": FROZEN, "active_seconds": 300.0, "error_message": None, "progress": [],
        "table_groups_name": "sales_tables", "test_suite": "orders_contract", "project_code": "demo",
        "project_name": "Demo", "test_ct": 5, "passed_ct": 5, "warning_ct": 0, "failed_ct": 0,
        "error_ct": 0, "log_ct": 0, "dismissed_ct": 0, "dq_score_testing": None, "total_count": 1,
    }
    fields.update(overrides)
    return TestRunSummary(**fields)


def test_an_active_verification():
    run = _run(version_number=3, version_frozen_at=FROZEN, active_version_number=3, test_starttime=AFTER)
    assert run_version_block(run) == {"value": "v3 active · Verification", "tooltip": "v3 is the agreement in force."}
    assert run_version_caption(run) == "v3 active"


def test_a_superseded_verification():
    run = _run(version_number=2, version_frozen_at=FROZEN, active_version_number=3, test_starttime=AFTER)
    assert run_version_block(run) == {
        "value": "v2 superseded · Verification",
        "tooltip": "The contract has since moved on. v3 is the agreement in force.",
    }
    assert run_version_caption(run) == "v2 superseded"


def test_a_draft_preview():
    run = _run(version_number=4, active_version_number=3, test_starttime=AFTER)
    assert run_version_block(run) == {"value": "v4 draft · Preview", "tooltip": PREVIEW_TOOLTIP.format("v4")}
    assert run_version_caption(run) == "v4 draft · Preview"


def test_a_preview_stays_a_preview_after_its_version_is_frozen():
    run = _run(version_number=4, version_frozen_at=FROZEN, active_version_number=4, test_starttime=BEFORE)
    assert run_version_block(run) == {"value": "v4 active · Preview", "tooltip": PREVIEW_TOOLTIP.format("v4")}
    assert run_version_caption(run) == "v4 active · Preview"


def test_a_preview_of_a_since_superseded_version():
    run = _run(version_number=2, version_frozen_at=FROZEN, active_version_number=3, test_starttime=BEFORE)
    assert run_version_block(run) == {"value": "v2 superseded · Preview", "tooltip": PREVIEW_TOOLTIP.format("v2")}
    assert run_version_caption(run) == "v2 superseded · Preview"


def test_a_run_started_at_the_freeze_instant_is_a_verification():
    run = _run(
        version_number=3, version_frozen_at=FROZEN, active_version_number=3, test_starttime=FROZEN.replace(tzinfo=None)
    )
    assert run_version_block(run)["value"] == "v3 active · Verification"
    assert run_version_caption(run) == "v3 active"


def test_a_queued_run_of_a_frozen_version_is_a_verification():
    run = _run(version_number=3, version_frozen_at=FROZEN, active_version_number=3)
    assert run_version_block(run)["value"] == "v3 active · Verification"
    assert run_version_caption(run) == "v3 active"


def test_a_discarded_draft():
    run = _run(version_discarded=True, active_version_number=3, test_starttime=AFTER)
    assert run_version_block(run) == {
        "value": "Discarded draft · Preview",
        "tooltip": "This run checked a draft that was later discarded. A preview does not count as the contract's status.",
    }
    assert run_version_caption(run) == "discarded draft · Preview"


def test_a_regular_run():
    run = _run(test_starttime=AFTER)
    assert run_version_block(run) is None
    assert run_version_caption(run) is None
