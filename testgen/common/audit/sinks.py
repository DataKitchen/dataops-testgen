import functools
import json
import logging
import os
from collections.abc import Sequence
from typing import Protocol

from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

from testgen import settings
from testgen.common.audit.record import AuditRecord

LOG = logging.getLogger("testgen")

AUDIT_LOG_FILE_NAME = "audit.log"


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


class _UnavailableSink:
    def __init__(self, path: str) -> None:
        self._path = path

    def write(self, records: Sequence[AuditRecord]) -> None:
        for record in records:
            LOG.error("Audit record %s (%s) not written: %s could not be opened", record.id, record.action, self._path)


@functools.cache
def get_sink() -> AuditSink:
    """The sink configured for this process."""
    if not settings.AUDIT_LOG_ENABLED:
        return _NullSink()
    path = os.path.join(settings.LOG_FILE_PATH, AUDIT_LOG_FILE_NAME)
    try:
        return FileSink(path, backup_count=int(settings.AUDIT_LOG_MAX_QTY))
    except Exception:
        LOG.exception("Audit log %s could not be opened", path)
        return _UnavailableSink(path)
