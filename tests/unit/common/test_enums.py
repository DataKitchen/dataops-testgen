import pytest

from testgen.common.enums import JOB_STATUS_LABEL, JobStatus
from testgen.common.models.profiling_run import ProfilingRunSummary
from testgen.common.models.test_run import TestRunSummary

pytestmark = pytest.mark.unit


def test_job_status_label_covers_every_status():
    # A missing entry would surface a raw lowercase status code (e.g. "cancel_requested")
    # in run lists, emails, and MCP output instead of a display label.
    assert set(JOB_STATUS_LABEL) == set(JobStatus)


def test_run_summaries_share_the_job_status_label_map():
    assert TestRunSummary.STATUS_LABEL is JOB_STATUS_LABEL
    assert ProfilingRunSummary.STATUS_LABEL is JOB_STATUS_LABEL
