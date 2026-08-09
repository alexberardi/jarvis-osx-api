"""Generic Shortcuts runner — the extensibility escape hatch (PRD API surface).

Anything buildable in Shortcuts (including HomeKit scenes, which have no other
macOS API) becomes a Jarvis capability with zero new endpoints.
"""

import shutil
import subprocess
from dataclasses import dataclass


def shortcuts_cli_present() -> bool:
    return shutil.which("shortcuts") is not None


@dataclass
class ShortcutResult:
    status: str  # ok | error | timeout | cli_missing
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""


def _run_subprocess(cmd: list[str], input_text: str | None, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True, timeout=timeout)


class ShortcutsRunner:
    def __init__(self, runner=None):
        self._run = runner or _run_subprocess

    def run(self, name: str, input_text: str | None = None, timeout: float = 60.0) -> ShortcutResult:
        if not shortcuts_cli_present():
            return ShortcutResult(status="cli_missing")
        cmd = ["shortcuts", "run", name]
        if input_text is not None:
            cmd += ["-i", "-"]
        try:
            proc = self._run(cmd, input_text, timeout)
        except subprocess.TimeoutExpired:
            return ShortcutResult(status="timeout")
        status = "ok" if proc.returncode == 0 else "error"
        return ShortcutResult(
            status=status,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
