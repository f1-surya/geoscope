from pathlib import Path

from app.paths import application_data_dir, ensure_data_dirs


def test_data_dir_honors_environment_override(monkeypatch, tmp_path):
    target = tmp_path / "custom-data"
    monkeypatch.setenv("GEOSCOPE_DATA_DIR", str(target))

    assert application_data_dir() == target

    paths = ensure_data_dirs()
    assert paths["root"] == target
    assert paths["logs"].is_dir()
    assert paths["datasets"].is_dir()


def test_data_dir_expands_user(monkeypatch):
    monkeypatch.setenv("GEOSCOPE_DATA_DIR", "~/geoscope-custom")

    assert application_data_dir() == (Path.home() / "geoscope-custom")
