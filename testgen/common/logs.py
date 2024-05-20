__all__ = ["configure_logging"]

import io
import logging
import logging.handlers
import os
import sys
import threading


def configure_logging(
    level: int = logging.DEBUG,
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_to_file: bool = False,
) -> None:
    """
    Configures the testgen logger.
    """
    logger = logging.getLogger("testgen")
    logger.setLevel(level)

    formatter = logging.Formatter(log_format)

    console_out_handler = logging.StreamHandler(stream=sys.stdout)
    console_out_handler.setLevel(logging.DEBUG)
    console_out_handler.setFormatter(formatter)
    console_out_handler.addFilter(LessThanFilter(logging.WARNING))

    console_err_handler = logging.StreamHandler(stream=sys.stderr)
    console_err_handler.setLevel(logging.WARNING)
    console_err_handler.setFormatter(formatter)

    logger.addHandler(console_out_handler)
    logger.addHandler(console_err_handler)

    if log_to_file:
        os.makedirs("/var/log/testgen", exist_ok=True)

        file_handler = logging.handlers.TimedRotatingFileHandler(
            "/var/log/testgen/app.log",
            when="D",
            interval=1,
            backupCount=15,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)

        logger.addHandler(file_handler)


class LessThanFilter(logging.Filter):
    def __init__(self, maximum: int, name: str = "") -> None:
        super().__init__(name)
        self._maximum = maximum

    def filter(self, record):
        return record.levelno < self._maximum


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
