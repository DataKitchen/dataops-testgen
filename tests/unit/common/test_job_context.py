from uuid import uuid4

import pytest

from testgen.common.enums import JobSource
from testgen.common.job_context import JobContext, job_context, measurements_for, record_measurement

pytestmark = pytest.mark.unit


def test_a_measurement_is_kept_for_the_job_being_run():
    job_id = uuid4()
    token = job_context.set(JobContext(job_id=job_id, source=JobSource.scheduler))
    try:
        record_measurement("prediction_duration", 2.0)
        assert measurements_for(job_id) == {"prediction_duration": 2.0}
        assert measurements_for(uuid4()) == {}
    finally:
        job_context.reset(token)


def test_a_measurement_outside_a_job_is_dropped():
    """The default context is shared by every caller in the process, so it must hold nothing."""
    record_measurement("prediction_duration", 2.0)

    assert job_context.get().measurements == {}
