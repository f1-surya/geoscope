import shutil
import subprocess
import sys
import webbrowser

from app.main import _clean_subprocess_env, _open_browser


def test_clean_subprocess_env_restores_original(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/usr/lib")
    monkeypatch.setenv("LD_PRELOAD", "libproblem.so")

    env = _clean_subprocess_env()

    assert env["LD_LIBRARY_PATH"] == "/usr/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env
    assert "LD_PRELOAD" not in env


def test_clean_subprocess_env_removes_bundle_path(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    env = _clean_subprocess_env()

    assert "LD_LIBRARY_PATH" not in env


def test_clean_subprocess_env_removes_empty_original(monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "")

    env = _clean_subprocess_env()

    assert "LD_LIBRARY_PATH" not in env


def test_open_browser_uses_clean_env(monkeypatch):
    calls = {}

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    def fake_popen(command, **kwargs):
        calls["command"] = command
        calls["env"] = kwargs.get("env")
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert _open_browser("http://127.0.0.1:46261") is True
    assert calls["command"] == ["xdg-open", "http://127.0.0.1:46261"]
    assert "LD_LIBRARY_PATH" not in calls["env"]


def test_open_browser_falls_back_when_opener_missing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: True)

    assert _open_browser("http://127.0.0.1:46261") is True
