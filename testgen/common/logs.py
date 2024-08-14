__all__ = ["configure_logging"]

import io
import logging
import logging.handlers
import os
import sys
import threading

from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

from testgen import settings


def configure_logging(
    level: int = logging.DEBUG,
    log_format: str = "[PID: %(process)s] %(asctime)s - %(levelname)s - %(message)s",
) -> None:
    """
    Configures the testgen logger.
    """
    logger = logging.getLogger("testgen")
    logger.setLevel(level)

    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        formatter = logging.Formatter(log_format)

        console_out_handler = logging.StreamHandler(stream=sys.stdout)
        if settings.IS_DEBUG:
            console_out_handler.setLevel(level)
        else:
            console_out_handler.setLevel(logging.WARNING)
        console_out_handler.setFormatter(formatter)

        console_err_handler = logging.StreamHandler(stream=sys.stderr)
        console_err_handler.setLevel(logging.WARNING)
        console_err_handler.setFormatter(formatter)

        logger.addHandler(console_out_handler)
        logger.addHandler(console_err_handler)

        if settings.LOG_TO_FILE:
            os.makedirs(settings.LOG_FILE_PATH, exist_ok=True)

            file_handler = ConcurrentTimedRotatingFileHandler(
                get_log_full_path(),
                when="D",
                interval=1,
                backupCount=int(settings.LOG_FILE_MAX_QTY),
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)

            logger.addHandler(file_handler)


def get_log_full_path() -> str:
    return os.path.join(settings.LOG_FILE_PATH, "app.log")


class LogPipe(threading.Thread, io.TextIOBase):
    def __init__(self, logger: logging.Logger, log_level: int) -> None:
        threading.Thread.__init__(self)

        self.daemon = False
        self.logger = logger
        self.level = log_level
        self.readDescriptor, self.writeDescriptor = os.pipe()
        self.start()

    def run(self) -> None:
        with os.fdopen(self.readDescriptor) as reader:
            for line in iter(reader.readline, ""):
                self.logger.log(self.level, line.strip("\n"))

    def fileno(self) -> int:
        return self.writeDescriptor

    def close(self) -> None:
        os.close(self.writeDescriptor)
