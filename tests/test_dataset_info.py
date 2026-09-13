import gzip
import json

import pytest

from app.geo import acquisition
from app.geo.acquisition import dataset_info, fetch_series_summary, load_dataset_info
from app.geo.soft import read_series_metadata
from app.main import app
from app.storage import Store


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


ESUMMARY = {
    "header": {"type": "esummary", "version": "0.3"},
    "result": {
        "uids": ["200150368"],
        "200150368": {
            "uid": "200150368",
            "accession": "GSE150368",
            "title": "Prostate cancer ADT",
            "summary": "A study of androgen deprivation therapy.",
            "gpl": "20795",
            "taxon": "Homo sapiens",
            "gdstype": "Expression profiling by high throughput sequencing",
            "pdat": "2020/09/23",
            "suppfile": "TXT",
            "samples": [{"accession": "GSM1", "title": "sample one"}, {"accession": "GSM2", "title": "sample two"}],
            "n_samples": 2,
            "pubmedids": ["32951005"],
            "bioproject": "PRJNA631926",
            "ftplink": "ftp://ftp.ncbi.nlm.nih.gov/geo/series/GSE150nnn/GSE150368/",
            "extrelations": [{"relationtype": "SRA", "targetobject": "SRP261279"}],
        },
    },
}


def _install_fake_urlopen(monkeypatch, responses):
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        handler = responses(len(calls), request.full_url)
        if isinstance(handler, Exception):
            raise handler
        return _FakeResponse(handler)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(acquisition.time, "sleep", lambda *_: None)
    return calls


def test_fetch_series_summary_normalizes_esummary(monkeypatch):
    _install_fake_urlopen(monkeypatch, lambda *_: ESUMMARY)

    summary = fetch_series_summary("GSE150368")

    assert summary["accession"] == "GSE150368"
    assert summary["title"] == "Prostate cancer ADT"
    assert summary["organism"] == "Homo sapiens"
    assert summary["experiment_type"].startswith("Expression profiling")
    assert summary["platforms"] == ["GPL20795"]
    assert summary["sample_count"] == 2
    assert summary["public_date"] == "2020/09/23"
    assert summary["pubmed_ids"] == ["32951005"]
    assert summary["bioproject"] == "PRJNA631926"
    assert summary["samples"][0] == {"accession": "GSM1", "title": "sample one"}
    assert summary["relations"] == ["SRP261279"]


def test_fetch_series_summary_falls_back_to_esearch(monkeypatch):
    mismatched = json.loads(json.dumps(ESUMMARY))
    mismatched["result"]["200150368"]["accession"] = "GSE999999"
    esearch = {"esearchresult": {"idlist": ["200150368", "100020795"]}}

    def handler(call, url):
        if "esummary" in url and call == 1:
            return mismatched
        if "esearch" in url:
            return esearch
        return ESUMMARY

    _install_fake_urlopen(monkeypatch, handler)

    summary = fetch_series_summary("GSE150368")

    assert summary["accession"] == "GSE150368"


def test_fetch_series_summary_raises_after_retries(monkeypatch):
    _install_fake_urlopen(monkeypatch, lambda *_: OSError("offline"))

    with pytest.raises(RuntimeError, match="Could not fetch GEO metadata"):
        fetch_series_summary("GSE150368")


def test_dataset_info_prefers_local_fields_and_keeps_geo_fields():
    metadata = {
        "accession": "GSE1",
        "title": "Local title",
        "platforms": [{"index": 0, "id": "GPL1"}],
        "sample_count": 5,
        "probe_count": 42,
        "organism": "Mus musculus",
        "pubmed_ids": ["1"],
        "geo": {
            "title": "GEO title",
            "summary": "GEO summary",
            "organism": "Homo sapiens",
            "platforms": ["9999"],
            "sample_count": 99,
            "bioproject": "PRJNA1",
        },
    }

    info = dataset_info(metadata)

    assert info["title"] == "Local title"
    assert info["platform_ids"] == ["GPL1"]
    assert info["sample_count"] == 5
    assert info["probe_count"] == 42
    assert info["organism"] == "Mus musculus"
    assert info["summary"] == "GEO summary"
    assert info["bioproject"] == "PRJNA1"
    assert info["pubmed_ids"] == ["1"]


SERIES_WITH_EXTRA = """^SERIES = GSE_EXTRA
!Series_title = Extra series
!Series_geo_accession = GSE_EXTRA
!Series_summary = A short summary.
!Series_overall_design = Case control design
!Series_type = Expression profiling by array
!Series_submission_date = Jan 01 2020
!Series_last_update_date = Feb 02 2021
!Series_pubmed_id = 12345
!Series_contributor = Doe,Jane
!Series_sample_organism = Homo sapiens
!Series_relation = BioProject: PRJNA1
!Series_sample_id = GSM1
^SAMPLE = GSM1
!Sample_title = sample one
!Sample_platform_id = GPL1
!sample_table_begin
ID_REF\tVALUE
p1\t1.0
!sample_table_end
"""


def test_read_series_metadata_captures_extended_fields(tmp_path):
    soft = tmp_path / "GSE_EXTRA_family.soft.gz"
    with gzip.open(soft, "wt", encoding="utf-8") as handle:
        handle.write(SERIES_WITH_EXTRA)

    info = read_series_metadata(soft, "GSE_EXTRA")

    assert info.summary == "A short summary."
    assert info.overall_design == "Case control design"
    assert info.experiment_type == "Expression profiling by array"
    assert info.submission_date == "Jan 01 2020"
    assert info.last_update_date == "Feb 02 2021"
    assert info.pubmed_ids == ["12345"]
    assert info.contributors == ["Doe,Jane"]
    assert info.organism == "Homo sapiens"
    assert info.relations == ["BioProject: PRJNA1"]


def test_load_dataset_info_persists_geo_for_cached_dataset(tmp_path, monkeypatch):
    store = Store(tmp_path)
    dataset_dir = store.paths["datasets"] / "GSE150368"
    dataset_dir.mkdir(parents=True)
    metadata = {"accession": "GSE150368", "title": "Local title", "platforms": [], "sample_count": 2}
    store.save_dataset("GSE150368", dataset_dir, metadata)
    (dataset_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    _install_fake_urlopen(monkeypatch, lambda *_: ESUMMARY)

    result = load_dataset_info("GSE150368", store)

    assert result["available"] is True
    assert result["info"]["summary"] == "A study of androgen deprivation therapy."
    stored = json.loads(store.dataset("GSE150368")["metadata"])
    assert stored["geo"]["bioproject"] == "PRJNA631926"
    on_disk = json.loads((dataset_dir / "metadata.json").read_text(encoding="utf-8"))
    assert on_disk["geo"]["accession"] == "GSE150368"


def test_load_dataset_info_fetches_when_uncached(tmp_path, monkeypatch):
    store = Store(tmp_path)
    _install_fake_urlopen(monkeypatch, lambda *_: ESUMMARY)

    result = load_dataset_info("GSE150368", store)

    assert result["available"] is True
    assert result["info"]["title"] == "Prostate cancer ADT"


def test_load_dataset_info_returns_unavailable_without_network(tmp_path, monkeypatch):
    store = Store(tmp_path)
    _install_fake_urlopen(monkeypatch, lambda *_: OSError("offline"))

    result = load_dataset_info("GSE150368", store)

    assert result["available"] is False
    assert result["accession"] == "GSE150368"


def test_info_endpoint_uses_network_summary(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main

    store = Store(tmp_path)
    monkeypatch.setattr(main, "store", store)
    _install_fake_urlopen(monkeypatch, lambda *_: ESUMMARY)

    response = TestClient(app).get("/api/datasets/GSE150368/info")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["info"]["platform_ids"] == ["GPL20795"]
