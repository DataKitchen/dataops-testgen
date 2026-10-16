import logging

import pytest

from testgen import settings
from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.sinks import get_sink

pytestmark = pytest.mark.unit


def test_records_never_reach_the_application_log_or_stdout(audit_log, capsys, caplog):
    with caplog.at_level(logging.DEBUG):
        record(AuditAction.USER_SIGNED_IN)

    assert len(audit_log.records()) == 1
    assert "user.signed_in" not in capsys.readouterr().out
    assert not [r for r in caplog.records if "user.signed_in" in r.getMessage()]


def test_each_record_is_one_json_line(audit_log):
    record(AuditAction.USER_SIGNED_IN)
    record(AuditAction.USER_SIGNED_OUT)

    with open(audit_log.path) as file:
        assert len(file.read().splitlines()) == 2


def test_disabled_audit_writes_nothing(audit_log, monkeypatch):
    monkeypatch.setattr(settings, "AUDIT_LOG_ENABLED", False)
    get_sink.cache_clear()

    record(AuditAction.USER_SIGNED_IN)

    assert audit_log.records() == []


def test_unwritable_folder_logs_each_dropped_record(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("")
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(blocker))
    get_sink.cache_clear()

    with caplog.at_level(logging.ERROR, "testgen"):
        record(AuditAction.USER_SIGNED_IN)
        record(AuditAction.USER_SIGNED_OUT)

    dropped = [r for r in caplog.records if "not written" in r.getMessage()]
    assert len(dropped) == 2
