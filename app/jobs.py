from __future__ import annotations

import threading
from typing import Any

from .progress import ProgressTracker, progress_tracker


class Operation:
    """A single in-flight, keyed operation owned by one request.

    The owner runs the work and publishes progress through ``reporter``; any
    request that arrives while the operation is in flight joins it and waits
    on ``done`` for the owner's ``result`` or ``error``.
    """

    def __init__(self, reporter: Any) -> None:
        self.reporter = reporter
        self.done = threading.Event()
        self.result: Any = None
        self.error: str | None = None


class OperationCoordinator:
    """Coalesce concurrent work that shares a progress key.

    The first caller for a key becomes the owner and runs the work. A caller
    that arrives while that operation is in flight joins it, waits, and
    receives the same result instead of starting duplicate work. Without this,
    a reconnecting client would spawn a second download for the same accession:
    it would race on the same ``.part`` file and overwrite the shared progress
    reporter, making the progress bar flicker between the two runs.
    """

    def __init__(self, tracker: ProgressTracker) -> None:
        self._tracker = tracker
        self._lock = threading.Lock()
        self._operations: dict[str, Operation] = {}

    def acquire(self, key: str, accession: str) -> tuple[Operation, bool]:
        with self._lock:
            operation = self._operations.get(key)
            if operation is not None:
                return operation, False
            operation = Operation(self._tracker.reporter(key, accession))
            self._operations[key] = operation
            return operation, True

    def release(self, key: str, operation: Operation, result: Any = None, error: str | None = None) -> None:
        with self._lock:
            if self._operations.get(key) is operation:
                self._operations.pop(key, None)
            operation.result = result
            operation.error = error
            operation.done.set()

    def wait(self, operation: Operation) -> Any:
        operation.done.wait()
        if operation.error is not None:
            raise RuntimeError(operation.error)
        return operation.result


operations = OperationCoordinator(progress_tracker)
