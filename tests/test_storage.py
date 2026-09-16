import json

from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.storage import Store, directory_size


def _make_dataset(store, accession="GSE150368", metadata=None, files=None):
    dataset_dir = store.paths["datasets"] / accession
    dataset_dir.mkdir(parents=True, exist_ok=True)
    (dataset_dir / "phenotype.parquet").write_bytes(b"phenotype")
    metadata = metadata or {"accession": accession, "title": "Prostate cancer ADT", "platforms": [{"index": 0, "id": "GPL20795"}], "sample_count": 2}
    (dataset_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    for name, payload in (files or {}).items():
        (dataset_dir / name).write_bytes(payload)
    store.save_dataset(accession, dataset_dir, metadata)
    return dataset_dir


def _make_analysis(store, accession="GSE150368", analysis_id="abc123", payload=b"plot"):
    result_dir = store.paths["analyses"] / analysis_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "observations.parquet").write_bytes(payload)
    store.save_analysis(analysis_id, accession, {"accession": accession}, result_dir)
    return result_dir


def test_directory_size_sums_nested_files(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "a.bin").write_bytes(b"12345")
    (tmp_path / "nested" / "b.bin").write_bytes(b"123")

    assert directory_size(tmp_path) == 8
    assert directory_size(tmp_path / "missing") == 0


def test_store_datasets_lists_saved_rows(tmp_path):
    store = Store(tmp_path)
    _make_dataset(store)

    rows = store.datasets()

    assert [row["accession"] for row in rows] == ["GSE150368"]


def test_datasets_endpoint_reports_sizes_and_analyses(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset_dir = _make_dataset(store, files={"platform-0-expression.parquet": b"x" * 100})
    _make_analysis(store)
    raw = store.paths["raw"] / "GSE150368_family.soft.gz"
    raw.write_bytes(b"y" * 50)
    expected_dataset_size = directory_size(dataset_dir)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).get("/api/datasets")

    assert response.status_code == 200
    body = response.json()
    row = body["datasets"][0]
    assert row["accession"] == "GSE150368"
    assert row["title"] == "Prostate cancer ADT"
    assert row["status"] == "ready"
    assert row["analyses_count"] == 1
    assert row["dataset_size"] == expected_dataset_size
    assert row["raw_size"] == 50
    assert row["total_size"] == expected_dataset_size + 50
    assert body["total_bytes"] == row["total_size"]


def test_datasets_endpoint_marks_missing_directory(tmp_path, monkeypatch):
    store = Store(tmp_path)
    metadata = {"accession": "GSE1", "title": "Gone", "platforms": [], "sample_count": 1}
    dataset_dir = store.paths["datasets"] / "GSE1"
    store.save_dataset("GSE1", dataset_dir, metadata)
    monkeypatch.setattr(main, "store", store)

    row = TestClient(app).get("/api/datasets").json()["datasets"][0]

    assert row["status"] == "missing"
    assert row["dataset_size"] == 0


def test_delete_dataset_removes_files_analyses_and_row(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset_dir = _make_dataset(store, files={"platform-0-expression.parquet": b"x" * 100})
    result_dir = _make_analysis(store)
    raw = store.paths["raw"] / "GSE150368_family.soft.gz"
    raw.write_bytes(b"y" * 50)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).delete("/api/datasets/GSE150368")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] == "GSE150368"
    assert body["freed_bytes"] > 100
    assert not dataset_dir.exists()
    assert not result_dir.exists()
    assert not raw.exists()
    assert store.dataset("GSE150368") is None
    assert store.analyses() == []


def test_delete_unknown_dataset_returns_404(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).delete("/api/datasets/GSE999999")

    assert response.status_code == 404


def test_delete_invalid_accession_returns_400(tmp_path, monkeypatch):
    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)

    response = TestClient(app).delete("/api/datasets/not-an-accession")

    assert response.status_code == 400
