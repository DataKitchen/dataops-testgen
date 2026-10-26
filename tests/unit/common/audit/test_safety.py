import pytest

from testgen.common.audit.projects import record_project_created
from testgen.common.audit.safety import never_raises

pytestmark = pytest.mark.unit


def test_a_failing_audit_function_logs_and_returns_its_fallback(caplog):
    @never_raises(dict)
    def read_changes() -> dict:
        raise RuntimeError("database gone")

    assert read_changes() == {}
    assert "Audit read_changes failed" in caplog.text


def test_a_failing_audit_helper_does_not_reach_the_caller(audit_session, audit_log, caplog):
    record_project_created(object())
    audit_session.commit()

    assert audit_log.records() == []
    assert "Audit record_project_created failed" in caplog.text
