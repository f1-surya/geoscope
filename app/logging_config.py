from __future__ import annotations

import logging
import os
import sys
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
    """Attach rotating file (and best-effort stderr) handlers to the root logger.

    The file handler is the authoritative sink: PyInstaller windowed builds on
    Windows have no usable stdout/stderr, so the log file is the only record of
    what happened. UTF-8 is used explicitly so Unicode messages never raise on
    a cp1252-configured Windows console.
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

    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        stream_handler._geoscope_marker = _HANDLER_MARKER  # type: ignore[attr-defined]
        root.addHandler(stream_handler)

    logging.captureWarnings(True)
    _configured_path = log_path
    return log_path


def log_path() -> Path | None:
    return _configured_path
