from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "geoscope.log"
MAX_BYTES = 2_000_000
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s [%(threadName)s]: %(message)s"
_HANDLER_MARKER = "geoscope-file-handler"

_configured_path: Path | None = None


def _resolve_level() -> int:
    name = os.environ.get("GEOSCOPE_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, name, logging.INFO) if name else logging.INFO


def configure_logging(logs_dir: Path) -> Path:
    """Attach a rotating file handler to the root logger.

    The file is the authoritative (and only) sink: PyInstaller windowed builds
    on Windows have no usable stdout/stderr, and printing records to a console
    would only duplicate what is already written to disk. UTF-8 is used
    explicitly so Unicode messages never raise on a cp1252-configured Windows
    console.
    """
    global _configured_path

    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / LOG_FILENAME

    root = logging.getLogger()
    root.setLevel(_resolve_level())
    for handler in list(root.handlers):
        if getattr(handler, "_geoscope_marker", None) == _HANDLER_MARKER:
            root.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._geoscope_marker = _HANDLER_MARKER  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    logging.captureWarnings(True)
    _configured_path = log_path
    return log_path


def log_path() -> Path | None:
    return _configured_path


def install_exception_logging(logger_name: str = "geoscope") -> None:
    """Route uncaught exceptions from any thread to the log file.

    Python's default hooks write unhandled tracebacks to stderr, which is lost
    in a windowed build and no longer emitted to the console. Capturing them
    guarantees every unexpected failure leaves a record on disk.
    """
    logger = logging.getLogger(logger_name)

    def handle(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)
