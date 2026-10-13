import threading

from app.geo import acquisition


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_concurrent_downloads_of_same_target_fetch_once(monkeypatch, tmp_path):
    payload = b"soft file contents"
    calls: list[object] = []

    def fake_urlopen(request, timeout=None, context=None):
        calls.append(request)
        threading.Event().wait(0.05)
        return _FakeResponse(payload)

    monkeypatch.setattr(acquisition.urllib.request, "urlopen", fake_urlopen)
    target = tmp_path / "GSE1_family.soft.gz"

    results: list[object] = []

    def run() -> None:
        results.append(acquisition._download_file("https://example.test/GSE1.soft.gz", target))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(calls) == 1
    assert len(results) == 2
    assert target.read_bytes() == payload
    assert not target.with_suffix(target.suffix + ".part").exists()


def test_cached_download_skips_network(monkeypatch, tmp_path):
    calls: list[object] = []
    monkeypatch.setattr(acquisition.urllib.request, "urlopen", lambda *a, **k: calls.append(a))

    target = tmp_path / "cached.soft.gz"
    target.write_bytes(b"already here")

    assert acquisition._download_file("https://example.test/cached.soft.gz", target) == target
    assert calls == []
