import json
import logging
import threading

import pytest

from testgen import settings
from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import record
from testgen.common.audit.sinks import AUDIT_LOG_FILE_NAME, FileSink, get_sink

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


def test_concurrent_first_use_attaches_one_handler(audit_log):
    threads_count = 8
    barrier = threading.Barrier(threads_count)
    sinks = []

    def open_sink():
        barrier.wait()
        sinks.append(FileSink(audit_log.path, backup_count=1))

    threads = [threading.Thread(target=open_sink) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    record(AuditAction.USER_SIGNED_IN)

    assert len(logging.getLogger(f"testgen_audit.{audit_log.path}").handlers) == 1
    assert len(audit_log.records()) == 1
    sinks[0].close()


def test_records_are_written_once_the_folder_becomes_writable(tmp_path, monkeypatch, audit_log, caplog):
    blocker = tmp_path / "late-mount"
    blocker.write_text("")
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(blocker))
    get_sink.cache_clear()

    with caplog.at_level(logging.ERROR, "testgen"):
        record(AuditAction.USER_SIGNED_IN)
    blocker.unlink()
    record(AuditAction.USER_SIGNED_OUT)

    with open(blocker / AUDIT_LOG_FILE_NAME) as file:
        assert [json.loads(line)["action"] for line in file] == ["user.signed_out"]
    assert [r for r in caplog.records if "not written" in r.getMessage()]
