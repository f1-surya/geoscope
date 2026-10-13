import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app import main
from app.jobs import OperationCoordinator
from app.progress import ProgressTracker


def test_acquire_reuses_operation_for_same_key():
    tracker = ProgressTracker()
    coordinator = OperationCoordinator(tracker)

    first, first_owner = coordinator.acquire("GSE1", "GSE1")
    second, second_owner = coordinator.acquire("GSE1", "GSE1")
    other, other_owner = coordinator.acquire("GSE2", "GSE2")

    assert first_owner is True
    assert second_owner is False
    assert second is first
    assert other_owner is True
    assert other is not first


def test_release_publishes_result_and_removes_operation():
    tracker = ProgressTracker()
    coordinator = OperationCoordinator(tracker)

    operation, _ = coordinator.acquire("GSE1", "GSE1")
    coordinator.release("GSE1", operation, result={"ok": True})

    assert coordinator.wait(operation) == {"ok": True}
    reopened, owner = coordinator.acquire("GSE1", "GSE1")
    assert owner is True
    assert reopened is not operation


def test_wait_raises_when_owner_reports_error():
    tracker = ProgressTracker()
    coordinator = OperationCoordinator(tracker)

    operation, _ = coordinator.acquire("GSE1", "GSE1")
    coordinator.release("GSE1", operation, error="download failed")

    with pytest.raises(RuntimeError, match="download failed"):
        coordinator.wait(operation)


def test_joiner_does_not_reset_owner_progress():
    tracker = ProgressTracker()
    coordinator = OperationCoordinator(tracker)

    operation, _ = coordinator.acquire("GSE1", "GSE1")
    operation.reporter.bytes(25, 100)
    before = tracker.snapshot("GSE1")

    _, owner = coordinator.acquire("GSE1", "GSE1")
    after = tracker.snapshot("GSE1")

    assert before is not None and after is not None
    assert owner is False
    assert after["fraction"] == before["fraction"] == 0.25
    assert after["bytes_downloaded"] == 25


def test_reconnecting_load_joins_in_flight_download(monkeypatch):
    calls: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def fake_load_dataset(accession, store, progress=None):
        calls.append(accession)
        progress.bytes(1, 2)
        started.set()
        assert release.wait(5)
        return {"accession": accession, "cached": False, "platforms": [{"index": 0, "id": "GPL1"}], "info": {"accession": accession}}

    monkeypatch.setattr(main, "load_dataset", fake_load_dataset)
    client = TestClient(main.app)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/api/datasets/load", json={"accession": "GSE900001"})
        assert started.wait(5)
        second = pool.submit(client.post, "/api/datasets/load", json={"accession": "GSE900001"})
        time.sleep(0.1)
        release.set()
        first_response = first.result(timeout=5)
        second_response = second.result(timeout=5)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == second_response.json()
    assert calls == ["GSE900001"]


def test_reconnecting_load_receives_owner_failure(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def fake_load_dataset(accession, store, progress=None):
        started.set()
        assert release.wait(5)
        raise RuntimeError("downloaded file was corrupt")

    monkeypatch.setattr(main, "load_dataset", fake_load_dataset)
    client = TestClient(main.app)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/api/datasets/load", json={"accession": "GSE900002"})
        assert started.wait(5)
        second = pool.submit(client.post, "/api/datasets/load", json={"accession": "GSE900002"})
        time.sleep(0.1)
        release.set()
        first_response = first.result(timeout=5)
        second_response = second.result(timeout=5)

    assert first_response.status_code == 400
    assert second_response.status_code == 400
    assert "corrupt" in second_response.json()["detail"]
