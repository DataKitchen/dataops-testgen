__all__ = ["configure_logging"]

import logging
import logging.handlers
import os
import sys

from concurrent_log_handler import ConcurrentTimedRotatingFileHandler

from testgen import settings


def configure_logging(
    level: int = logging.INFO,
    log_format: str = "[PID: %(process)s] %(asctime)s %(levelname)+7s %(message)s",
) -> None:
    """
    Configures the testgen logger.
    """
    logger = logging.getLogger("testgen")
    logger.setLevel(level)

    if not logger.hasHandlers():

        formatter = logging.Formatter(log_format)

        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        if settings.LOG_TO_FILE:
            os.makedirs(settings.LOG_FILE_PATH, exist_ok=True)

            file_handler = ConcurrentTimedRotatingFileHandler(
                get_log_full_path(),
                when="MIDNIGHT",
                interval=1,
                backupCount=int(settings.LOG_FILE_MAX_QTY),
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)


def get_log_full_path() -> str:
    return os.path.join(settings.LOG_FILE_PATH, "app.log")
