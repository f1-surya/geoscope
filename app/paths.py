from __future__ import annotations

import os
import sys
from pathlib import Path


def application_data_dir() -> Path:
    """Return a writable per-user data directory on all supported systems."""
    override = os.environ.get("GEOSCOPE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "GEOscope"


def ensure_data_dirs(root: Path | None = None) -> dict[str, Path]:
    base = root or application_data_dir()
    paths = {
        "root": base,
        "datasets": base / "datasets",
        "analyses": base / "analyses",
        "artifacts": base / "artifacts",
        "raw": base / "raw",
        "logs": base / "logs",
        "database": base / "geoscope.sqlite3",
    }
    for path in paths.values():
        if path.suffix != ".sqlite3":
            path.mkdir(parents=True, exist_ok=True)
    return paths
