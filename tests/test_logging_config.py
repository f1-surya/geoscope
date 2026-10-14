import logging
import sys
import threading

from app.logging_config import configure_logging, install_exception_logging, log_path


def test_configure_logging_writes_records(tmp_path):
    path = configure_logging(tmp_path)

    logger = logging.getLogger("geoscope.test")
    logger.warning("hello from the test suite")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert path == tmp_path / "geoscope.log"
    assert "hello from the test suite" in path.read_text(encoding="utf-8")
    assert log_path() == path


def test_configure_logging_is_idempotent(tmp_path):
    configure_logging(tmp_path)
    before = len(logging.getLogger().handlers)

    configure_logging(tmp_path)

    assert len(logging.getLogger().handlers) == before


def test_configure_logging_honors_level_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOSCOPE_LOG_LEVEL", "DEBUG")

    configure_logging(tmp_path)

    assert logging.getLogger().level == logging.DEBUG


def test_configure_logging_writes_only_to_file(tmp_path, capsys):
    path = configure_logging(tmp_path)

    logging.getLogger("geoscope.test").warning("file only please")
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert "file only please" not in capsys.readouterr().err
    assert "file only please" in path.read_text(encoding="utf-8")


def test_install_exception_logging_logs_uncaught(tmp_path):
    path = configure_logging(tmp_path)
    original_sys, original_thread = sys.excepthook, threading.excepthook
    try:
        install_exception_logging()
        try:
            raise RuntimeError("uncaught boom")
        except RuntimeError as error:
            sys.excepthook(type(error), error, error.__traceback__)
    finally:
        sys.excepthook, threading.excepthook = original_sys, original_thread

    content = path.read_text(encoding="utf-8")
    assert "Unhandled exception" in content
    assert "uncaught boom" in content


def test_install_exception_logging_logs_background_thread(tmp_path):
    path = configure_logging(tmp_path)
    original_sys, original_thread = sys.excepthook, threading.excepthook

    def boom():
        raise ValueError("thread boom")

    try:
        install_exception_logging()
        thread = threading.Thread(target=boom)
        thread.start()
        thread.join()
    finally:
        sys.excepthook, threading.excepthook = original_sys, original_thread

    assert "thread boom" in path.read_text(encoding="utf-8")
