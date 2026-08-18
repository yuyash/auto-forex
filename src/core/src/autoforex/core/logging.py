"""Logging utilities for core library and standalone scripts."""

from __future__ import annotations

import logging
import sys
from enum import StrEnum
from typing import TextIO

CORE_LOGGER_NAME = "core"
CORE_MODULE_NAME = "autoforex.core"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class LogLevel(StrEnum):
    """Logging levels accepted by :func:`configure_logging`."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    @property
    def number(self) -> int:
        """Return the numeric logging level for this name."""
        return logging.getLevelNamesMapping()[self.value]


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a Core logger without configuring output handlers."""
    if name is None or name in {CORE_LOGGER_NAME, CORE_MODULE_NAME}:
        return logging.getLogger(CORE_LOGGER_NAME)
    if name.startswith(f"{CORE_MODULE_NAME}."):
        name = name.removeprefix(f"{CORE_MODULE_NAME}.")
    if name.startswith(f"{CORE_LOGGER_NAME}."):
        return logging.getLogger(name)
    return logging.getLogger(f"{CORE_LOGGER_NAME}.{name}")


def _remove_output_handlers(logger: logging.Logger) -> None:
    for existing_handler in tuple(logger.handlers):
        if isinstance(existing_handler, logging.NullHandler):
            continue
        logger.removeHandler(existing_handler)
        existing_handler.close()


def _stream_handler(logger: logging.Logger, stream: TextIO | None) -> logging.StreamHandler:
    target_stream = stream if stream is not None else sys.stderr
    for existing_handler in logger.handlers:
        if (
            isinstance(existing_handler, logging.StreamHandler)
            and existing_handler.stream is target_stream
        ):
            return existing_handler
    return logging.StreamHandler(target_stream)


def configure_logging(
    *,
    level: LogLevel = LogLevel.INFO,
    stream: TextIO | None = None,
    handler: logging.Handler | None = None,
    format: str = DEFAULT_LOG_FORMAT,
    datefmt: str | None = None,
    propagate: bool = False,
    replace_handlers: bool = False,
) -> logging.Logger:
    """Configure Core logging for standalone scripts and local tools.

    Applications embedding Core can ignore this function and configure the
    standard Python logging tree themselves.
    """
    logger = get_logger()
    logger.setLevel(LogLevel(level).number)
    logger.propagate = propagate

    if replace_handlers:
        _remove_output_handlers(logger)

    output_handler = handler or _stream_handler(logger, stream)
    if handler is None:
        output_handler.setFormatter(logging.Formatter(format, datefmt=datefmt))
    if output_handler not in logger.handlers:
        logger.addHandler(output_handler)
        logger.debug(
            "Added Core logging handler",
            extra={
                "logger_name": CORE_LOGGER_NAME,
                "handler_class": output_handler.__class__.__name__,
            },
        )
    logger.info(
        "Configured Core logging",
        extra={
            "logger_name": CORE_LOGGER_NAME,
            "logging_level": logging.getLevelName(logger.level),
            "propagate": logger.propagate,
            "handler_count": len(logger.handlers),
        },
    )
    return logger


def _add_null_handler() -> None:
    logger = get_logger()
    if not any(isinstance(handler, logging.NullHandler) for handler in logger.handlers):
        logger.addHandler(logging.NullHandler())


_add_null_handler()
