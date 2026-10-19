import functools
import json
import logging
import os
import threading
from collections.abc import Sequence
from typing import Protocol

from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

from testgen import settings
from testgen.common.audit.record import AuditRecord

LOG = logging.getLogger("testgen")

AUDIT_LOG_FILE_NAME = "audit.log"

_handler_lock = threading.Lock()


class AuditSink(Protocol):
    def write(self, records: Sequence[AuditRecord]) -> None:
        """Write ``records``. Must not raise."""


class _AuditFileHandler(ConcurrentTimedRotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:  # noqa: ARG002
        LOG.exception("Audit record could not be written to %s", self.baseFilename)


class FileSink:
    """Writes each record as one JSON line to a file rotated daily, safe for concurrent processes."""

    def __init__(self, path: str, backup_count: int) -> None:
        # Not a child of the "testgen" logger, so records never reach the application log or stdout.
        self._logger = logging.getLogger(f"testgen_audit.{path}")
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)
        with _handler_lock:
            if not self._logger.handlers:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                handler = _AuditFileHandler(path, when="MIDNIGHT", interval=1, backupCount=backup_count)
                handler.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(handler)

    def write(self, records: Sequence[AuditRecord]) -> None:
        for record in records:
            try:
                line = json.dumps(record.to_dict(), default=str)
            except Exception:
                LOG.exception("Audit record could not be serialized: %s", record.action)
                continue
            self._logger.info(line)

    def close(self) -> None:
        for handler in list(self._logger.handlers):
            handler.close()
            self._logger.removeHandler(handler)


class _NullSink:
    def write(self, records: Sequence[AuditRecord]) -> None:
        pass


class _ReopeningSink:
    """Opens the audit file on the first write that can, and writes through it from then on."""

    def __init__(self, path: str, backup_count: int) -> None:
        self._path = path
        self._backup_count = backup_count
        self._sink: FileSink | None = None

    def write(self, records: Sequence[AuditRecord]) -> None:
        if self._sink is None:
            try:
                self._sink = FileSink(self._path, self._backup_count)
            except Exception:
                LOG.exception("Audit log %s could not be opened", self._path)
        if self._sink is None:
            for record in records:
                LOG.error("Audit record %s (%s) not written", record.id, record.action)
            return
        self._sink.write(records)

    def close(self) -> None:
        if self._sink is not None:
            self._sink.close()


@functools.cache
def get_sink() -> AuditSink:
    """The sink configured for this process."""
    if not settings.AUDIT_LOG_ENABLED:
        return _NullSink()
    return _ReopeningSink(os.path.join(settings.LOG_FILE_PATH, AUDIT_LOG_FILE_NAME), int(settings.AUDIT_LOG_MAX_QTY))
