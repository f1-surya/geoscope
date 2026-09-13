from __future__ import annotations

import threading
import time
from typing import Any


def human_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class ProgressReporter:
    """Publishes coarse progress for one long-running operation.

    All values are plain JSON-friendly types so the snapshot can be returned
    directly from an HTTP endpoint. ``fraction`` is ``None`` when the total
    work is unknown, letting the client render an indeterminate bar.
    """

    def __init__(self, tracker: "ProgressTracker", key: str, accession: str) -> None:
        self._tracker = tracker
        self._key = key
        self._state: dict[str, Any] = {
            "active": True,
            "accession": accession,
            "stage": "pending",
            "message": "Preparing…",
            "fraction": None,
            "detail": "",
            "eta_seconds": None,
            "bytes_downloaded": None,
            "bytes_total": None,
            "info": {"accession": accession},
            "done": False,
            "error": None,
            "_started": time.monotonic(),
            "_stage_started": time.monotonic(),
            "_finished": None,
        }
        self._publish()

    def stage(self, name: str, message: str = "") -> None:
        self._state.update(
            stage=name,
            message=message,
            fraction=None,
            detail="",
            eta_seconds=None,
            bytes_downloaded=None,
            bytes_total=None,
            _stage_started=time.monotonic(),
        )
        self._publish()

    def fraction(self, value: float, detail: str | None = None) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._state["fraction"] = value
        if detail is not None:
            self._state["detail"] = detail
        if value > 0:
            self._state["eta_seconds"] = round(self._stage_elapsed() * (1 - value) / value, 1)
        else:
            self._state["eta_seconds"] = None
        self._publish()

    def bytes(self, downloaded: int, total: int | None) -> None:
        self._state["bytes_downloaded"] = downloaded
        self._state["bytes_total"] = total
        if total:
            value = min(1.0, downloaded / total)
            self._state["fraction"] = value
            self._state["detail"] = f"{human_bytes(downloaded)} / {human_bytes(total)}"
            self._state["eta_seconds"] = round(self._stage_elapsed() * (total - downloaded) / downloaded, 1) if downloaded else None
        else:
            self._state["fraction"] = None
            self._state["detail"] = human_bytes(downloaded)
            self._state["eta_seconds"] = None
        self._publish()

    def info(self, **fields: Any) -> None:
        self._state["info"].update(fields)
        self._publish()

    def succeed(self) -> None:
        self._state.update(active=False, done=True, error=None, fraction=1.0, eta_seconds=0, _finished=time.monotonic())
        self._publish()

    def fail(self, message: str) -> None:
        self._state.update(active=False, done=True, error=str(message), _finished=time.monotonic())
        self._publish()

    def _stage_elapsed(self) -> float:
        return time.monotonic() - self._state["_stage_started"]

    def _publish(self) -> None:
        state = dict(self._state)
        end = state.pop("_finished", None) or time.monotonic()
        state["elapsed_seconds"] = round(end - state.pop("_started"), 1)
        state.pop("_stage_started", None)
        self._tracker._set(self._key, state)


class ProgressTracker:
    """Small in-memory registry keyed by accession.

    The application is a single-user local tool, so a process-wide tracker is
    sufficient and avoids a job-queue dependency. Access is serialized because
    the blocking work and the polling requests run on different threads.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, dict[str, Any]] = {}

    def reporter(self, key: str, accession: str) -> ProgressReporter:
        return ProgressReporter(self, key, accession)

    def _set(self, key: str, state: dict[str, Any]) -> None:
        with self._lock:
            self._items[key] = state

    def snapshot(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            state = self._items.get(key)
            return dict(state) if state else None

    def clear(self, key: str) -> None:
        with self._lock:
            self._items.pop(key, None)


progress_tracker = ProgressTracker()
