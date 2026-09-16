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


def test_storage_page_is_served():
    response = TestClient(app).get("/storage")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_home_header_links_to_storage_and_has_quit():
    body = TestClient(app).get("/").text
    assert 'href="/storage"' in body
    assert 'id="quit"' in body
    assert "<footer" not in body


def test_quit_link_and_header_script_on_every_page():
    client = TestClient(app)
    for path in ("/", "/storage", "/analysis/new"):
        body = client.get(path).text
        assert 'id="quit"' in body, path
        assert 'src="/static/header.js"' in body, path
