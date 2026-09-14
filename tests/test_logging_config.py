import logging

from app.logging_config import configure_logging, log_path


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
