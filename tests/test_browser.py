import os
import shutil
import subprocess
import sys
import webbrowser

import app.main as main
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


def test_open_browser_uses_startfile_on_windows(monkeypatch):
    opened = {}

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", lambda url: opened.setdefault("url", url), raising=False)

    assert _open_browser("http://127.0.0.1:46261") is True
    assert opened["url"] == "http://127.0.0.1:46261"


def test_open_browser_windows_failure_notifies(monkeypatch):
    def fail(_url):
        raise OSError("no handler")

    notified = {}

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(os, "startfile", fail, raising=False)
    monkeypatch.setattr(webbrowser, "open", lambda url: False)
    monkeypatch.setattr(main, "_notify", lambda message: notified.setdefault("message", message))

    assert _open_browser("http://127.0.0.1:46261") is False
    assert "http://127.0.0.1:46261" in notified["message"]


def test_open_browser_uses_open_on_macos(monkeypatch):
    calls = {}

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")

    def fake_popen(command, **kwargs):
        calls["command"] = command
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    assert _open_browser("http://127.0.0.1:46261") is True
    assert calls["command"] == ["open", "http://127.0.0.1:46261"]
