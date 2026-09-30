"""The schema label the summary dataclasses hand to the frontend."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from testgen.common.enums import JobStatus
from testgen.common.models.profiling_run import ProfilingRunSummary
from testgen.common.models.table_group import TableGroupStats

pytestmark = pytest.mark.unit


def _stats(sql_flavor_code):
    return TableGroupStats(
        id=uuid4(),
        table_groups_name="claims",
        table_group_schema="main",
        sql_flavor_code=sql_flavor_code,
        table_ct=1,
        column_ct=2,
        approx_record_ct=3,
        record_ct=3,
        approx_data_point_ct=6,
        data_point_ct=6,
    )


def _run_summary(sql_flavor_code):
    return ProfilingRunSummary(
        job_execution_id=uuid4(),
        profiling_run_id=uuid4(),
        job_schedule_id=None,
        project_code="demo",
        status=JobStatus.COMPLETED,
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
        started_at=None,
        completed_at=None,
        active_seconds=None,
        error_message=None,
        progress=[],
        table_groups_name="claims",
        table_group_schema="main",
        sql_flavor_code=sql_flavor_code,
        table_ct=1,
        column_ct=2,
        record_ct=3,
        data_point_ct=6,
        anomaly_ct=0,
        anomalies_definite_ct=0,
        anomalies_likely_ct=0,
        anomalies_possible_ct=0,
        anomalies_dismissed_ct=0,
        dq_score_profiling=None,
        total_count=1,
    )


@pytest.mark.parametrize(
    ("sql_flavor_code", "expected"),
    [
        ("files", None),
        ("salesforce_data360", "Data Space"),
        ("postgresql", "Schema"),
    ],
)
def test_table_group_stats_carry_the_label(sql_flavor_code, expected):
    assert _stats(sql_flavor_code).to_dict()["schema_label"] == expected


@pytest.mark.parametrize(
    ("sql_flavor_code", "expected"),
    [
        ("files", None),
        ("salesforce_data360", "Data Space"),
        ("postgresql", "Schema"),
    ],
)
def test_profiling_run_summaries_carry_the_label(sql_flavor_code, expected):
    assert _run_summary(sql_flavor_code).to_dict()["schema_label"] == expected


def test_the_stored_value_is_reported_alongside_the_label():
    """A flavor that reports no label still stores the schema a run needs to reach the target."""
    payload = _stats("files").to_dict()
    assert payload["table_group_schema"] == "main"
    assert payload["schema_label"] is None
