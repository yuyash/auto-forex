import logging
from io import StringIO

from autoforex.core.logging import CORE_LOGGER_NAME, LogLevel, configure_logging, get_logger


class TrackingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def emit(self, record: logging.LogRecord) -> None:
        _ = record

    def close(self) -> None:
        self.closed = True
        super().close()


def reset_logger(logger: logging.Logger) -> None:
    for handler in tuple(logger.handlers):
        if not isinstance(handler, logging.NullHandler):
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


class TestLogging:
    def test_get_logger_namespaces_core_loggers(self) -> None:
        assert get_logger().name == CORE_LOGGER_NAME
        assert get_logger("tasks.execution").name == "core.tasks.execution"
        assert get_logger("core.events").name == "core.events"
        assert get_logger("autoforex.core.tasks.execution").name == "core.tasks.execution"

    def test_configure_logging_sets_standalone_handler(self) -> None:
        stream = StringIO()
        logger = configure_logging(
            level=LogLevel.INFO,
            stream=stream,
            format="%(levelname)s %(name)s %(message)s",
            replace_handlers=True,
        )
        try:
            get_logger("test").info("standalone logging works")

            assert "INFO core.test standalone logging works" in stream.getvalue()
        finally:
            reset_logger(logger)

    def test_configure_logging_reuses_handler_for_the_same_stream(self) -> None:
        stream = StringIO()
        logger = configure_logging(
            stream=stream,
            format="%(message)s",
            replace_handlers=True,
        )
        try:
            configure_logging(stream=stream, format="%(message)s")
            get_logger("test").info("written once")

            output_handlers = tuple(
                handler
                for handler in logger.handlers
                if not isinstance(handler, logging.NullHandler)
            )
            assert len(output_handlers) == 1
            assert stream.getvalue().count("written once") == 1
        finally:
            reset_logger(logger)

    def test_configure_logging_closes_replaced_handlers(self) -> None:
        replaced = TrackingHandler()
        logger = configure_logging(handler=replaced, replace_handlers=True)
        try:
            configure_logging(stream=StringIO(), replace_handlers=True)

            assert replaced.closed
        finally:
            reset_logger(logger)
