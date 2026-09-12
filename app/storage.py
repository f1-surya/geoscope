from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import ensure_data_dirs


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path | None = None):
        self.paths = ensure_data_dirs(root)
        # FastAPI may serve requests from a different thread than the one
        # that initialized the application. Serialize access to this small
        # local database while allowing that usage pattern.
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.paths["database"], check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                accession TEXT PRIMARY KEY, path TEXT NOT NULL, metadata TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analyses (
                id TEXT PRIMARY KEY, accession TEXT NOT NULL, config TEXT NOT NULL,
                result_path TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(accession) REFERENCES datasets(accession)
            );
            """
        )
        self.connection.commit()

    def dataset(self, accession: str) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute("SELECT * FROM datasets WHERE accession = ?", (accession,)).fetchone()

    def save_dataset(self, accession: str, path: Path, metadata: dict[str, Any]) -> None:
        now = utc_now()
        with self._lock:
            self.connection.execute(
                "INSERT INTO datasets VALUES (?, ?, ?, ?, ?) ON CONFLICT(accession) DO UPDATE SET path=excluded.path, metadata=excluded.metadata, updated_at=excluded.updated_at",
                (accession, str(path), json.dumps(metadata), now, now),
            )
            self.connection.commit()

    def save_analysis(self, analysis_id: str, accession: str, config: dict[str, Any], result_path: Path) -> None:
        with self._lock:
            self.connection.execute(
                "INSERT INTO analyses VALUES (?, ?, ?, ?, ?)",
                (analysis_id, accession, json.dumps(config), str(result_path), utc_now()),
            )
            self.connection.commit()

    def analyses(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute("SELECT * FROM analyses ORDER BY created_at DESC").fetchall()
            return [dict(row) for row in rows]

    def analysis(self, analysis_id: str) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute("SELECT * FROM analyses WHERE id = ?", (analysis_id,)).fetchone()

    def update_analysis_config(self, analysis_id: str, config: dict[str, Any]) -> None:
        with self._lock:
            self.connection.execute("UPDATE analyses SET config = ? WHERE id = ?", (json.dumps(config), analysis_id))
            self.connection.commit()
