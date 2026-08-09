import subprocess

import services.shortcuts as shortcuts_mod
from services.shortcuts import ShortcutsRunner


def _fake_proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_cli_missing(monkeypatch):
    monkeypatch.setattr(shortcuts_mod.shutil, "which", lambda _: None)
    assert ShortcutsRunner(runner=lambda *a: _fake_proc()).run("Anything").status == "cli_missing"


def test_run_ok(monkeypatch):
    monkeypatch.setattr(shortcuts_mod.shutil, "which", lambda _: "/usr/bin/shortcuts")
    captured = {}

    def runner(cmd, input_text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input_text
        return _fake_proc(stdout="done\n")

    result = ShortcutsRunner(runner=runner).run("Good Morning")
    assert result.status == "ok"
    assert result.stdout == "done\n"
    assert captured["cmd"] == ["shortcuts", "run", "Good Morning"]
    assert captured["input"] is None


def test_run_with_input_pipes_stdin(monkeypatch):
    monkeypatch.setattr(shortcuts_mod.shutil, "which", lambda _: "/usr/bin/shortcuts")
    captured = {}

    def runner(cmd, input_text, timeout):
        captured["cmd"] = cmd
        captured["input"] = input_text
        return _fake_proc()

    ShortcutsRunner(runner=runner).run("Add To List", input_text="tomatoes")
    assert captured["cmd"] == ["shortcuts", "run", "Add To List", "-i", "-"]
    assert captured["input"] == "tomatoes"


def test_run_error(monkeypatch):
    monkeypatch.setattr(shortcuts_mod.shutil, "which", lambda _: "/usr/bin/shortcuts")
    result = ShortcutsRunner(runner=lambda *a: _fake_proc(1, "", "no such shortcut")).run("Nope")
    assert result.status == "error"
    assert result.stderr == "no such shortcut"


def test_run_timeout(monkeypatch):
    monkeypatch.setattr(shortcuts_mod.shutil, "which", lambda _: "/usr/bin/shortcuts")

    def runner(cmd, input_text, timeout):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    assert ShortcutsRunner(runner=runner).run("Slow").status == "timeout"
