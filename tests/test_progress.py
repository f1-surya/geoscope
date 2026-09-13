import pandas as pd

from app.analysis.statistics import analyze
from app.progress import human_bytes, ProgressTracker


class _Recorder:
    def __init__(self):
        self.fractions = []
        self.infos = []

    def stage(self, *args, **kwargs):
        pass

    def bytes(self, *args, **kwargs):
        pass

    def fraction(self, value, detail=None):
        self.fractions.append(value)

    def info(self, **fields):
        self.infos.append(fields)


def test_reporter_tracks_download_progress_and_eta():
    tracker = ProgressTracker()
    reporter = tracker.reporter("GSE1", "GSE1")
    reporter.stage("download", "Downloading GSE1 from GEO")
    reporter.bytes(25, 100)

    snapshot = tracker.snapshot("GSE1")

    assert snapshot["active"] is True
    assert snapshot["stage"] == "download"
    assert snapshot["message"] == "Downloading GSE1 from GEO"
    assert snapshot["fraction"] == 0.25
    assert snapshot["bytes_total"] == 100
    assert snapshot["eta_seconds"] is not None
    assert "100" in snapshot["detail"]


def test_reporter_handles_unknown_size_and_merges_info():
    tracker = ProgressTracker()
    reporter = tracker.reporter("GSE2", "GSE2")
    reporter.info(title="Demo series")
    reporter.info(sample_count=4)
    reporter.bytes(2048, None)

    snapshot = tracker.snapshot("GSE2")

    assert snapshot["fraction"] is None
    assert snapshot["eta_seconds"] is None
    assert snapshot["info"] == {"accession": "GSE2", "title": "Demo series", "sample_count": 4}
    assert snapshot["detail"] == human_bytes(2048)


def test_reporter_success_and_failure_states():
    tracker = ProgressTracker()
    assert tracker.snapshot("missing") is None

    reporter = tracker.reporter("GSE3", "GSE3")
    reporter.succeed()
    assert tracker.snapshot("GSE3")["done"] is True
    assert tracker.snapshot("GSE3")["active"] is False

    reporter = tracker.reporter("GSE4", "GSE4")
    reporter.fail("boom")
    snapshot = tracker.snapshot("GSE4")
    assert snapshot["error"] == "boom"
    assert snapshot["active"] is False


def test_analyze_reports_gene_progress():
    data = pd.DataFrame(
        {
            "gene_symbol": ["CD5"] * 4 + ["CD7"] * 4,
            "sample": ["A", "B", "C", "D", "A", "B", "C", "D"],
            "value": [1.0, 2.0, 8.0, 9.0, 3.0, 4.0, 7.0, 6.0],
            "group": ["X", "X", "Y", "Y", "X", "X", "Y", "Y"],
        }
    )
    recorder = _Recorder()

    analyze(data, ["CD5", "CD7"], "group", progress=recorder)

    assert recorder.fractions == [0.5, 1.0]
