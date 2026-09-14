import sys

from fastapi.testclient import TestClient

from app.main import app


def test_standard_streams_are_available():
    assert sys.stdout is not None
    assert sys.stderr is not None


def test_shutdown_sets_server_exit(monkeypatch):
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    monkeypatch.setattr(app.state, "server", fake, raising=False)

    response = TestClient(app).post("/api/shutdown")

    assert response.status_code == 200
    assert fake.should_exit is True


def test_shutdown_rejects_foreign_origin(monkeypatch):
    class FakeServer:
        should_exit = False

    fake = FakeServer()
    monkeypatch.setattr(app.state, "server", fake, raising=False)

    response = TestClient(app).post("/api/shutdown", headers={"origin": "https://evil.example"})

    assert response.status_code == 403
    assert fake.should_exit is False


def test_static_path_traversal_is_blocked():
    client = TestClient(app)
    for filename in ("..%2F..%2Fpyproject.toml", "..%5C..%5Cpyproject.toml", "..%2Fmain.py"):
        response = client.get(f"/static/{filename}")
        assert response.status_code == 404, filename


def test_static_files_are_served():
    response = TestClient(app).get("/static/home.js")
    assert response.status_code == 200
